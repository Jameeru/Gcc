"""
Gemini-powered research engine for the GCC Research Intelligence Platform.

Mirrors research_engine.py's interface and retry semantics (3 attempts,
base_delay=1.0s, max_delay=60.0s exponential backoff) so the rest of the
application (results_processor.py) can treat OpenAI and Gemini as
interchangeable providers behind the same `research_company(name, domain)
-> ResearchResult` contract.

Built on the actively-maintained `google-genai` SDK (the older
`google-generativeai` package was deprecated upstream as of its 0.8.x
release and explicitly tells callers to migrate, so this was the right
choice for new, production code rather than building against a sunset API).

Adds round-robin + failover across the user's two configured Gemini API
keys (per the Settings UI from task #20): each call starts from the next
key in rotation, and if a key fails with an auth/quota-shaped error, the
*same* attempt immediately tries the other key before counting against the
exponential-backoff retry budget -- so a single exhausted/invalid key
doesn't waste retries that a healthy second key could have served.

**Validates the same research-response-shape contract as Requirements 5.1-5.7
or research_engine.py's, applied to the Gemini provider.**
"""

from __future__ import annotations

import itertools
import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from ..models.entities import ResearchResult
from ..utils.api_keys import get_gemini_api_keys
from ..utils.config import get_config
from ..utils.logging import get_logger, log_event
from .research_engine import (
    REQUIRED_FIELDS,
    RESEARCH_PROMPT_TEMPLATE,
    ResponseParsingError,
    exponential_backoff_retry,
    parse_research_response,
)

logger = get_logger("gemini_engine")

DEFAULT_MODEL = "gemini-2.0-flash"

SYSTEM_INSTRUCTION = (
    "You are a business research analyst specializing in Global Capability "
    "Centers (GCCs) in India. Respond only with valid JSON matching the "
    "exact schema requested, with no additional commentary or markdown "
    "formatting."
)


class GeminiEngineError(Exception):
    """Base exception for Gemini research engine failures."""


class GeminiNoKeysConfiguredError(GeminiEngineError):
    """Raised when no Gemini API key is configured (neither DB nor env)."""


class GeminiResponseError(GeminiEngineError):
    """Raised when Gemini's response is missing fields or malformed."""


class GeminiAPIError(GeminiEngineError):
    """Raised when all retry attempts (across all configured keys) are exhausted."""


def _is_key_level_failure(exc: Exception) -> bool:
    """
    Heuristic for "this specific key is bad" (invalid/unauthorized/quota
    exhausted) vs. a generic transient failure -- key-level failures are
    worth immediately retrying on the *other* configured key, since a
    different key may simply not have the same problem.
    """
    status_code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if status_code in (401, 403, 429):
        return True
    message = str(exc).lower()
    return any(
        token in message
        for token in ("api key", "permission", "unauthorized", "quota", "rate limit")
    )


