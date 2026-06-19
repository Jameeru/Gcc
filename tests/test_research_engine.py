"""
Unit tests and property-based tests for the OpenAI research engine.

Covers the synchronous exponential backoff retry helper, response
parsing/validation (required fields, score clamping, list coercion),
end-to-end research_company behavior against a mocked OpenAI client,
and property-based testing for research response validation.

**Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 10.1**
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

import json
import string
from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock, patch
from typing import Any, Dict, List, Optional, Union

import httpx
import pytest
from hypothesis import given, strategies as st, assume, settings, HealthCheck
from openai import APIConnectionError, RateLimitError

from src.components.research_engine import (
    REQUIRED_FIELDS,
    VALID_FIT,
    VALID_HAS_GCC,
    ResearchAPIError,
    ResearchEngine,
    ResearchEngineError,
    ResearchNoKeyConfiguredError,
    ResearchResponseError,
    ResponseParsingError,
    exponential_backoff_retry,
    get_research_engine,
    parse_research_response,
)
from src.models.entities import ResearchResult


def _valid_payload(**overrides):
    payload = {
        "has_gcc": "Yes",
        "fit": "Strong",
        "pain_points": "High operational costs and talent shortages noted.",
    }
    payload.update(overrides)
    return payload


def _make_completion(content: str):
    """Build a minimal object mimicking the OpenAI chat completion response shape."""
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    completion = MagicMock()
    completion.choices = [choice]
    return completion


def _make_responses_api_result(text: str):
    """Build a minimal object mimicking the OpenAI Responses API result shape
    (response.output_text), used by ResearchEngine._call_openai's primary
    (web-search-grounded) call path."""
    response = MagicMock()
    response.output_text = text
    return response


def _make_rate_limit_error():
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(429, request=request)
    return RateLimitError("Rate limited", response=response, body=None)


def _make_connection_error():
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    return APIConnectionError(request=request)


class TestExponentialBackoffRetry:
    def test_succeeds_on_first_attempt_without_sleeping(self):
        func = Mock(return_value="ok")
        with patch("time.sleep") as mock_sleep:
            result = exponential_backoff_retry(func, max_attempts=3)
        assert result == "ok"
        func.assert_called_once()
        mock_sleep.assert_not_called()

    def test_succeeds_after_transient_failures(self):
        func = Mock(side_effect=[ValueError("transient"), ValueError("transient"), "ok"])
        with patch("time.sleep") as mock_sleep:
            result = exponential_backoff_retry(func, max_attempts=3, base_delay=1.0)
        assert result == "ok"
        assert func.call_count == 3
        assert mock_sleep.call_count == 2

    def test_exhausts_all_attempts_and_raises_last_exception(self):
        func = Mock(side_effect=ValueError("always fails"))
        with patch("time.sleep"):
            with pytest.raises(ValueError, match="always fails"):
                exponential_backoff_retry(func, max_attempts=3)
        assert func.call_count == 3

    def test_delay_doubles_and_is_capped_at_max_delay(self):
        func = Mock(side_effect=[ValueError("x"), ValueError("x"), ValueError("x"), "ok"])
        with patch("time.sleep") as mock_sleep:
            exponential_backoff_retry(func, max_attempts=4, base_delay=10.0, max_delay=15.0)
        # Delays: 10.0, 20.0 (capped to 15.0), 30.0 (capped to 15.0)
        delays = [call.args[0] for call in mock_sleep.call_args_list]
        assert delays == [10.0, 15.0, 15.0]

    def test_on_retry_callback_invoked_per_failed_attempt(self):
        func = Mock(side_effect=[ValueError("first"), "ok"])
        on_retry = Mock()
        with patch("time.sleep"):
            exponential_backoff_retry(func, max_attempts=3, on_retry=on_retry)
        on_retry.assert_called_once()
        attempt_idx, exc = on_retry.call_args.args
        assert attempt_idx == 0
        assert isinstance(exc, ValueError)


class TestParseAndValidate:
    """
    Covers ResearchEngine._parse_and_validate, which now just delegates to
    the shared parse_research_response (see TestParseResearchResponse below)
    and re-wraps ResponseParsingError as ResearchResponseError. Kept here
    (rather than folded entirely into the shared-function tests) so the
    wrapping behavior itself stays covered.
    """

    def setup_method(self):
        self.engine = ResearchEngine(client=Mock())

    def test_valid_response_parses_correctly(self):
        result = self.engine._parse_and_validate(
            json.dumps(_valid_payload()), "Microsoft", "microsoft.com"
        )
        assert isinstance(result, ResearchResult)
        assert result.company_name == "Microsoft"
        assert result.gcc_status == "Yes"
        assert result.fit_rating == "Strong"
        assert result.gcc_presence is True
        assert result.suitability_score == 9

    def test_invalid_json_raises_response_error(self):
        with pytest.raises(ResearchResponseError, match="not valid JSON"):
            self.engine._parse_and_validate("not json {{{", "Acme", None)

    def test_missing_required_field_raises_response_error(self):
        payload = _valid_payload()
        del payload["pain_points"]
        with pytest.raises(ResearchResponseError, match="missing required fields"):
            self.engine._parse_and_validate(json.dumps(payload), "Acme", None)

    @pytest.mark.parametrize("field", REQUIRED_FIELDS)
    def test_each_required_field_is_actually_required(self, field):
        payload = _valid_payload()
        del payload[field]
        with pytest.raises(ResearchResponseError):
            self.engine._parse_and_validate(json.dumps(payload), "Acme", None)


class TestParseResearchResponse:
    """
    Unit tests for the shared parse_research_response() function in
    research_engine.py, which both ResearchEngine and GeminiEngine delegate
    to for the has_gcc/fit/pain_points response schema.
    """

    def test_valid_response_derives_legacy_fields_correctly(self):
        result = parse_research_response(
            json.dumps(_valid_payload()), "Microsoft", "microsoft.com"
        )
        assert isinstance(result, ResearchResult)
        assert result.company_name == "Microsoft"
        assert result.company_domain == "microsoft.com"
        assert result.gcc_status == "Yes"
        assert result.fit_rating == "Strong"
        assert result.pain_points_summary == "High operational costs and talent shortages noted."
        # Derived legacy fields.
        assert result.gcc_presence is True
        assert result.suitability_score == 9
        assert result.business_pain_points == ["High operational costs and talent shortages noted."]
        assert result.research_summary == "High operational costs and talent shortages noted."
        assert result.expansion_indicators == []
        assert result.hiring_signals == []
        assert result.is_cached is False
        assert isinstance(result.created_at, datetime)

    def test_invalid_json_raises_response_parsing_error(self):
        with pytest.raises(ResponseParsingError, match="not valid JSON"):
            parse_research_response("not json {{{", "Acme", None)

    def test_empty_string_raises_response_parsing_error(self):
        with pytest.raises(ResponseParsingError):
            parse_research_response("", "Acme", None)

    def test_non_object_json_raises_response_parsing_error(self):
        with pytest.raises(ResponseParsingError, match="must be a JSON object"):
            parse_research_response("[1, 2, 3]", "Acme", None)

    @pytest.mark.parametrize("field", REQUIRED_FIELDS)
    def test_each_required_field_is_actually_required(self, field):
        payload = _valid_payload()
        del payload[field]
        with pytest.raises(ResponseParsingError, match="missing required fields"):
            parse_research_response(json.dumps(payload), "Acme", None)

    @pytest.mark.parametrize("has_gcc_value,expected_presence", [("Yes", True), ("No", False), ("Uncertain", False)])
    def test_has_gcc_values_map_to_gcc_presence(self, has_gcc_value, expected_presence):
        result = parse_research_response(
            json.dumps(_valid_payload(has_gcc=has_gcc_value)), "Acme", None
        )
        assert result.gcc_status == has_gcc_value
        assert result.gcc_presence is expected_presence

    @pytest.mark.parametrize("fit_value,expected_score", [("Strong", 9), ("Possible", 5), ("Unlikely", 2)])
    def test_fit_values_map_to_suitability_score(self, fit_value, expected_score):
        result = parse_research_response(
            json.dumps(_valid_payload(fit=fit_value)), "Acme", None
        )
        assert result.fit_rating == fit_value
        assert result.suitability_score == expected_score

    def test_invalid_has_gcc_value_is_normalized_not_rejected(self):
        """Invalid enum values are normalized to a default rather than
        raising -- see _normalize_enum in research_engine.py."""
        result = parse_research_response(
            json.dumps(_valid_payload(has_gcc="Maybe")), "Acme", None
        )
        assert result.gcc_status == "Uncertain"

    def test_invalid_fit_value_is_normalized_not_rejected(self):
        result = parse_research_response(
            json.dumps(_valid_payload(fit="Excellent")), "Acme", None
        )
        assert result.fit_rating == "Possible"

    def test_has_gcc_value_normalization_is_case_insensitive(self):
        result = parse_research_response(
            json.dumps(_valid_payload(has_gcc="yes")), "Acme", None
        )
        assert result.gcc_status == "Yes"

    def test_no_specific_signals_found_pain_points_yields_empty_list(self):
        result = parse_research_response(
            json.dumps(_valid_payload(pain_points="no specific signals found")), "Acme", None
        )
        assert result.business_pain_points == []
        assert result.pain_points_summary == "no specific signals found"

    def test_no_specific_signals_found_is_case_insensitive(self):
        result = parse_research_response(
            json.dumps(_valid_payload(pain_points="No Specific Signals Found")), "Acme", None
        )
        assert result.business_pain_points == []

    def test_blank_pain_points_defaults_to_no_specific_signals_found(self):
        result = parse_research_response(
            json.dumps(_valid_payload(pain_points="   ")), "Acme", None
        )
        assert result.pain_points_summary == "no specific signals found"
        assert result.business_pain_points == []

    def test_markdown_fenced_json_is_tolerated(self):
        fenced = "```json\n" + json.dumps(_valid_payload()) + "\n```"
        result = parse_research_response(fenced, "Acme", None)
        assert result.gcc_status == "Yes"

    def test_json_with_preamble_text_is_tolerated(self):
        wrapped = "Here is the research result:\n" + json.dumps(_valid_payload()) + "\nThanks."
        result = parse_research_response(wrapped, "Acme", None)
        assert result.gcc_status == "Yes"


class TestResearchCompany:
    """
    research_company's primary call path is now _call_openai, which calls
    self.client.responses.create(...) (the web-search-grounded Responses
    API) and reads response.output_text -- NOT the old
    chat.completions.create()/choices[0].message.content path. These tests
    mock responses.create accordingly; the fallback-to-chat-completions path
    is covered separately in TestOpenAISearchFallback.
    """

    def test_success_on_first_attempt(self):
        mock_client = Mock()
        mock_client.responses.create.return_value = _make_responses_api_result(
            json.dumps(_valid_payload())
        )
        engine = ResearchEngine(client=mock_client)

        result = engine.research_company("Microsoft", "microsoft.com")

        assert result.company_name == "Microsoft"
        assert mock_client.responses.create.call_count == 1
        mock_client.chat.completions.create.assert_not_called()

    def test_retries_on_rate_limit_then_succeeds(self):
        mock_client = Mock()
        mock_client.responses.create.side_effect = [
            _make_rate_limit_error(),
            _make_responses_api_result(json.dumps(_valid_payload())),
        ]
        engine = ResearchEngine(client=mock_client)
        engine._config = Mock(max_retries=3, retry_delay=1.0, max_retry_delay=60.0)

        with patch("time.sleep"):
            result = engine.research_company("Acme", "acme.com")

        assert result.company_name == "Acme"
        assert mock_client.responses.create.call_count == 2

    def test_exhausted_retries_raise_research_api_error(self):
        mock_client = Mock()
        mock_client.responses.create.side_effect = _make_connection_error()
        engine = ResearchEngine(client=mock_client)
        engine._config = Mock(max_retries=3, retry_delay=1.0, max_retry_delay=60.0)

        with patch("time.sleep"):
            with pytest.raises(ResearchAPIError):
                engine.research_company("Acme", "acme.com")

        assert mock_client.responses.create.call_count == 3

    def test_malformed_response_not_retried(self):
        """
        Malformed JSON indicates a prompting/schema issue, not a transient
        failure, so research_company should surface ResearchResponseError
        directly without burning through retry attempts.
        """
        mock_client = Mock()
        mock_client.responses.create.return_value = _make_responses_api_result("not valid json")
        engine = ResearchEngine(client=mock_client)
        engine._config = Mock(max_retries=3, retry_delay=1.0, max_retry_delay=60.0)

        with pytest.raises(ResearchResponseError):
            engine.research_company("Acme", "acme.com")

        # Only one call -- the bad JSON came back successfully from the API,
        # so the retry loop (which only catches API-level failures) never re-invoked it.
        assert mock_client.responses.create.call_count == 1

    def test_research_engine_error_is_common_base_class(self):
        assert issubclass(ResearchAPIError, ResearchEngineError)
        assert issubclass(ResearchResponseError, ResearchEngineError)


class TestOpenAISearchFallback:
    """
    Covers ResearchEngine._call_openai's fallback to the plain (non-grounded)
    chat-completions path: triggered when the web_search_preview tool isn't
    supported (heuristically detected by _is_tool_unsupported_error), or
    when response.output_text comes back empty/falsy.
    """

    def test_falls_back_when_tool_unsupported_error_is_raised(self):
        mock_client = Mock()
        unsupported_exc = Exception("Unknown parameter: 'tools[0].type' (does not support this tool)")
        unsupported_exc.status_code = 400
        mock_client.responses.create.side_effect = unsupported_exc
        mock_client.chat.completions.create.return_value = _make_completion(
            json.dumps(_valid_payload())
        )
        engine = ResearchEngine(client=mock_client)

        result = engine.research_company("Acme", "acme.com")

        assert result.company_name == "Acme"
        mock_client.responses.create.assert_called_once()
        mock_client.chat.completions.create.assert_called_once()

    def test_falls_back_when_output_text_is_empty(self):
        mock_client = Mock()
        mock_client.responses.create.return_value = _make_responses_api_result("")
        mock_client.chat.completions.create.return_value = _make_completion(
            json.dumps(_valid_payload())
        )
        engine = ResearchEngine(client=mock_client)

        result = engine.research_company("Acme", "acme.com")

        assert result.company_name == "Acme"
        mock_client.chat.completions.create.assert_called_once()

    def test_does_not_fall_back_on_auth_error(self):
        """401/403/429-shaped errors must keep propagating to the existing
        retry/failure path rather than being swallowed as a tool-support issue."""
        mock_client = Mock()
        auth_exc = Exception("Invalid API key")
        auth_exc.status_code = 401
        mock_client.responses.create.side_effect = auth_exc
        engine = ResearchEngine(client=mock_client)
        engine._config = Mock(max_retries=1, retry_delay=1.0, max_retry_delay=60.0)

        with pytest.raises(ResearchAPIError):
            engine.research_company("Acme", "acme.com")

        mock_client.chat.completions.create.assert_not_called()

    @pytest.mark.parametrize(
        "exc,expected",
        [
            (Exception("web_search not supported by this model"), True),
            (Exception("unknown parameter: tools"), True),
            (Exception("does not support tool calling"), True),
            (Exception("connection reset"), False),
        ],
    )
    def test_is_tool_unsupported_error_message_heuristics(self, exc, expected):
        exc.status_code = 400
        assert ResearchEngine._is_tool_unsupported_error(exc) is expected

    @pytest.mark.parametrize("status_code", [401, 403, 429])
    def test_is_tool_unsupported_error_never_true_for_auth_or_rate_limit(self, status_code):
        exc = Exception("web_search tool not supported")
        exc.status_code = status_code
        assert ResearchEngine._is_tool_unsupported_error(exc) is False


class TestNoKeyConfiguredFailsFast:
    """
    Covers the OpenAI-side fix for the gap found while wiring the dual
    provider Settings UI: previously the OpenAI client's key came straight
    from the OPENAI_API_KEY env var (via get_config().openai.api_key),
    completely bypassing the DB-first resolution layer the Settings UI
    writes to -- so a key saved through the UI was silently never used.
    Now it's resolved via get_api_key(OPENAI_API_KEY), and a missing key
    fails fast rather than burning through the retry budget.
    """

    def test_raises_immediately_without_retry_delay_when_unconfigured(self):
        import time

        with patch(
            "src.components.research_engine.get_api_key", return_value=None
        ):
            engine = ResearchEngine()
            start = time.perf_counter()
            with pytest.raises(ResearchNoKeyConfiguredError):
                engine.research_company("Acme", "acme.com")
            elapsed = time.perf_counter() - start

        assert elapsed < 0.5

    def test_db_resolved_key_is_used_to_construct_client(self):
        engine = ResearchEngine()
        with patch(
            "src.components.research_engine.get_api_key",
            return_value="sk-from-db",
        ):
            with patch("src.components.research_engine.OpenAI") as mock_openai_cls:
                _ = engine.client

        mock_openai_cls.assert_called_once_with(api_key="sk-from-db")

    def test_no_key_configured_error_is_a_research_engine_error(self):
        assert issubclass(ResearchNoKeyConfiguredError, ResearchEngineError)

    def test_injected_client_bypasses_key_resolution_entirely(self):
        # When a client is injected (tests/DI), research_company must not
        # require any key to be configured at all.
        mock_client = Mock()
        mock_client.responses.create.return_value = _make_responses_api_result(
            json.dumps(_valid_payload())
        )
        engine = ResearchEngine(client=mock_client)

        with patch(
            "src.components.research_engine.get_api_key", return_value=None
        ):
            result = engine.research_company("Acme", "acme.com")

        assert result.company_name == "Acme"


class TestLazySingleton:
    def test_get_research_engine_returns_same_instance(self):
        engine1 = get_research_engine()
        engine2 = get_research_engine()
        assert engine1 is engine2

    def test_importing_module_does_not_require_api_key(self):
        # If this test file imported successfully and ResearchEngine() can be
        # constructed without an OPENAI_API_KEY in the environment, the lazy
        # client/config properties are doing their job.
        engine = ResearchEngine()
        assert engine._client is None
        assert engine._config is None


# Hypothesis strategies for generating test data
valid_company_chars = string.ascii_letters + string.digits + " .,'-&()[]"
valid_domain_chars = string.ascii_letters + string.digits + ".-"

# Strategy for generating valid company names
@st.composite
def company_name_strategy(draw):
    """Generate realistic company names for testing."""
    name = draw(st.text(alphabet=valid_company_chars, min_size=1, max_size=100))
    assume(name.strip())  # Must not be empty after stripping
    return name.strip()

# Strategy for generating valid domain names
@st.composite
def domain_strategy(draw):
    """Generate realistic domain names for testing."""
    # Generate domain label (before the TLD)
    domain_label = draw(st.text(alphabet=string.ascii_letters + string.digits + "-", min_size=1, max_size=50))
    assume(not domain_label.startswith('-') and not domain_label.endswith('-'))
    
    # Generate TLD
    tld = draw(st.sampled_from(['com', 'org', 'net', 'edu', 'gov', 'co.uk', 'io', 'ai', 'us']))
    
    return f"{domain_label}.{tld}".lower()

# Strategy for generating valid research response JSON data (new
# has_gcc/fit/pain_points tri-state schema).
@st.composite
def valid_research_response_strategy(draw):
    """Generate valid research response data that should pass validation."""
    return {
        "has_gcc": draw(st.sampled_from(VALID_HAS_GCC)),
        "fit": draw(st.sampled_from(VALID_FIT)),
        "pain_points": draw(st.text(alphabet=valid_company_chars, min_size=1, max_size=1000)),
    }


class TestResearchResponseValidationProperties:
    """
    Property-based tests for research response validation against the new
    has_gcc/fit/pain_points tri-state schema.

    **Property 9: Research Response Validation**
    *For any* research operation that completes successfully, the returned
    result shall derive from valid JSON containing all required fields,
    with a suitability_score (derived from `fit`) between 1-10.

    **Validates: Requirements 5.3, 5.6**
    """

    def setup_method(self):
        """Set up test fixtures."""
        self.engine = ResearchEngine(client=Mock())

    @given(
        company_name=company_name_strategy(),
        domain=st.one_of(st.none(), domain_strategy()),
        response_data=valid_research_response_strategy()
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_property_9_valid_research_responses_pass_validation(
        self, company_name: str, domain: Optional[str], response_data: Dict[str, Any]
    ):
        """
        **Property 9: Research Response Validation**

        For any valid research response JSON containing all required fields
        (has_gcc/fit/pain_points), validation should succeed and return a
        proper ResearchResult with both the new tri-state fields and the
        derived legacy fields populated correctly.

        **Validates: Requirements 5.3, 5.6**
        """
        json_response = json.dumps(response_data)

        result = self.engine._parse_and_validate(json_response, company_name, domain)

        assert isinstance(result, ResearchResult)
        assert result.company_name == company_name
        assert result.company_domain == domain
        assert result.gcc_status == response_data["has_gcc"]
        assert result.fit_rating == response_data["fit"]
        assert result.gcc_presence == (response_data["has_gcc"] == "Yes")
        assert 1 <= result.suitability_score <= 10
        assert isinstance(result.business_pain_points, list)
        assert isinstance(result.expansion_indicators, list)
        assert isinstance(result.hiring_signals, list)
        assert isinstance(result.research_summary, str)
        assert result.research_summary.strip()  # Must not be empty
        assert result.is_cached is False
        assert isinstance(result.created_at, datetime)

    @given(
        company_name=company_name_strategy(),
        domain=st.one_of(st.none(), domain_strategy()),
        missing_field=st.sampled_from(REQUIRED_FIELDS)
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_property_9_missing_required_fields_fail_validation(
        self, company_name: str, domain: Optional[str], missing_field: str
    ):
        """
        **Property 9: Research Response Validation - Missing Fields**

        For any research response JSON missing required fields,
        the validation should fail with ResearchResponseError.

        **Validates: Requirements 5.3, 5.6**
        """
        response_data = _valid_payload()
        del response_data[missing_field]
        json_response = json.dumps(response_data)

        with pytest.raises(ResearchResponseError, match="missing required fields"):
            self.engine._parse_and_validate(json_response, company_name, domain)

    @given(
        company_name=company_name_strategy(),
        domain=st.one_of(st.none(), domain_strategy()),
        invalid_has_gcc=st.text().filter(lambda x: x.strip().lower() not in {v.lower() for v in VALID_HAS_GCC}),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_property_9_invalid_has_gcc_values_are_normalized_to_uncertain(
        self, company_name: str, domain: Optional[str], invalid_has_gcc: str
    ):
        """
        **Property 9: Research Response Validation - Enum Normalization**

        For any has_gcc value that doesn't match the valid enum
        (case-insensitively), the engine should normalize it to "Uncertain"
        rather than raising -- see _normalize_enum in research_engine.py.

        **Validates: Requirements 5.3, 5.6**
        """
        response_data = _valid_payload(has_gcc=invalid_has_gcc)
        json_response = json.dumps(response_data)

        result = self.engine._parse_and_validate(json_response, company_name, domain)
        assert result.gcc_status == "Uncertain"
        assert result.gcc_presence is False

    @given(
        company_name=company_name_strategy(),
        domain=st.one_of(st.none(), domain_strategy()),
        fit_value=st.sampled_from(VALID_FIT),
    )
    @settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_property_9_fit_values_always_map_to_in_range_score(
        self, company_name: str, domain: Optional[str], fit_value: str
    ):
        """
        **Property 9: Research Response Validation - Score Derivation**

        For any valid `fit` value, the derived suitability_score must
        always land in the valid 1-10 range.

        **Validates: Requirements 5.3, 5.6**
        """
        response_data = _valid_payload(fit=fit_value)
        json_response = json.dumps(response_data)

        result = self.engine._parse_and_validate(json_response, company_name, domain)
        assert 1 <= result.suitability_score <= 10
        assert result.fit_rating == fit_value

    def test_property_9_malformed_json_fails_validation_simple(self):
        """
        **Property 9: Research Response Validation - JSON Format**

        Test specific cases of malformed JSON that should fail validation.

        **Validates: Requirements 5.3, 5.6**
        """
        malformed_responses = [
            "not json at all",
            '{"incomplete": json',
            '{has_gcc: true}',  # unquoted keys
            '',  # empty string
        ]

        for malformed_json in malformed_responses:
            with pytest.raises(ResearchResponseError):
                self.engine._parse_and_validate(malformed_json, "Test Company", "test.com")

        # Test valid JSON that's not an object - these should also fail but differently
        non_object_json = [
            'null',
            '[]',
            '"string"',
            '42'
        ]

        for non_object_json_str in non_object_json:
            with pytest.raises((ResearchResponseError, TypeError)):
                self.engine._parse_and_validate(non_object_json_str, "Test Company", "test.com")

    @given(
        company_name=company_name_strategy(),
        domain=st.one_of(st.none(), domain_strategy())
    )
    @settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_property_9_malformed_json_fails_validation(
        self, company_name: str, domain: Optional[str]
    ):
        """
        **Property 9: Research Response Validation - JSON Format**

        For any malformed JSON response, validation should fail
        with ResearchResponseError indicating JSON parsing failure.

        **Validates: Requirements 5.3, 5.6**
        """
        # Test with obviously non-JSON content
        with pytest.raises(ResearchResponseError):
            self.engine._parse_and_validate("definitely not json", company_name, domain)

    @given(
        company_name=company_name_strategy(),
        domain=st.one_of(st.none(), domain_strategy()),
        pain_points_value=st.one_of(
            st.text(min_size=1, max_size=500),
            st.just("no specific signals found"),
            st.just("No Specific Signals Found"),
        ),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_property_9_pain_points_coercion_behavior(
        self, company_name: str, domain: Optional[str], pain_points_value: str
    ):
        """
        **Property 9: Research Response Validation - Pain Points Handling**

        For any pain_points string, business_pain_points should be derived
        as [] when the text is exactly "no specific signals found"
        (case-insensitively), and a single-item list otherwise.

        **Validates: Requirements 5.3, 5.6**
        """
        response_data = _valid_payload(pain_points=pain_points_value)
        json_response = json.dumps(response_data)

        result = self.engine._parse_and_validate(json_response, company_name, domain)

        # A blank/whitespace-only pain_points string is normalized to the
        # "no specific signals found" placeholder by parse_research_response
        # before the no-signals-vs-list-item branch is evaluated.
        normalized = (pain_points_value or "").strip() or "no specific signals found"

        assert isinstance(result.business_pain_points, list)
        if normalized.lower() == "no specific signals found":
            assert result.business_pain_points == []
        else:
            assert result.business_pain_points == [normalized]
        assert result.pain_points_summary == normalized
        assert result.research_summary == normalized
