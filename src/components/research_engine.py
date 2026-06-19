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

# Exact prompt template from design.md's API Interfaces section.
RESEARCH_PROMPT_TEMPLATE = """
Analyze the company '{company_name}' (domain: {company_domain}) for GCC opportunities in India.

Provide a JSON response with the following structure:
{{
    "gcc_presence": boolean,
    "gcc_location": "string or null",
    "suitability_score": integer (1-10),
    "business_pain_points": ["string", "string"],
    "expansion_indicators": ["string", "string"],
    "hiring_signals": ["string", "string"],
    "research_summary": "string"
}}

Research focus:
1. Does this company already have a GCC/development center in India?
2. Rate suitability for GCC establishment (1=poor, 10=excellent)
3. Identify business challenges that a GCC could solve
4. Look for signs of expansion or growth
5. Check for active hiring in tech/operations roles

Provide factual, research-based insights only.
"""

REQUIRED_FIELDS = (
    "gcc_presence",
    "gcc_location",
    "suitability_score",
    "business_pain_points",
    "expansion_indicators",
    "hiring_signals",
    "research_summary",
)


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

    def _call_openai(self, prompt: str) -> str:
        """Make a single OpenAI chat completion call and return the raw text content."""
        response = self.client.chat.completions.create(
            model=self.config.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a business research analyst specializing in Global "
                        "Capability Centers (GCCs) in India. Respond only with valid "
                        "JSON matching the exact schema requested, with no additional "
                        "commentary or markdown formatting."
                    ),
                },
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
        Parse the model's JSON response and validate it against the required
        schema, raising ResearchResponseError on any structural problem.

        **Validates: Requirements 5.3, 5.6**
        """
        try:
            data: Dict[str, Any] = json.loads(raw_content)
        except json.JSONDecodeError as exc:
            raise ResearchResponseError(f"Model response was not valid JSON: {exc}") from exc

        missing = [field for field in REQUIRED_FIELDS if field not in data]
        if missing:
            raise ResearchResponseError(f"Model response missing required fields: {missing}")

        try:
            score = int(data["suitability_score"])
        except (TypeError, ValueError) as exc:
            raise ResearchResponseError(
                f"suitability_score must be an integer, got: {data['suitability_score']!r}"
            ) from exc

        # Clamp rather than reject outright on minor model deviations (e.g. 0 or 11),
        # since the rest of the research is still valuable; log when this happens.
        if not 1 <= score <= 10:
            logger.warning(
                f"Model returned out-of-range suitability_score={score} for "
                f"'{company_name}'; clamping to [1, 10]."
            )
            score = max(1, min(10, score))

        def _as_str_list(value: Any) -> list:
            if value is None:
                return []
            if isinstance(value, list):
                return [str(v) for v in value]
            return [str(value)]

        try:
            return ResearchResult(
                company_name=company_name,
                company_domain=company_domain,
                gcc_presence=bool(data["gcc_presence"]),
                gcc_location=data.get("gcc_location"),
                suitability_score=score,
                business_pain_points=_as_str_list(data.get("business_pain_points")),
                expansion_indicators=_as_str_list(data.get("expansion_indicators")),
                hiring_signals=_as_str_list(data.get("hiring_signals")),
                research_summary=str(data.get("research_summary") or "").strip()
                or "No summary provided.",
                is_cached=False,
                created_at=datetime.now(timezone.utc),
            )
        except ValueError as exc:
            raise ResearchResponseError(f"Research result failed validation: {exc}") from exc

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
