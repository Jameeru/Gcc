"""
OpenAI-powered research engine for the GCC Research Intelligence Platform.

Analyzes a company for Global Capability Center (GCC) opportunities in India
using GPT-4o, returning a structured ResearchResult. Implements the
exponential backoff retry strategy specified in design.md (3 attempts,
base_delay=1.0s, max_delay=60.0s) and validates the model's JSON response
against the required schema before returning it.

Streamlit's execution model is synchronous, so this module uses the
synchronous OpenAI client and `time.sleep` for backoff rather than asyncio,
while preserving the exact retry semantics from the design spec.

**Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 10.1**
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, TypeVar

from openai import OpenAI, APIError, APIConnectionError, RateLimitError

from ..models.entities import ResearchResult
from ..utils.api_keys import OPENAI_API_KEY, get_api_key
from ..utils.config import get_config
from ..utils.logging import get_logger, log_event

logger = get_logger("research_engine")

T = TypeVar("T")

# Exact ANSR research prompt, as specified by the user. Note: the model's
# JSON response keys (has_gcc / fit / pain_points) are intentionally a much
# smaller tri-state schema than the legacy 7-field one this engine used to
# require -- see parse_research_response() below, which derives the legacy
# fields (gcc_presence, suitability_score, business_pain_points, ...) from
# these three so the Dashboard KPIs, History page, and CSV/Excel exports
# keep working unchanged on top of the new prompt.
RESEARCH_PROMPT_TEMPLATE = """You are a research analyst for ANSR, a Global Capability Center (GCC) setup and transformation firm. Research this company using web search.

Company: {company_name}
Domain: {company_domain}

Q1: Does this company already own and operate a GCC / Global Capability Center / Center of Excellence / captive offshore delivery center / shared services center in India? (Not third-party outsourcing — must be their own office.)

Q2: Whether or not they have one, identify pain points relevant to a GCC-setup conversation: talent scarcity, rising costs, layoffs/cost-cutting, competitors with a GCC already, growth that strains back-office scaling (finance, IT, HR, procurement, engineering), or expansion signals.

