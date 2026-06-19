"""
Property-based tests for exponential backoff retry logic consistency.

These tests validate Property 10: Retry Logic Consistency - that for any
API failure scenario, the retry mechanism executes exactly three attempts
with exponential backoff timing before final failure.

**Validates: Requirements 5.7, 10.1**
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

import time
from unittest.mock import Mock, patch
from typing import List, Tuple

import pytest
from hypothesis import given, strategies as st, assume, settings
from hypothesis.strategies import SearchStrategy

from src.components.research_engine import exponential_backoff_retry


class RetryBehaviorTracker:
    """Helper class to track retry behavior during property tests."""
    
    def __init__(self):
        self.call_count = 0
        self.sleep_calls: List[float] = []
        self.exceptions_raised: List[Exception] = []
        self.on_retry_calls: List[Tuple[int, Exception]] = []
    
    def failing_func(self, exception_type: type = Exception):
        """Function that always fails with the specified exception type."""
        def _func():
            self.call_count += 1
            exc = exception_type(f"Attempt {self.call_count} failed")
            self.exceptions_raised.append(exc)
            raise exc
        return _func
    
    def eventually_succeeding_func(self, fail_count: int, exception_type: type = Exception):
        """Function that fails for fail_count attempts, then succeeds."""
        def _func():
            self.call_count += 1
            if self.call_count <= fail_count:
                exc = exception_type(f"Attempt {self.call_count} failed")
                self.exceptions_raised.append(exc)
                raise exc
            return f"Success on attempt {self.call_count}"
        return _func
    
    def mock_sleep(self, delay: float):
        """Mock sleep function that records all delays."""
        self.sleep_calls.append(delay)
    
    def on_retry_callback(self, attempt: int, exception: Exception):
        """Callback that records retry attempts."""
        self.on_retry_calls.append((attempt, exception))


def retry_config_strategy() -> SearchStrategy[Tuple[int, float, float]]:
    """Generate valid retry configurations."""
    return st.tuples(
        st.integers(min_value=1, max_value=10),  # max_attempts
        st.floats(min_value=0.1, max_value=5.0),  # base_delay
        st.floats(min_value=1.0, max_value=120.0),  # max_delay
    ).filter(lambda cfg: cfg[2] >= cfg[1])  # max_delay >= base_delay


class TestRetryLogicConsistency:
    """
    Property 10: Retry Logic Consistency
    
    For any API failure scenario, the retry mechanism shall execute exactly
    the configured number of attempts with exponential backoff timing before
    final failure.
    """
    
    @given(retry_config_strategy())
    @settings(max_examples=50, deadline=5000)
    def test_property_10_exact_attempt_count_on_continuous_failure(self, config):
        """
        Property: Continuous failures result in exactly max_attempts calls.
        
        **Validates: Requirements 5.7, 10.1**
        """
        max_attempts, base_delay, max_delay = config
        tracker = RetryBehaviorTracker()
        
        with patch('time.sleep', side_effect=tracker.mock_sleep):
            with pytest.raises(Exception):  # Should raise the last exception
                exponential_backoff_retry(
                    tracker.failing_func(ValueError),
                    max_attempts=max_attempts,
                    base_delay=base_delay,
                    max_delay=max_delay,
                    on_retry=tracker.on_retry_callback
                )
        
        # Property: Exactly max_attempts function calls
        assert tracker.call_count == max_attempts
        
        # Property: Exactly (max_attempts - 1) sleep calls (no sleep after last attempt)
        assert len(tracker.sleep_calls) == max_attempts - 1
        
        # Property: Exactly (max_attempts - 1) on_retry callbacks
        assert len(tracker.on_retry_calls) == max_attempts - 1
        
        # Property: on_retry callback gets correct attempt indices
        expected_attempts = list(range(max_attempts - 1))
        actual_attempts = [call[0] for call in tracker.on_retry_calls]
        assert actual_attempts == expected_attempts
    
    @given(retry_config_strategy(), st.integers(min_value=1, max_value=5))
    @settings(max_examples=50, deadline=5000)
    def test_property_10_early_success_stops_retrying(self, config, success_attempt):
        """
        Property: Success on attempt N results in exactly N calls, no further retries.
        
        **Validates: Requirements 5.7, 10.1**
        """
        max_attempts, base_delay, max_delay = config
        assume(success_attempt <= max_attempts)
        
        tracker = RetryBehaviorTracker()
        fail_count = success_attempt - 1  # Fail this many times, then succeed
        
        with patch('time.sleep', side_effect=tracker.mock_sleep):
            result = exponential_backoff_retry(
                tracker.eventually_succeeding_func(fail_count, ValueError),
                max_attempts=max_attempts,
                base_delay=base_delay,
                max_delay=max_delay,
                on_retry=tracker.on_retry_callback
            )
        
        # Property: Exactly success_attempt function calls
        assert tracker.call_count == success_attempt
        
        # Property: Exactly fail_count sleep calls (no sleep after success)
        assert len(tracker.sleep_calls) == fail_count
        
        # Property: Exactly fail_count on_retry callbacks 
        assert len(tracker.on_retry_calls) == fail_count
        
        # Property: Function returns the success value
        assert result == f"Success on attempt {success_attempt}"
    
    @given(st.floats(min_value=0.1, max_value=5.0), st.floats(min_value=10.0, max_value=60.0))
    @settings(max_examples=50, deadline=5000)
    def test_property_10_exponential_backoff_timing(self, base_delay, max_delay):
        """
        Property: Delay follows exponential backoff pattern with proper capping.
        
        **Validates: Requirements 5.7, 10.1**
        """
        assume(max_delay >= base_delay)
        
        tracker = RetryBehaviorTracker()
        max_attempts = 5  # Fixed attempts to test timing pattern
        
        with patch('time.sleep', side_effect=tracker.mock_sleep):
            with pytest.raises(Exception):
                exponential_backoff_retry(
                    tracker.failing_func(ValueError),
                    max_attempts=max_attempts,
                    base_delay=base_delay,
                    max_delay=max_delay,
                    on_retry=tracker.on_retry_callback
                )
        
        # Property: Each delay follows exponential pattern or is capped
        expected_delays = []
        for attempt in range(max_attempts - 1):
            expected_delay = min(base_delay * (2 ** attempt), max_delay)
            expected_delays.append(expected_delay)
        
        assert tracker.sleep_calls == expected_delays
        
        # Property: No delay exceeds max_delay
        assert all(delay <= max_delay for delay in tracker.sleep_calls)
        
        # Property: Delays are non-decreasing (due to exponential growth + capping)
        for i in range(1, len(tracker.sleep_calls)):
            assert tracker.sleep_calls[i] >= tracker.sleep_calls[i-1]
    
    @given(retry_config_strategy())
    @settings(max_examples=50, deadline=5000)
    def test_property_10_last_exception_propagated(self, config):
        """
        Property: The last exception raised by the function is propagated after all retries.
        
        **Validates: Requirements 5.7, 10.1**
        """
        max_attempts, base_delay, max_delay = config
        tracker = RetryBehaviorTracker()
        
        with patch('time.sleep', side_effect=tracker.mock_sleep):
            with pytest.raises(ValueError) as exc_info:
                exponential_backoff_retry(
                    tracker.failing_func(ValueError),
                    max_attempts=max_attempts,
                    base_delay=base_delay,
                    max_delay=max_delay
                )
        
        # Property: The raised exception is the last one from the function
        last_exception = tracker.exceptions_raised[-1]
        assert str(exc_info.value) == str(last_exception)
        assert type(exc_info.value) == type(last_exception)
    
    def test_property_10_default_configuration_matches_spec(self):
        """
        Property: Default retry configuration matches the design specification.
        
        The spec requires:
        - Maximum 3 retry attempts before final failure
        - Base delay of 1.0 seconds
        - Maximum delay of 60 seconds
        
        **Validates: Requirements 5.7, 10.1**
        """
        tracker = RetryBehaviorTracker()
        
        with patch('time.sleep', side_effect=tracker.mock_sleep):
            with pytest.raises(Exception):
                # Use default parameters (should match spec)
                exponential_backoff_retry(
                    tracker.failing_func(ValueError)
                )
        
        # Property: Exactly 3 attempts as specified in requirements
        assert tracker.call_count == 3
        
        # Property: 2 sleep calls (between 3 attempts)
        assert len(tracker.sleep_calls) == 2
        
        # Property: First delay is 1.0 second (base_delay)
        assert tracker.sleep_calls[0] == 1.0
        
        # Property: Second delay is 2.0 seconds (base_delay * 2^1)
        assert tracker.sleep_calls[1] == 2.0
        
        # Property: Both delays are within the 60-second max_delay limit
        assert all(delay <= 60.0 for delay in tracker.sleep_calls)
    
    @given(st.integers(min_value=1, max_value=10))
    @settings(max_examples=20, deadline=5000)
    def test_property_10_no_sleep_on_immediate_success(self, max_attempts):
        """
        Property: No sleep calls or retry callbacks when function succeeds immediately.
        
        **Validates: Requirements 5.7, 10.1**
        """
        tracker = RetryBehaviorTracker()
        
        def immediate_success():
            tracker.call_count += 1
            return "immediate success"
        
        with patch('time.sleep', side_effect=tracker.mock_sleep):
            result = exponential_backoff_retry(
                immediate_success,
                max_attempts=max_attempts,
                on_retry=tracker.on_retry_callback
            )
        
        # Property: Exactly one function call
        assert tracker.call_count == 1
        
        # Property: No sleep calls on immediate success
        assert len(tracker.sleep_calls) == 0
        
        # Property: No retry callbacks on immediate success
        assert len(tracker.on_retry_calls) == 0
        
        # Property: Returns the success value
        assert result == "immediate success"
    
    @given(retry_config_strategy())
    @settings(max_examples=30, deadline=5000)
    def test_property_10_retry_callback_receives_correct_data(self, config):
        """
        Property: on_retry callback receives correct attempt index and exception.
        
        **Validates: Requirements 5.7, 10.1**
        """
        max_attempts, base_delay, max_delay = config
        assume(max_attempts >= 2)  # Need at least 2 attempts to test callback
        
        tracker = RetryBehaviorTracker()
        
        with patch('time.sleep', side_effect=tracker.mock_sleep):
            with pytest.raises(Exception):
                exponential_backoff_retry(
                    tracker.failing_func(RuntimeError),
                    max_attempts=max_attempts,
                    base_delay=base_delay,
                    max_delay=max_delay,
                    on_retry=tracker.on_retry_callback
                )
        
        # Property: Callback called for each retry (not including final failure)
        assert len(tracker.on_retry_calls) == max_attempts - 1
        
        # Property: Attempt indices are sequential starting from 0
        for i, (attempt_idx, exception) in enumerate(tracker.on_retry_calls):
            assert attempt_idx == i
            
            # Property: Exception passed to callback matches the one that was raised
            expected_exception = tracker.exceptions_raised[i]
            assert str(exception) == str(expected_exception)
            assert type(exception) == type(expected_exception)


class TestResearchEngineRetryIntegration:
    """
    Integration tests ensuring the ResearchEngine uses retry logic correctly
    with the specified configuration values.
    """
    
    def test_research_engine_uses_configured_retry_parameters(self):
        """
        Verify that ResearchEngine.research_company uses the retry mechanism
        with the configuration values from the OpenAI config.
        
        **Validates: Requirements 5.7, 10.1**
        """
        from src.components.research_engine import ResearchEngine
        from unittest.mock import Mock
        import httpx
        from openai import APIConnectionError
        
        # Create a mock client that always fails
        mock_client = Mock()
        request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
        connection_error = APIConnectionError(request=request)
        mock_client.chat.completions.create.side_effect = connection_error
        
        # Create engine with mock config
        engine = ResearchEngine(client=mock_client)
        engine._config = Mock(
            max_retries=3,
            retry_delay=1.0, 
            max_retry_delay=60.0,
            model="gpt-4o",
            max_tokens=2000,
            temperature=0.1
        )
        
        sleep_calls = []
        def mock_sleep(delay):
            sleep_calls.append(delay)
        
        with patch('time.sleep', side_effect=mock_sleep):
            with pytest.raises(Exception):  # Should raise ResearchAPIError
                engine.research_company("Test Company", "test.com")
        
        # Verify retry behavior matches configuration
        assert mock_client.chat.completions.create.call_count == 3  # max_retries
        assert len(sleep_calls) == 2  # 3 attempts = 2 sleep calls
        assert sleep_calls == [1.0, 2.0]  # base_delay=1.0, exponential backoff


# Run property tests focused on the OpenAI configuration defaults
class TestOpenAIConfigRetryDefaults:
    """
    Focused tests ensuring the OpenAI configuration defaults match 
    the design specification requirements.
    """
    
    def test_openai_config_retry_defaults_match_spec(self):
        """
        Verify the OpenAI configuration uses the retry parameters specified
        in the design document (3 attempts, 1.0s base, 60s max).
        
        **Validates: Requirements 5.7, 10.1**
        """
        from src.utils.config import get_config
        
        config = get_config().openai
        
        # Design spec requirements:
        # - Maximum 3 retry attempts before final failure
        # - Base delay of 1.0 seconds  
        # - Maximum delay of 60 seconds
        assert config.max_retries == 3
        assert config.retry_delay == 1.0
        assert config.max_retry_delay == 60.0