class GeminiEngine:
    """
    Wraps the Gemini API (via google-genai) to research a company's GCC
    opportunity profile, with round-robin + failover across up to 2
    configured API keys.

    **Mirrors ResearchEngine's public contract in research_engine.py.**
    """

    def __init__(self, api_keys: Optional[List[str]] = None, model: Optional[str] = None):
        """
        Args:
            api_keys: Optional explicit list of Gemini API keys (for
                testing/dependency injection). If not provided, resolved
                live from the DB-first/env-fallback layer in
                src.utils.api_keys on each call, so a key rotated through
                the Settings UI takes effect without an app restart.
            model: Optional Gemini model name override.
        """
        self._explicit_keys = api_keys
        self._model_override = model
        self._clients_by_key: Dict[str, genai.Client] = {}
        self._rotation_lock = threading.Lock()
        self._rotation_counter = itertools.count()

    @property
    def model(self) -> str:
        if self._model_override:
            return self._model_override
        return os.getenv("GEMINI_MODEL", DEFAULT_MODEL)

    def _current_keys(self) -> List[str]:
        if self._explicit_keys is not None:
            return [k for k in self._explicit_keys if k]
        return get_gemini_api_keys()

    def _client_for_key(self, api_key: str) -> genai.Client:
        client = self._clients_by_key.get(api_key)
        if client is None:
            client = genai.Client(api_key=api_key)
            self._clients_by_key[api_key] = client
        return client

    def _ordered_keys_for_this_call(self) -> List[str]:
        """
        Return the currently-configured keys, rotated so consecutive calls
        start from a different key (simple round-robin) -- this spreads
        load/quota usage across both keys rather than always preferring key 1.
        """
        keys = self._current_keys()
        if not keys:
            return []
        if len(keys) == 1:
            return keys
        with self._rotation_lock:
            start = next(self._rotation_counter) % len(keys)
        return keys[start:] + keys[:start]

    def _build_prompt(self, company_name: str, company_domain: Optional[str]) -> str:
        return RESEARCH_PROMPT_TEMPLATE.format(
            company_name=company_name,
            company_domain=company_domain or "unknown",
        )

    def _call_gemini_with_key(self, api_key: str, prompt: str) -> str:
        """
        Make a single Gemini generate_content call with a specific key,
        using live Google Search grounding so research reflects current
        public information -- the prompt itself instructs "Research this
        company using web search".

        Gemini's API does not support combining the `google_search`
        grounding tool with `response_mime_type="application/json"` (it
        raises "Function calling with a response mime type:
        'application/json' is unsupported"), so the grounded call below
        omits response_mime_type entirely and relies on the prompt's own
        "Respond ONLY with valid JSON" instruction instead.

        If the grounded call fails for a reason that is NOT a key-level
        failure (those must keep propagating untouched to `_call_gemini`'s
        existing key-rotation/failover loop), fall back once to a
        non-grounded call on this same key, which restores
        response_mime_type for maximum JSON reliability.
        """
        try:
            text = self._call_gemini_grounded(api_key, prompt)
            if text:
                return text
            logger.warning(
                "Gemini grounded response had no text; falling back to non-grounded call."
            )
        except Exception as exc:  # noqa: BLE001
            if _is_key_level_failure(exc):
                raise
            logger.warning(
                f"Gemini search grounding failed (non-key-level), falling back to "
                f"non-grounded call: {exc}"
            )

        return self._call_gemini_no_search(api_key, prompt)

    def _call_gemini_grounded(self, api_key: str, prompt: str) -> str:
        """Gemini call with Google Search grounding enabled (no JSON response_mime_type)."""
        client = self._client_for_key(api_key)
        response = client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.1,
                max_output_tokens=2000,
                tools=[genai_types.Tool(google_search=genai_types.GoogleSearch())],
            ),
        )
        return (response.text or "").strip()

    def _call_gemini_no_search(self, api_key: str, prompt: str) -> str:
        """Plain (non-grounded) Gemini call -- the original, reliable call path."""
        client = self._client_for_key(api_key)
        response = client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.1,
                max_output_tokens=2000,
                response_mime_type="application/json",
            ),
        )
        return response.text or ""

    def _call_gemini(self, prompt: str, session_id: Optional[str]) -> str:
        """
        Try the currently-configured Gemini keys in rotation order for a
        single logical attempt. A key-level failure (auth/quota-shaped)
        immediately falls through to the next key within this same
        attempt; any other exception propagates to the caller's
        exponential-backoff retry loop.
        """
        keys = self._ordered_keys_for_this_call()
        if not keys:
            raise GeminiNoKeysConfiguredError(
                "No Gemini API key is configured. Add one in Settings, or "
                "set GEMINI_API_KEY_1 / GEMINI_API_KEY_2."
            )

        last_exc: Optional[Exception] = None
        for index, key in enumerate(keys):
            try:
                return self._call_gemini_with_key(key, prompt)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                is_last_key = index == len(keys) - 1
                if is_last_key or not _is_key_level_failure(exc):
                    raise
                log_event(
                    logger,
                    "WARNING",
                    "gemini_key_failover",
                    user_session=session_id,
                    details={
                        "key_index": index,
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                    },
                )
        raise last_exc  # type: ignore[misc]

    def _parse_and_validate(
        self, raw_content: str, company_name: str, company_domain: Optional[str]
    ) -> ResearchResult:
        """
        Parse Gemini's JSON response (has_gcc/fit/pain_points schema).
        Delegates to the shared `parse_research_response` so this engine and
        ResearchEngine (OpenAI) can't drift apart on parsing behavior.
        """
        try:
            return parse_research_response(raw_content, company_name, company_domain)
        except ResponseParsingError as exc:
            raise GeminiResponseError(str(exc)) from exc

    def research_company(
        self,
        company_name: str,
        company_domain: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> ResearchResult:
        """
        Research a single company's GCC opportunity profile via Gemini.

        Same retry contract as ResearchEngine.research_company: up to 3
        attempts with exponential backoff on transient failures. Within
        each attempt, a key-level failure (bad/exhausted key) is retried
        immediately against the other configured key before counting
        against that attempt budget.

        Args:
            company_name: Name of the company to research.
            company_domain: Optional company domain/website.
            session_id: Optional processing session id, for log correlation.

        Returns:
            A validated ResearchResult.

        Raises:
            GeminiNoKeysConfiguredError: If no Gemini API key is configured.
            GeminiAPIError: If all retry attempts are exhausted.
            GeminiResponseError: If Gemini's response is malformed/invalid.
        """
        # Fail fast: "no key configured" is a permanent configuration problem,
        # not a transient API failure, so it shouldn't burn through the
        # exponential-backoff retry budget (and its sleeps) before surfacing.
        if not self._current_keys():
            raise GeminiNoKeysConfiguredError(
                "No Gemini API key is configured. Add one in Settings, or "
                "set GEMINI_API_KEY_1 / GEMINI_API_KEY_2."
            )

        prompt = self._build_prompt(company_name, company_domain)

        def _attempt_retry_log(attempt: int, exc: Exception) -> None:
            log_event(
                logger,
                "WARNING",
                "gemini_api_retry",
                user_session=session_id,
                details={
                    "company_name": company_name,
                    "attempt": attempt + 1,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )

        openai_config = get_config().openai  # reuse the same retry tuning knobs
        start = time.perf_counter()
        try:
            raw_content = exponential_backoff_retry(
                lambda: self._call_gemini(prompt, session_id),
                max_attempts=openai_config.max_retries,
                base_delay=openai_config.retry_delay,
                max_delay=openai_config.max_retry_delay,
                on_retry=_attempt_retry_log,
            )
        except GeminiNoKeysConfiguredError:
            raise
        except (genai_errors.APIError, genai_errors.ClientError, genai_errors.ServerError) as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            log_event(
                logger,
                "ERROR",
                "gemini_api_exhausted",
                user_session=session_id,
                duration_ms=duration_ms,
                details={"company_name": company_name, "error": str(exc)},
            )
            raise GeminiAPIError(
                f"Gemini API call failed after {openai_config.max_retries} attempts: {exc}"
            ) from exc
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            log_event(
                logger,
                "ERROR",
                "gemini_api_exhausted",
                user_session=session_id,
                duration_ms=duration_ms,
                details={"company_name": company_name, "error": str(exc)},
            )
            raise GeminiAPIError(
                f"Gemini API call failed after retries: {exc}"
            ) from exc

        result = self._parse_and_validate(raw_content, company_name, company_domain)

        duration_ms = (time.perf_counter() - start) * 1000
        log_event(
            logger,
            "INFO",
            "gemini_research_completed",
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
# importing this module never requires a Gemini API key to be set yet.
# Unlike research_engine.py's _engine, this one does NOT cache resolved API
# keys (the GeminiEngine instance itself re-resolves keys via
# src.utils.api_keys on every call), so a key rotated through the Settings
# UI is picked up by the very next research call.
_engine: Optional[GeminiEngine] = None


def get_gemini_engine() -> GeminiEngine:
    """Get the global GeminiEngine instance, constructing it on first use."""
    global _engine
    if _engine is None:
        _engine = GeminiEngine()
    return _engine
