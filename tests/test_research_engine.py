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
    ResearchAPIError,
    ResearchEngine,
    ResearchEngineError,
    ResearchNoKeyConfiguredError,
    ResearchResponseError,
    exponential_backoff_retry,
    get_research_engine,
)
from src.models.entities import ResearchResult


def _valid_payload(**overrides):
    payload = {
        "gcc_presence": True,
        "gcc_location": "Bangalore, India",
        "suitability_score": 8,
        "business_pain_points": ["High operational costs"],
        "expansion_indicators": ["Recent funding round"],
        "hiring_signals": ["Active job postings"],
        "research_summary": "Strong GCC candidate.",
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
    def setup_method(self):
        self.engine = ResearchEngine(client=Mock())

    def test_valid_response_parses_correctly(self):
        result = self.engine._parse_and_validate(
            json.dumps(_valid_payload()), "Microsoft", "microsoft.com"
        )
        assert isinstance(result, ResearchResult)
        assert result.company_name == "Microsoft"
        assert result.suitability_score == 8
        assert result.gcc_presence is True
        assert result.business_pain_points == ["High operational costs"]

    def test_invalid_json_raises_response_error(self):
        with pytest.raises(ResearchResponseError, match="not valid JSON"):
            self.engine._parse_and_validate("not json {{{", "Acme", None)

    def test_missing_required_field_raises_response_error(self):
        payload = _valid_payload()
        del payload["suitability_score"]
        with pytest.raises(ResearchResponseError, match="missing required fields"):
            self.engine._parse_and_validate(json.dumps(payload), "Acme", None)

    @pytest.mark.parametrize("field", REQUIRED_FIELDS)
    def test_each_required_field_is_actually_required(self, field):
        payload = _valid_payload()
        del payload[field]
        with pytest.raises(ResearchResponseError):
            self.engine._parse_and_validate(json.dumps(payload), "Acme", None)

    def test_score_above_range_is_clamped_not_rejected(self):
        result = self.engine._parse_and_validate(
            json.dumps(_valid_payload(suitability_score=15)), "Acme", None
        )
        assert result.suitability_score == 10

    def test_score_below_range_is_clamped_not_rejected(self):
        result = self.engine._parse_and_validate(
            json.dumps(_valid_payload(suitability_score=-3)), "Acme", None
        )
        assert result.suitability_score == 1

    def test_non_integer_score_raises_response_error(self):
        with pytest.raises(ResearchResponseError, match="must be an integer"):
            self.engine._parse_and_validate(
                json.dumps(_valid_payload(suitability_score="not-a-number")), "Acme", None
            )

    def test_scalar_list_fields_coerced_to_single_item_list(self):
        result = self.engine._parse_and_validate(
            json.dumps(_valid_payload(business_pain_points="Just one pain point")),
            "Acme",
            None,
        )
        assert result.business_pain_points == ["Just one pain point"]

    def test_none_list_fields_coerced_to_empty_list(self):
        result = self.engine._parse_and_validate(
            json.dumps(_valid_payload(expansion_indicators=None)), "Acme", None
        )
        assert result.expansion_indicators == []

    def test_blank_summary_defaults_to_placeholder(self):
        result = self.engine._parse_and_validate(
            json.dumps(_valid_payload(research_summary="   ")), "Acme", None
        )
        assert result.research_summary == "No summary provided."


class TestResearchCompany:
    def test_success_on_first_attempt(self):
        mock_client = Mock()
        mock_client.chat.completions.create.return_value = _make_completion(
            json.dumps(_valid_payload())
        )
        engine = ResearchEngine(client=mock_client)

        result = engine.research_company("Microsoft", "microsoft.com")

        assert result.company_name == "Microsoft"
        assert mock_client.chat.completions.create.call_count == 1

    def test_retries_on_rate_limit_then_succeeds(self):
        mock_client = Mock()
        mock_client.chat.completions.create.side_effect = [
            _make_rate_limit_error(),
            _make_completion(json.dumps(_valid_payload())),
        ]
        engine = ResearchEngine(client=mock_client)
        engine._config = Mock(max_retries=3, retry_delay=1.0, max_retry_delay=60.0)

        with patch("time.sleep"):
            result = engine.research_company("Acme", "acme.com")

        assert result.company_name == "Acme"
        assert mock_client.chat.completions.create.call_count == 2

    def test_exhausted_retries_raise_research_api_error(self):
        mock_client = Mock()
        mock_client.chat.completions.create.side_effect = _make_connection_error()
        engine = ResearchEngine(client=mock_client)
        engine._config = Mock(max_retries=3, retry_delay=1.0, max_retry_delay=60.0)

        with patch("time.sleep"):
            with pytest.raises(ResearchAPIError):
                engine.research_company("Acme", "acme.com")

        assert mock_client.chat.completions.create.call_count == 3

    def test_malformed_response_not_retried(self):
        """
        Malformed JSON indicates a prompting/schema issue, not a transient
        failure, so research_company should surface ResearchResponseError
        directly without burning through retry attempts.
        """
        mock_client = Mock()
        mock_client.chat.completions.create.return_value = _make_completion("not valid json")
        engine = ResearchEngine(client=mock_client)
        engine._config = Mock(max_retries=3, retry_delay=1.0, max_retry_delay=60.0)

        with pytest.raises(ResearchResponseError):
            engine.research_company("Acme", "acme.com")

        # Only one call -- the bad JSON came back successfully from the API,
        # so the retry loop (which only catches API-level failures) never re-invoked it.
        assert mock_client.chat.completions.create.call_count == 1

    def test_research_engine_error_is_common_base_class(self):
        assert issubclass(ResearchAPIError, ResearchEngineError)
        assert issubclass(ResearchResponseError, ResearchEngineError)


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
        mock_client.chat.completions.create.return_value = _make_completion(
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

# Strategy for generating valid research response JSON data
@st.composite
def valid_research_response_strategy(draw):
    """Generate valid research response data that should pass validation."""
    return {
        "gcc_presence": draw(st.booleans()),
        "gcc_location": draw(st.one_of(
            st.none(),
            st.text(alphabet=string.ascii_letters + string.digits + " ,.-", min_size=1, max_size=100)
        )),
        "suitability_score": draw(st.integers(min_value=1, max_value=10)),
        "business_pain_points": draw(st.lists(
            st.text(alphabet=valid_company_chars, min_size=1, max_size=200),
            min_size=0, max_size=10
        )),
        "expansion_indicators": draw(st.lists(
            st.text(alphabet=valid_company_chars, min_size=1, max_size=200),
            min_size=0, max_size=10
        )),
        "hiring_signals": draw(st.lists(
            st.text(alphabet=valid_company_chars, min_size=1, max_size=200),
            min_size=0, max_size=10
        )),
        "research_summary": draw(st.text(alphabet=valid_company_chars, min_size=1, max_size=1000))
    }

# Helper function for checking int conversion
def is_convertible_to_int(value):
    """Check if a value can be converted to int without error."""
    try:
        int(value)
        return True
    except (ValueError, TypeError):
        return False

# Strategy for generating invalid suitability scores that should raise errors
invalid_scores_strategy = st.one_of(
    st.text().filter(lambda x: not is_convertible_to_int(x)),  # Non-numeric string values
    st.none(),  # None values
    st.lists(st.integers()),  # Lists
    st.dictionaries(st.text(), st.integers())  # Dictionaries
)

# Strategy for generating out-of-range but valid numeric scores
out_of_range_scores_strategy = st.one_of(
    st.integers(max_value=0),
    st.integers(min_value=11),
    st.floats(allow_nan=False, allow_infinity=False)  # Float values that can be converted
)


class TestResearchResponseValidationProperties:
    """
    Property-based tests for research response validation.
    
    **Property 9: Research Response Validation**
    *For any* research operation that completes successfully, the returned result 
    shall be valid JSON containing all required fields with suitability scores between 1-10
    
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
        with suitability scores between 1-10, the validation should succeed
        and return a proper ResearchResult object.
        
        **Validates: Requirements 5.3, 5.6**
        """
        # Convert response data to JSON string
        json_response = json.dumps(response_data)
        
        # Parse and validate the response
        result = self.engine._parse_and_validate(json_response, company_name, domain)
        
        # Verify all required properties
        assert isinstance(result, ResearchResult)
        assert result.company_name == company_name
        assert result.company_domain == domain
        assert result.gcc_presence == response_data["gcc_presence"]
        assert result.gcc_location == response_data["gcc_location"]
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
        # Generate valid response data
        response_data = {
            "gcc_presence": True,
            "gcc_location": "Bangalore, India",
            "suitability_score": 8,
            "business_pain_points": ["High costs"],
            "expansion_indicators": ["Growth signals"],
            "hiring_signals": ["Active recruiting"],
            "research_summary": "Good candidate"
        }
        
        # Remove one required field
        del response_data[missing_field]
        json_response = json.dumps(response_data)
        
        # Should raise ResearchResponseError
        with pytest.raises(ResearchResponseError, match="missing required fields"):
            self.engine._parse_and_validate(json_response, company_name, domain)

    @given(
        company_name=company_name_strategy(),
        domain=st.one_of(st.none(), domain_strategy()),
        invalid_score=invalid_scores_strategy
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_property_9_truly_invalid_suitability_scores_fail_validation(
        self, company_name: str, domain: Optional[str], invalid_score: Any
    ):
        """
        **Property 9: Research Response Validation - Invalid Score Types**
        
        For any research response with non-numeric suitability scores,
        the validation should fail with ResearchResponseError.
        
        **Validates: Requirements 5.3, 5.6**
        """
        response_data = {
            "gcc_presence": True,
            "gcc_location": "Mumbai, India",
            "suitability_score": invalid_score,
            "business_pain_points": ["Cost challenges"],
            "expansion_indicators": ["Market expansion"],
            "hiring_signals": ["Tech hiring"],
            "research_summary": "Analysis complete"
        }
        
        json_response = json.dumps(response_data)
        
        # These should all raise ResearchResponseError
        with pytest.raises(ResearchResponseError, match="must be an integer"):
            self.engine._parse_and_validate(json_response, company_name, domain)

    @given(
        company_name=company_name_strategy(),
        domain=st.one_of(st.none(), domain_strategy()),
        out_of_range_score=out_of_range_scores_strategy
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_property_9_out_of_range_numeric_scores_are_clamped(
        self, company_name: str, domain: Optional[str], out_of_range_score: Union[int, float]
    ):
        """
        **Property 9: Research Response Validation - Score Clamping**
        
        For any research response with numeric but out-of-range suitability scores,
        the scores should be clamped to the valid 1-10 range.
        
        **Validates: Requirements 5.3, 5.6**
        """
        response_data = {
            "gcc_presence": True,
            "gcc_location": "Mumbai, India", 
            "suitability_score": out_of_range_score,
            "business_pain_points": ["Cost challenges"],
            "expansion_indicators": ["Market expansion"],
            "hiring_signals": ["Tech hiring"],
            "research_summary": "Analysis complete"
        }
        
        json_response = json.dumps(response_data)
        
        # Should not raise an exception but clamp the value
        result = self.engine._parse_and_validate(json_response, company_name, domain)
        assert 1 <= result.suitability_score <= 10
        
        # Verify clamping behavior
        try:
            int_score = int(out_of_range_score)
            if int_score < 1:
                assert result.suitability_score == 1
            elif int_score > 10:
                assert result.suitability_score == 10
            else:
                assert result.suitability_score == int_score
        except (ValueError, OverflowError):
            # For extreme float values that can't be converted to int
            # The system should still clamp to valid range
            assert 1 <= result.suitability_score <= 10

    def test_property_9_malformed_json_fails_validation_simple(self):
        """
        **Property 9: Research Response Validation - JSON Format**
        
        Test specific cases of malformed JSON that should fail validation.
        
        **Validates: Requirements 5.3, 5.6**
        """
        malformed_responses = [
            "not json at all",
            '{"incomplete": json',
            '{gcc_presence: true}',  # unquoted keys
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
        list_field=st.sampled_from(["business_pain_points", "expansion_indicators", "hiring_signals"]),
        list_value=st.one_of(
            st.none(),
            st.text(),
            st.integers(),
            st.lists(st.text(), min_size=0, max_size=5)
        )
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_property_9_list_fields_coercion_behavior(
        self, company_name: str, domain: Optional[str], list_field: str, list_value: Any
    ):
        """
        **Property 9: Research Response Validation - List Field Handling**
        
        For any research response, list fields should be properly coerced:
        - None values become empty lists
        - Scalar values become single-item lists
        - Lists remain as lists (with string conversion of items)
        
        **Validates: Requirements 5.3, 5.6**
        """
        response_data = {
            "gcc_presence": False,
            "gcc_location": None,
            "suitability_score": 5,
            "business_pain_points": [],
            "expansion_indicators": [],
            "hiring_signals": [],
            "research_summary": "Research completed"
        }
        
        # Set the specific list field to the test value
        response_data[list_field] = list_value
        json_response = json.dumps(response_data)
        
        result = self.engine._parse_and_validate(json_response, company_name, domain)
        
        # Check that the field was properly coerced to a list
        field_result = getattr(result, list_field)
        assert isinstance(field_result, list)
        
        if list_value is None:
            assert field_result == []
        elif isinstance(list_value, list):
            assert field_result == [str(item) for item in list_value]
        else:
            assert field_result == [str(list_value)]
