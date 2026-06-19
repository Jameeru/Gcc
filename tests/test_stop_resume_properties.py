"""
Property-based tests for stop/resume functionality with result preservation.

Tests Property 13: Stop Functionality Preservation - stopped sessions preserve
completed results, and validates the resume functionality allows continuation
from where processing left off.

**Validates: Requirements 6.3, 6.4**
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock, patch

import hypothesis.strategies as st
from hypothesis import given, assume

from src.components.results_processor import (
    PROVIDER_OPENAI,
    PROVIDER_GEMINI,
    ProcessedItem, 
    ProcessingState,
    clear_state,
    get_current_state,
    resume_processing,
    start_new_batch,
)
from src.models.entities import CompanyRecord, ResearchResult


def _company(name="Acme Inc", domain="acme.com", row_index=0):
    return CompanyRecord(
        name=name,
        domain=domain,
        normalized_key=f"{name.lower()}_{domain}",
        row_index=row_index,
    )


def _research_result(company_name="Acme Inc"):
    return ResearchResult(
        company_name=company_name,
        company_domain="acme.com",
        gcc_presence=True,
        gcc_location="Pune, India",
        suitability_score=7,
        business_pain_points=["Scaling challenges"],
        expansion_indicators=["New funding"],
        hiring_signals=["Open roles"],
        research_summary="Solid candidate.",
        is_cached=False,
        created_at=datetime.now(timezone.utc),
    )


class TestStopFunctionalityPreservation:
    """
    Property 13: Stop Functionality Preservation - For any processing session 
    that is stopped, all previously completed results shall be preserved and 
    remain accessible.
    
    **Validates: Requirements 6.3, 6.4**
    """

    def setup_method(self):
        clear_state()

    def teardown_method(self):
        clear_state()

    @given(
        num_companies=st.integers(min_value=2, max_value=10),
        stop_at_index=st.integers(min_value=1, max_value=5),
        provider=st.sampled_from([PROVIDER_OPENAI, PROVIDER_GEMINI])
    )
    def test_stopped_session_preserves_completed_results(self, num_companies, stop_at_index, provider):
        """
        Property 13: For any processing session that is stopped, all previously 
        completed results shall be preserved and remain accessible.
        
        **Validates: Requirements 6.3, 6.4**
        """
        assume(stop_at_index < num_companies)
        
        # Create a processing session with multiple companies
        companies = [_company(f"Company{i}", f"company{i}.com", i) for i in range(num_companies)]
        
        with patch('src.components.results_processor._create_db_session'):
            start_new_batch(companies, "test-session", provider=provider)
        
        state = get_current_state()
        assert state is not None
        
        # Simulate processing some companies before stopping
        for i in range(stop_at_index):
            result = _research_result(f"Company{i}")
            processed_item = ProcessedItem(
                company_record=companies[i],
                research_result=result,
                is_cached=False
            )
            state.items.append(processed_item)
            state.current_index += 1
            state.cache_hits += 1 if i % 2 == 0 else 0  # Mix of cache hits
        
        # Stop the session
        state.status = "stopped"
        
        # Verify all completed results are preserved
        assert len(state.items) == stop_at_index
        assert state.current_index == stop_at_index
        assert state.status == "stopped"
        
        # Verify each processed item is preserved correctly
        for i, item in enumerate(state.items):
            assert item.company_record.name == f"Company{i}"
            assert item.research_result is not None
            assert item.research_result.company_name == f"Company{i}"
        
        # Verify remaining companies are not processed
        assert len(state.items) < len(companies)
        
    @given(
        total_companies=st.integers(min_value=3, max_value=8),
        first_stop_at=st.integers(min_value=1, max_value=3),
        provider=st.sampled_from([PROVIDER_OPENAI, PROVIDER_GEMINI])
    )
    def test_resume_continues_from_stop_point(self, total_companies, first_stop_at, provider):
        """
        Property: Resume functionality continues processing from exactly where
        it stopped, preserving all previous results and state.
        
        **Validates: Requirements 6.3, 6.4**
        """
        assume(first_stop_at < total_companies)
        
        # Create and start a processing session
        companies = [_company(f"Firm{i}", f"firm{i}.com", i) for i in range(total_companies)]
        
        with patch('src.components.results_processor._create_db_session'):
            start_new_batch(companies, "resume-test-session", provider=provider)
        
        state = get_current_state()
        assert state is not None
        
        # Process some companies
        for i in range(first_stop_at):
            result = _research_result(f"Firm{i}")
            processed_item = ProcessedItem(
                company_record=companies[i],
                research_result=result,
                is_cached=i % 2 == 0  # Mix of cached and fresh results
            )
            state.items.append(processed_item)
            state.current_index += 1
            if i % 2 == 0:
                state.cache_hits += 1
        
        original_items_count = len(state.items)
        original_index = state.current_index
        original_cache_hits = state.cache_hits
        
        # Stop the session
        state.status = "stopped"
        
        # Resume the session
        success = resume_processing(state.session_id)
        assert success is True
        assert state.status == "running"
        
        # Verify state is preserved after resume
        assert len(state.items) == original_items_count
        assert state.current_index == original_index
        assert state.cache_hits == original_cache_hits
        
        # Verify the items are identical before and after resume
        for i, item in enumerate(state.items):
            assert item.company_record.name == f"Firm{i}"
            assert item.research_result is not None
            
        # Verify we can continue processing from where we stopped
        assert state.current_index < len(state.company_records)
        next_company = state.company_records[state.current_index]
        assert next_company.name == f"Firm{first_stop_at}"
        
    def test_cannot_resume_running_session(self):
        """
        Property: Cannot resume when another session is already running.
        
        **Validates: Requirements 6.3**
        """
        companies = [_company("Test1"), _company("Test2")]
        
        with patch('src.components.results_processor._create_db_session'):
            start_new_batch(companies, "running-session", PROVIDER_OPENAI)
        
        state = get_current_state()
        assert state is not None
        assert state.status == "running"
        
        # Try to resume - should fail because session is running, not stopped
        success = resume_processing("different-session")
        assert success is False
        
        # Original session should still be running
        assert state.status == "running"
        
    def test_cannot_resume_nonexistent_session(self):
        """
        Property: Cannot resume a session that doesn't exist.
        
        **Validates: Requirements 6.3**
        """
        clear_state()
        assert get_current_state() is None
        
        # Try to resume non-existent session
        success = resume_processing("non-existent-session")
        assert success is False
        
    def test_cannot_resume_completed_session(self):
        """
        Property: Cannot resume a session that is already completed.
        
        **Validates: Requirements 6.3**
        """
        companies = [_company("Done1"), _company("Done2")]
        
        with patch('src.components.results_processor._create_db_session'):
            start_new_batch(companies, "completed-session", PROVIDER_OPENAI)
        
        state = get_current_state()
        assert state is not None
        
        # Mark as completed
        state.status = "completed"
        state.current_index = len(companies)
        
        # Try to resume completed session - should fail
        success = resume_processing(state.session_id)
        assert success is False
        assert state.status == "completed"  # Status should remain unchanged

    @given(
        num_companies=st.integers(min_value=2, max_value=6),
        stop_indices=st.lists(st.integers(min_value=1, max_value=5), min_size=1, max_size=3)
    )
    def test_multiple_stop_resume_cycles_preserve_state(self, num_companies, stop_indices):
        """
        Property: Multiple stop/resume cycles preserve cumulative state correctly.
        
        **Validates: Requirements 6.3, 6.4**
        """
        # Ensure all stop indices are valid and in ascending order
        valid_stops = sorted([idx for idx in stop_indices if idx < num_companies])
        assume(len(valid_stops) > 0)
        
        companies = [_company(f"Multi{i}", f"multi{i}.com", i) for i in range(num_companies)]
        
        with patch('src.components.results_processor._create_db_session'):
            start_new_batch(companies, "multi-stop-session", PROVIDER_OPENAI)
        
        state = get_current_state()
        assert state is not None
        
        last_processed = 0
        
        for stop_at in valid_stops:
            # Process up to the stop point
            while state.current_index < stop_at and state.current_index < len(companies):
                idx = state.current_index
                result = _research_result(f"Multi{idx}")
                processed_item = ProcessedItem(
                    company_record=companies[idx],
                    research_result=result,
                    is_cached=False
                )
                state.items.append(processed_item)
                state.current_index += 1
                last_processed = idx + 1
            
            # Stop and verify preservation
            state.status = "stopped"
            assert len(state.items) == last_processed
            assert state.current_index == last_processed
            
            # Resume and verify state continuity
            success = resume_processing(state.session_id)
            assert success is True
            assert state.status == "running"
            assert len(state.items) == last_processed
            assert state.current_index == last_processed
        
        # Verify final state consistency
        assert all(item.research_result is not None for item in state.items)
        assert len(set(item.company_record.name for item in state.items)) == len(state.items)  # No duplicates