Respond ONLY with valid JSON, no markdown fences, no preamble, in exactly this format:
{{"has_gcc": "Yes" | "No" | "Uncertain", "fit": "Strong" | "Possible" | "Unlikely", "pain_points": "2-3 sentences, or 'no specific signals found'"}}"""

REQUIRED_FIELDS = ("has_gcc", "fit", "pain_points")

VALID_HAS_GCC = ("Yes", "No", "Uncertain")
VALID_FIT = ("Strong", "Possible", "Unlikely")

# Maps the tri-state "fit" rating onto the legacy 1-10 suitability_score
# scale so older UI surfaces (Dashboard KPIs, History, exports) that sort/
# filter/display by suitability_score keep behaving sensibly.
_FIT_TO_SCORE = {"Strong": 9, "Possible": 5, "Unlikely": 2}

SYSTEM_INSTRUCTION = (
    "You are a business research analyst specializing in Global Capability "
    "Centers (GCCs) in India. Respond only with valid JSON matching the "
    "exact schema requested, with no additional commentary or markdown "
    "formatting."
)


class ResponseParsingError(Exception):
    """
    Internal, provider-agnostic exception raised by `parse_research_response`.

    Each engine (OpenAI's ResearchEngine, Gemini's GeminiEngine) catches this
    and re-raises it as its own public error type (ResearchResponseError /
    GeminiResponseError respectively), so callers keep seeing the error type
    they already expect while both engines share one parsing implementation
    and can't drift apart.
    """


def _extract_json_object(text: str) -> Dict[str, Any]:
    """
    Parse a model response into a JSON object, tolerating the markdown
    fences and stray preamble/postamble text that web-search-grounded model
    calls are more prone to emit than a plain, non-tool JSON-mode call.

    Tries, in order: the raw text as-is, the text with a leading/trailing
    ``` fence (optionally tagged ```json) stripped, and finally the
    substring between the first ``{`` and the last ``}`` in the text.

    Raises:
        json.JSONDecodeError: if no strategy yields valid JSON.
    """
    if text is None:
        raise json.JSONDecodeError("Response was empty", "", 0)
    stripped = text.strip()
    if not stripped:
        raise json.JSONDecodeError("Response was empty", stripped, 0)

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    if stripped.startswith("```"):
        without_fence = stripped.strip("`")
        if "\n" in without_fence:
            first_line, rest = without_fence.split("\n", 1)
            if first_line.strip().isalpha():
                without_fence = rest
        try:
            return json.loads(without_fence.strip())
        except json.JSONDecodeError:
            pass

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(stripped[start : end + 1])

    raise json.JSONDecodeError("No JSON object found in response", stripped, 0)


def _normalize_enum(value: Any, valid_values: tuple, field_name: str, default: str) -> str:
    """Case-insensitively match `value` against `valid_values`, defaulting (with a log) if no match."""
    if isinstance(value, str):
        for candidate in valid_values:
            if value.strip().lower() == candidate.lower():
                return candidate
    logger.warning(
        f"Model returned unrecognized {field_name}={value!r}; defaulting to {default!r}."
    )
    return default


def parse_research_response(
    raw_content: str, company_name: str, company_domain: Optional[str]
) -> ResearchResult:
    """
    Shared parsing/validation logic for the ANSR has_gcc/fit/pain_points
    response schema, used by both the OpenAI and Gemini engines so their
    behavior can't silently drift apart.

    Derives the legacy 7-field schema (gcc_presence, suitability_score,
    business_pain_points, ...) from the three tri-state fields so existing
    UI surfaces keep working, while also populating the new gcc_status/
    fit_rating/pain_points_summary fields with the precise values for the
    new results UI.

    Raises:
        ResponseParsingError: on any structural problem with the response.
    """
    try:
        data: Dict[str, Any] = _extract_json_object(raw_content)
    except json.JSONDecodeError as exc:
        raise ResponseParsingError(f"Model response was not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ResponseParsingError(
            f"Model response must be a JSON object, got: {type(data).__name__}"
        )

    missing = [field for field in REQUIRED_FIELDS if field not in data]
    if missing:
        raise ResponseParsingError(f"Model response missing required fields: {missing}")

    has_gcc = _normalize_enum(data.get("has_gcc"), VALID_HAS_GCC, "has_gcc", "Uncertain")
    fit = _normalize_enum(data.get("fit"), VALID_FIT, "fit", "Possible")
    pain_points = str(data.get("pain_points") or "").strip() or "no specific signals found"

    gcc_presence = has_gcc == "Yes"
    suitability_score = _FIT_TO_SCORE[fit]
    business_pain_points = (
        [] if pain_points.lower() == "no specific signals found" else [pain_points]
    )

    try:
        return ResearchResult(
            company_name=company_name,
            company_domain=company_domain,
            gcc_presence=gcc_presence,
            gcc_location=None,
            suitability_score=suitability_score,
            business_pain_points=business_pain_points,
            expansion_indicators=[],
            hiring_signals=[],
            research_summary=pain_points,
            is_cached=False,
            created_at=datetime.now(timezone.utc),
            gcc_status=has_gcc,
            fit_rating=fit,
            pain_points_summary=pain_points,
        )
    except ValueError as exc:
        raise ResponseParsingError(f"Research result failed validation: {exc}") from exc


class ResearchEngineError(Exception):
    """Base exception for research engine failures."""


class ResearchResponseError(ResearchEngineError):
    """Raised when the model's response is missing fields or malformed."""


class ResearchAPIError(ResearchEngineError):
    """Raised when all retry attempts against the OpenAI API are exhausted."""


class ResearchNoKeyConfiguredError(ResearchEngineError):
    """Raised when no OpenAI API key is configured (neither DB nor env)."""


def exponential_backoff_retry(
    func: Callable[[], T],
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    on_retry: Optional[Callable[[int, Exception], None]] = None,
) -> T:
    """
    Synchronous exponential backoff retry, mirroring design.md's
    `exponential_backoff_retry` spec (3 attempts, base_delay=1.0, max_delay=60.0).

    Args:
        func: Zero-argument callable to invoke.
        max_attempts: Total number of attempts before giving up.
        base_delay: Initial backoff delay in seconds.
        max_delay: Maximum backoff delay in seconds.
        on_retry: Optional callback invoked as (attempt_index, exception) after
            each failed attempt that will be retried, for logging/UI feedback.

    Returns:
        The return value of `func()` on success.

    Raises:
        The last exception raised by `func`, if all attempts fail.

    **Validates: Requirements 5.7, 10.1**
    """
    last_exception: Optional[Exception] = None
    for attempt in range(max_attempts):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001 - we deliberately retry broadly
            last_exception = exc
            if attempt == max_attempts - 1:
                raise
            if on_retry:
                on_retry(attempt, exc)
            delay = min(base_delay * (2**attempt), max_delay)
            time.sleep(delay)

    # Unreachable, but keeps type checkers happy.
    raise last_exception  # type: ignore[misc]


class ResearchEngine:
    """
    Wraps the OpenAI GPT-4o API to research a company's GCC opportunity profile.

    **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7**
    """

    def __init__(self, client: Optional[OpenAI] = None):
        """
        Args:
            client: Optional pre-built OpenAI client (for testing/dependency
                injection). If not provided, a client is lazily constructed
                on first use using the resolved API key (DB-stored value
                from the Settings UI, falling back to the OPENAI_API_KEY
                env var -- see src.utils.api_keys.get_api_key), so importing
                this module never requires a key to already be set.

                Note: when a client is injected, the key resolution below is
                bypassed entirely (the injected client owns its own key) --
                used by tests and any other caller that wants to manage the
                OpenAI client itself.
        """
        self._client = client
        self._config = None

    @property
    def config(self):
        if self._config is None:
            self._config = get_config().openai
        return self._config

    def _current_api_key(self) -> Optional[str]:
        """Resolve the OpenAI key fresh (DB-first, env-fallback) on every call."""
        return get_api_key(OPENAI_API_KEY)

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            api_key = self._current_api_key()
            if not api_key:
                raise ResearchNoKeyConfiguredError(
                    "No OpenAI API key is configured. Add one in Settings, "
                    "or set the OPENAI_API_KEY environment variable."
                )
            self._client = OpenAI(api_key=api_key)
        return self._client

    def _build_prompt(self, company_name: str, company_domain: Optional[str]) -> str:
        return RESEARCH_PROMPT_TEMPLATE.format(
            company_name=company_name,
            company_domain=company_domain or "unknown",
        )

    @staticmethod
    def _is_tool_unsupported_error(exc: Exception) -> bool:
        """
        Heuristic: did this failure happen because the configured OpenAI
        account/model doesn't support the `web_search_preview` tool (in
        which case we should gracefully fall back to a plain, non-grounded
        call), or is it a genuine key/quota failure that must keep
        propagating to the existing retry/backoff logic untouched?

        Deliberately conservative: only a 400-shaped error whose message
        hints at an unsupported tool/parameter is treated as a tool-support
        issue. Auth (401/403) and rate-limit (429) status codes are never
        swallowed here -- they must reach the normal retry/failure path.
        """
        status_code = getattr(exc, "status_code", None)
        if status_code in (401, 403, 429):
            return False
        message = str(exc).lower()
        hints = (
            "web_search",
            "tool",
            "not supported",
            "unsupported",
            "unknown parameter",
            "invalid value",
            "does not support",
        )
        if status_code == 400 and any(hint in message for hint in hints):
            return True
        return False

    def _call_openai(self, prompt: str) -> str:
        """
        Call OpenAI with live web search grounding via the Responses API, so
        research is actually based on current public information rather
        than only the model's training-data recall -- the prompt itself
        instructs "Research this company using web search".

        Falls back to a plain (non-grounded) chat completion if the
        search-enabled call fails for a reason that looks like the
        configured account/model doesn't support the web_search tool.
        Genuine key/quota failures (401/403/429-shaped) are left to
        propagate untouched to the existing retry logic in
        `research_company`.
        """
        try:
            response = self.client.responses.create(
                model=self.config.model,
                tools=[{"type": "web_search_preview", "search_context_size": "low"}],
                input=[
                    {"role": "system", "content": SYSTEM_INSTRUCTION},
                    {"role": "user", "content": prompt},
                ],
                max_output_tokens=self.config.max_tokens,
            )
            text = (getattr(response, "output_text", None) or "").strip()
            if text:
                return text
            logger.warning(
                "Web search response had empty output_text; falling back to non-grounded call."
            )
        except Exception as exc:  # noqa: BLE001 - heuristically classified below
            if not self._is_tool_unsupported_error(exc):
                raise
            logger.warning(
                f"Web search tool unavailable, falling back to non-grounded call: {exc}"
            )

        return self._call_openai_without_search(prompt)

    def _call_openai_without_search(self, prompt: str) -> str:
        """Plain (non-grounded) chat completion -- the original, reliable call path."""
        response = self.client.chat.completions.create(
            model=self.config.model,
            messages=[
                {"role": "system", "content": SYSTEM_INSTRUCTION},
                {"role": "user", "content": prompt},
            ],
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content or ""

    def _parse_and_validate(
        self, raw_content: str, company_name: str, company_domain: Optional[str]
    ) -> ResearchResult:
        """
        Parse the model's JSON response (has_gcc/fit/pain_points schema) and
        validate it, raising ResearchResponseError on any structural
        problem. Delegates to the shared `parse_research_response` so this
        engine and the Gemini engine can't drift apart on parsing behavior.

        **Validates: Requirements 5.3, 5.6**
        """
        try:
            return parse_research_response(raw_content, company_name, company_domain)
        except ResponseParsingError as exc:
            raise ResearchResponseError(str(exc)) from exc

    def research_company(
        self,
        company_name: str,
        company_domain: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> ResearchResult:
        """
        Research a single company's GCC opportunity profile via GPT-4o.

        Retries on any API failure (rate limits, connection errors, transient
        API errors) up to 3 times with exponential backoff per design.md.
        Malformed/invalid JSON responses are NOT retried automatically here
        since they typically indicate a prompting issue rather than a
        transient failure; callers should surface these for manual review
        per the design's error handling strategy.

        Args:
            company_name: Name of the company to research.
            company_domain: Optional company domain/website.
            session_id: Optional processing session id, for log correlation.

        Returns:
            A validated ResearchResult.

        Raises:
            ResearchNoKeyConfiguredError: If no OpenAI API key is configured.
            ResearchAPIError: If all retry attempts against the API are exhausted.
            ResearchResponseError: If the model's response is malformed/invalid.

        **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7**
        """
        # Fail fast: "no key configured" is a permanent configuration problem,
        # not a transient API failure, so it shouldn't burn through the
        # exponential-backoff retry budget (and its sleeps) before surfacing.
        # Skipped when a client was injected directly (tests/DI) since then
        # there's no key to resolve in the first place.
        if self._client is None and not self._current_api_key():
            raise ResearchNoKeyConfiguredError(
                "No OpenAI API key is configured. Add one in Settings, or "
                "set the OPENAI_API_KEY environment variable."
            )

        prompt = self._build_prompt(company_name, company_domain)

        def _attempt_retry_log(attempt: int, exc: Exception) -> None:
            log_event(
                logger,
                "WARNING",
                "research_api_retry",
                user_session=session_id,
                details={
                    "company_name": company_name,
                    "attempt": attempt + 1,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )

        start = time.perf_counter()
        try:
            raw_content = exponential_backoff_retry(
                lambda: self._call_openai(prompt),
                max_attempts=self.config.max_retries,
                base_delay=self.config.retry_delay,
                max_delay=self.config.max_retry_delay,
                on_retry=_attempt_retry_log,
            )
        except ResearchNoKeyConfiguredError:
            raise
        except (APIError, APIConnectionError, RateLimitError) as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            log_event(
                logger,
                "ERROR",
                "research_api_exhausted",
                user_session=session_id,
                duration_ms=duration_ms,
                details={"company_name": company_name, "error": str(exc)},
            )
            raise ResearchAPIError(
                f"OpenAI API call failed after {self.config.max_retries} attempts: {exc}"
            ) from exc
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            log_event(
                logger,
                "ERROR",
                "research_api_exhausted",
                user_session=session_id,
                duration_ms=duration_ms,
                details={"company_name": company_name, "error": str(exc)},
            )
            raise ResearchAPIError(
                f"OpenAI API call failed after retries: {exc}"
            ) from exc

        result = self._parse_and_validate(raw_content, company_name, company_domain)

        duration_ms = (time.perf_counter() - start) * 1000
        log_event(
            logger,
            "INFO",
            "research_completed",
            user_session=session_id,
            duration_ms=duration_ms,
            details={
                "company_name": company_name,
                "suitability_score": result.suitability_score,
                "gcc_presence": result.gcc_presence,
            },
        )
        return result


# Module-level singleton, constructed lazily on first attribute access so
# importing this module never requires OPENAI_API_KEY to be set yet.
_engine: Optional[ResearchEngine] = None


def get_research_engine() -> ResearchEngine:
    """Get the global ResearchEngine instance, constructing it on first use."""
    global _engine
    if _engine is None:
        _engine = ResearchEngine()
    return _engine
