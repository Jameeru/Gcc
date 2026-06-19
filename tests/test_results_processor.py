"""
Unit tests for the sequential results processor.

Covers cache-hit/miss branching, per-company error isolation (Property 19),
batch state lifecycle (start/get/clear), and the render_processor control
flow (stop preservation, rerun-per-company, terminal states) via a mocked
Streamlit module.

**Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 10.4**
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.components.gemini_engine import GeminiAPIError
from src.components.research_engine import ResearchAPIError
from src.core.cache_manager import CacheError
from src.models.entities import CompanyRecord, ResearchResult
import src.components.results_processor as rp


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


def _research_result_tri_state(gcc_status, fit_rating, company_name="Acme Inc"):
    """Build a ResearchResult with the new tri-state fields explicitly set,
    for tests that need to verify ProcessingState's gcc_no/gcc_yes/
    gcc_uncertain/fit_strong KPI counters."""
    return ResearchResult(
        company_name=company_name,
        company_domain="acme.com",
        gcc_presence=(gcc_status == "Yes"),
        gcc_location="Pune, India",
        suitability_score={"Strong": 9, "Possible": 5, "Unlikely": 2}[fit_rating],
        business_pain_points=["Scaling challenges"],
        expansion_indicators=["New funding"],
        hiring_signals=["Open roles"],
        research_summary="Solid candidate.",
        is_cached=False,
        created_at=datetime.now(timezone.utc),
        gcc_status=gcc_status,
        fit_rating=fit_rating,
        pain_points_summary="Solid candidate.",
    )


class TestBatchStateLifecycle:
    def setup_method(self):
        rp.clear_state()

    def teardown_method(self):
        rp.clear_state()

    @patch.object(rp, "_create_db_session")
    def test_start_new_batch_initializes_state(self, mock_create_db):
        records = [_company("Acme"), _company("Beta")]
        rp.start_new_batch(records, "session-123")

        state = rp.get_current_state()
        assert state is not None
        assert state.session_id == "session-123"
        assert state.company_records == records
        assert state.current_index == 0
        assert state.status == "running"
        assert state.items == []
        mock_create_db.assert_called_once_with("session-123", 2)

    def test_get_current_state_none_when_not_started(self):
        assert rp.get_current_state() is None

    @patch.object(rp, "_create_db_session")
    def test_clear_state_removes_active_batch(self, mock_create_db):
        rp.start_new_batch([_company()], "session-456")
        assert rp.get_current_state() is not None
        rp.clear_state()
        assert rp.get_current_state() is None


class TestResearchOneCompany:
    """
    Covers _research_one_company, the pure (no state-mutation) function that
    replaced the old _process_one for a single company's cache-lookup/
    research/cache-store sequence. This is what _process_chunk submits to
    its ThreadPoolExecutor for each company in a chunk.
    """

    @patch.object(rp, "get_cache_manager")
    def test_cache_hit_returns_cached_item(self, mock_get_cache_manager):
        cached_result = _research_result()
        mock_cache = Mock()
        mock_cache.lookup_cache.return_value = cached_result
        mock_get_cache_manager.return_value = mock_cache

        item = rp._research_one_company(_company(), rp.PROVIDER_OPENAI, "proc-session", None)

        assert item.is_cached is True
        assert item.research_result is cached_result
        assert item.error is None

    @patch.object(rp, "get_research_engine")
    @patch.object(rp, "get_cache_manager")
    def test_cache_miss_calls_research_engine_and_stores_result(
        self, mock_get_cache_manager, mock_get_research_engine
    ):
        mock_cache = Mock()
        mock_cache.lookup_cache.return_value = None
        mock_get_cache_manager.return_value = mock_cache

        fresh_result = _research_result()
        mock_engine = Mock()
        mock_engine.research_company.return_value = fresh_result
        mock_get_research_engine.return_value = mock_engine

        item = rp._research_one_company(_company(), rp.PROVIDER_OPENAI, "proc-session", None)

        assert item.is_cached is False
        assert item.research_result is fresh_result
        mock_cache.store_cache.assert_called_once()

    @patch.object(rp, "get_research_engine")
    @patch.object(rp, "get_cache_manager")
    def test_cache_lookup_error_falls_through_to_research(
        self, mock_get_cache_manager, mock_get_research_engine
    ):
        mock_cache = Mock()
        mock_cache.lookup_cache.side_effect = CacheError("db unavailable")
        mock_get_cache_manager.return_value = mock_cache

        fresh_result = _research_result()
        mock_engine = Mock()
        mock_engine.research_company.return_value = fresh_result
        mock_get_research_engine.return_value = mock_engine

        item = rp._research_one_company(_company(), rp.PROVIDER_OPENAI, "proc-session", None)

        mock_engine.research_company.assert_called_once()
        assert item.research_result is fresh_result

    @patch.object(rp, "get_research_engine")
    @patch.object(rp, "get_cache_manager")
    def test_research_failure_is_isolated_to_one_item(
        self, mock_get_cache_manager, mock_get_research_engine
    ):
        """Property 19: Error Isolation -- one company's failure must not
        raise out of _research_one_company."""
        mock_cache = Mock()
        mock_cache.lookup_cache.return_value = None
        mock_get_cache_manager.return_value = mock_cache

        mock_engine = Mock()
        mock_engine.research_company.side_effect = ResearchAPIError("OpenAI down")
        mock_get_research_engine.return_value = mock_engine

        item = rp._research_one_company(_company(), rp.PROVIDER_OPENAI, "proc-session", None)  # must not raise

        assert item.research_result is None
        assert "OpenAI down" in item.error

    @patch.object(rp, "get_research_engine")
    @patch.object(rp, "get_cache_manager")
    def test_cache_store_failure_does_not_discard_successful_result(
        self, mock_get_cache_manager, mock_get_research_engine
    ):
        mock_cache = Mock()
        mock_cache.lookup_cache.return_value = None
        mock_cache.store_cache.side_effect = CacheError("store failed")
        mock_get_cache_manager.return_value = mock_cache

        fresh_result = _research_result()
        mock_engine = Mock()
        mock_engine.research_company.return_value = fresh_result
        mock_get_research_engine.return_value = mock_engine

        item = rp._research_one_company(_company(), rp.PROVIDER_OPENAI, "proc-session", None)  # must not raise

        assert item.error is None
        assert item.research_result is fresh_result


class TestProcessChunk:
    """
    Covers _process_chunk, which advances ProcessingState by up to
    `state.chunk_size` companies per call, processed concurrently but
    appended to state.items in original order, and which maintains the
    cache_hits/errors counters plus the new tri-state KPI counters
    (gcc_no/gcc_yes/gcc_uncertain/fit_strong).
    """

    def _state(self, records=None, chunk_size=15):
        state = rp.ProcessingState(
            session_id="s1",
            company_records=records or [_company()],
        )
        state.chunk_size = chunk_size
        return state

    @patch.object(rp, "get_cache_manager")
    def test_cache_hit_increments_cache_hits_and_advances_index(self, mock_get_cache_manager):
        cached_result = _research_result()
        mock_cache = Mock()
        mock_cache.lookup_cache.return_value = cached_result
        mock_get_cache_manager.return_value = mock_cache

        state = self._state(chunk_size=1)
        rp._process_chunk(state, user_session_id=None)

        assert state.current_index == 1
        assert state.cache_hits == 1
        assert state.errors == 0
        assert len(state.items) == 1
        assert state.items[0].is_cached is True
        assert state.items[0].research_result is cached_result

    @patch.object(rp, "get_research_engine")
    @patch.object(rp, "get_cache_manager")
    def test_cache_miss_calls_research_engine_and_stores_result(
        self, mock_get_cache_manager, mock_get_research_engine
    ):
        mock_cache = Mock()
        mock_cache.lookup_cache.return_value = None
        mock_get_cache_manager.return_value = mock_cache

        fresh_result = _research_result()
        mock_engine = Mock()
        mock_engine.research_company.return_value = fresh_result
        mock_get_research_engine.return_value = mock_engine

        state = self._state(chunk_size=1)
        rp._process_chunk(state, user_session_id=None)

        assert state.current_index == 1
        assert state.cache_hits == 0
        assert state.errors == 0
        assert state.items[0].is_cached is False
        assert state.items[0].research_result is fresh_result
        mock_cache.store_cache.assert_called_once()

    @patch.object(rp, "get_research_engine")
    @patch.object(rp, "get_cache_manager")
    def test_research_failure_is_isolated_to_one_item(
        self, mock_get_cache_manager, mock_get_research_engine
    ):
        """Property 19: Error Isolation -- one company's failure must not
        raise out of _process_chunk or block the rest of the batch."""
        mock_cache = Mock()
        mock_cache.lookup_cache.return_value = None
        mock_get_cache_manager.return_value = mock_cache

        mock_engine = Mock()
        mock_engine.research_company.side_effect = ResearchAPIError("OpenAI down")
        mock_get_research_engine.return_value = mock_engine

        state = self._state(chunk_size=1)
        rp._process_chunk(state, user_session_id=None)  # must not raise

        assert state.current_index == 1
        assert state.errors == 1
        assert state.items[0].research_result is None
        assert "OpenAI down" in state.items[0].error

    @patch.object(rp, "get_cache_manager")
    def test_processes_companies_in_order_one_at_a_time(self, mock_get_cache_manager):
        mock_cache = Mock()
        mock_cache.lookup_cache.return_value = _research_result()
        mock_get_cache_manager.return_value = mock_cache

        records = [_company("Alpha", row_index=0), _company("Beta", row_index=1)]
        state = self._state(records, chunk_size=1)

        rp._process_chunk(state, user_session_id=None)
        rp._process_chunk(state, user_session_id=None)

        assert state.current_index == 2
        assert [item.company_record.name for item in state.items] == ["Alpha", "Beta"]

    @patch.object(rp, "get_cache_manager")
    def test_processes_multiple_companies_in_one_chunk_preserving_order(self, mock_get_cache_manager):
        """
        With chunk_size big enough to cover the whole batch, a single
        _process_chunk call should process every company concurrently but
        still append them to state.items in their original submission
        order (not ThreadPoolExecutor completion order).
        """
        mock_cache = Mock()
        mock_cache.lookup_cache.return_value = _research_result()
        mock_get_cache_manager.return_value = mock_cache

        records = [
            _company("Alpha", row_index=0),
            _company("Beta", row_index=1),
            _company("Gamma", row_index=2),
        ]
        state = self._state(records, chunk_size=15)

        rp._process_chunk(state, user_session_id=None)

        assert state.current_index == 3
        assert [item.company_record.name for item in state.items] == ["Alpha", "Beta", "Gamma"]

    @patch.object(rp, "get_research_engine")
    @patch.object(rp, "get_cache_manager")
    def test_chunk_size_caps_companies_processed_per_call(
        self, mock_get_cache_manager, mock_get_research_engine
    ):
        """A chunk never processes more than `state.chunk_size` companies,
        even if more remain unprocessed in the batch."""
        mock_cache = Mock()
        mock_cache.lookup_cache.return_value = None
        mock_get_cache_manager.return_value = mock_cache
        mock_engine = Mock()
        mock_engine.research_company.return_value = _research_result()
        mock_get_research_engine.return_value = mock_engine

        records = [_company(f"Co{i}", row_index=i) for i in range(5)]
        state = self._state(records, chunk_size=2)

        rp._process_chunk(state, user_session_id=None)

        assert state.current_index == 2
        assert len(state.items) == 2

    @patch.object(rp, "get_research_engine")
    @patch.object(rp, "get_cache_manager")
    def test_tri_state_kpi_counters_increment_per_result(
        self, mock_get_cache_manager, mock_get_research_engine
    ):
        """
        _process_chunk maintains gcc_no/gcc_yes/gcc_uncertain/fit_strong
        incrementally as each item completes -- verifies the new counters
        introduced alongside chunked processing.
        """
        mock_cache = Mock()
        mock_cache.lookup_cache.return_value = None
        mock_get_cache_manager.return_value = mock_cache

        results = [
            _research_result_tri_state("Yes", "Strong"),
            _research_result_tri_state("No", "Unlikely"),
            _research_result_tri_state("Uncertain", "Possible"),
        ]
        mock_engine = Mock()
        mock_engine.research_company.side_effect = results
        mock_get_research_engine.return_value = mock_engine

        records = [_company(f"Co{i}", row_index=i) for i in range(3)]
        state = self._state(records, chunk_size=3)

        rp._process_chunk(state, user_session_id=None)

        assert state.gcc_yes == 1
        assert state.gcc_no == 1
        assert state.gcc_uncertain == 1
        assert state.fit_strong == 1


class TestProviderSelection:
    """
    Covers the provider branching added on top of the existing
    cache-hit/miss/error-isolation logic (task #19): start_new_batch's
    provider validation, and _process_one routing cache misses to the
    correct engine (OpenAI vs. Gemini) based on ProcessingState.provider.

    **Validates the user's explicit request for dual OpenAI/Gemini
    integration, applied to the batch-processing pipeline.**
    """

    def setup_method(self):
        rp.clear_state()

    def teardown_method(self):
        rp.clear_state()

    @patch.object(rp, "_create_db_session")
    def test_start_new_batch_defaults_to_openai_provider(self, mock_create_db):
        rp.start_new_batch([_company()], "session-1")
        state = rp.get_current_state()
        assert state.provider == rp.PROVIDER_OPENAI

    @patch.object(rp, "_create_db_session")
    def test_start_new_batch_accepts_gemini_provider(self, mock_create_db):
        rp.start_new_batch([_company()], "session-1", provider=rp.PROVIDER_GEMINI)
        state = rp.get_current_state()
        assert state.provider == rp.PROVIDER_GEMINI

    def test_start_new_batch_rejects_unsupported_provider(self):
        with pytest.raises(ValueError, match="Unsupported provider"):
            rp.start_new_batch([_company()], "session-1", provider="claude")

    @patch.object(rp, "get_gemini_engine")
    @patch.object(rp, "get_research_engine")
    @patch.object(rp, "get_cache_manager")
    def test_gemini_provider_routes_cache_miss_to_gemini_engine(
        self, mock_get_cache_manager, mock_get_research_engine, mock_get_gemini_engine
    ):
        mock_cache = Mock()
        mock_cache.lookup_cache.return_value = None
        mock_get_cache_manager.return_value = mock_cache

        fresh_result = _research_result()
        mock_gemini_engine = Mock()
        mock_gemini_engine.research_company.return_value = fresh_result
        mock_get_gemini_engine.return_value = mock_gemini_engine

        record = _company()
        item = rp._research_one_company(record, rp.PROVIDER_GEMINI, "proc-session", None)

        mock_gemini_engine.research_company.assert_called_once()
        mock_get_research_engine.assert_not_called()
        assert item.research_result is fresh_result

    @patch.object(rp, "get_gemini_engine")
    @patch.object(rp, "get_research_engine")
    @patch.object(rp, "get_cache_manager")
    def test_openai_provider_routes_cache_miss_to_openai_engine(
        self, mock_get_cache_manager, mock_get_research_engine, mock_get_gemini_engine
    ):
        mock_cache = Mock()
        mock_cache.lookup_cache.return_value = None
        mock_get_cache_manager.return_value = mock_cache

        fresh_result = _research_result()
        mock_openai_engine = Mock()
        mock_openai_engine.research_company.return_value = fresh_result
        mock_get_research_engine.return_value = mock_openai_engine

        record = _company()
        item = rp._research_one_company(record, rp.PROVIDER_OPENAI, "proc-session", None)

        mock_openai_engine.research_company.assert_called_once()
        mock_get_gemini_engine.assert_not_called()
        assert item.research_result is fresh_result

    @patch.object(rp, "get_gemini_engine")
    @patch.object(rp, "get_cache_manager")
    def test_gemini_failure_is_isolated_to_one_item(
        self, mock_get_cache_manager, mock_get_gemini_engine
    ):
        """Property 19: Error Isolation, applied to the Gemini provider."""
        mock_cache = Mock()
        mock_cache.lookup_cache.return_value = None
        mock_get_cache_manager.return_value = mock_cache

        mock_gemini_engine = Mock()
        mock_gemini_engine.research_company.side_effect = GeminiAPIError("Gemini down")
        mock_get_gemini_engine.return_value = mock_gemini_engine

        record = _company()
        item = rp._research_one_company(record, rp.PROVIDER_GEMINI, "proc-session", None)  # must not raise

        assert item.research_result is None
        assert "Gemini down" in item.error

    @patch.object(rp, "get_gemini_engine")
    @patch.object(rp, "get_cache_manager")
    def test_cache_store_receives_provider_for_provenance(
        self, mock_get_cache_manager, mock_get_gemini_engine
    ):
        mock_cache = Mock()
        mock_cache.lookup_cache.return_value = None
        mock_get_cache_manager.return_value = mock_cache

        fresh_result = _research_result()
        mock_gemini_engine = Mock()
        mock_gemini_engine.research_company.return_value = fresh_result
        mock_get_gemini_engine.return_value = mock_gemini_engine

        record = _company()
        rp._research_one_company(record, rp.PROVIDER_GEMINI, "proc-session", None)

        mock_cache.store_cache.assert_called_once_with(
            record, fresh_result, provider=rp.PROVIDER_GEMINI
        )


class TestResumeProcessingLogic:
    """
    Unit tests for the new resume_processing function and related functionality.
    
    **Validates: Requirements 6.3, 6.4**
    """

    def setup_method(self):
        rp.clear_state()

    def teardown_method(self):
        rp.clear_state()

    @patch.object(rp, "_create_db_session")
    def test_resume_stopped_session_success(self, mock_create_db):
        """Test successful resume of a stopped session."""
        companies = [_company("Resume1"), _company("Resume2")]
        rp.start_new_batch(companies, "resume-session", rp.PROVIDER_OPENAI)
        
        state = rp.get_current_state()
        state.status = "stopped"
        state.current_index = 1  # Simulate partial processing
        
        success = rp.resume_processing("resume-session")
        assert success is True
        assert state.status == "running"
        
    def test_resume_nonexistent_session_failure(self):
        """Test that resuming a non-existent session fails gracefully."""
        rp.clear_state()
        success = rp.resume_processing("non-existent")
        assert success is False
        
    @patch.object(rp, "_create_db_session")
    def test_resume_running_session_failure(self, mock_create_db):
        """Test that attempting to resume when already running fails."""
        companies = [_company("Running1")]
        rp.start_new_batch(companies, "running-session", rp.PROVIDER_OPENAI)
        
        state = rp.get_current_state()
        assert state.status == "running"
        
        success = rp.resume_processing("different-session")
        assert success is False
        
    @patch.object(rp, "_create_db_session")
    def test_resume_completed_session_failure(self, mock_create_db):
        """Test that resuming a completed session fails."""
        companies = [_company("Completed1")]
        rp.start_new_batch(companies, "completed-session", rp.PROVIDER_OPENAI)
        
        state = rp.get_current_state()
        state.status = "completed"
        
        success = rp.resume_processing("completed-session")
        assert success is False
        assert state.status == "completed"


class TestRenderProcessorControlFlow:
    """
    Exercises render_processor's branching logic with Streamlit and the DB
    helpers mocked out, since this function is UI glue around the already
    independently-tested _research_one_company/_process_chunk state machinery.

    render_processor's body now also calls st.markdown, st.metric (7x),
    st.caption, st.dataframe (via _render_live_table), st.success, and
    st.warning/st.error in various branches -- all are mocked here so the
    tests run outside Streamlit's script context without raising.
    """

    def setup_method(self):
        rp.clear_state()

    def teardown_method(self):
        rp.clear_state()

    def _mock_columns(self, n):
        # Handle both integer (range) and list (column widths) cases
        if isinstance(n, list):
            return [MagicMock() for _ in range(len(n))]
        return [MagicMock() for _ in range(n)]

    @patch.object(rp, "_complete_db_session")
    @patch.object(rp, "_update_db_progress")
    @patch.object(rp.st, "dataframe")
    @patch.object(rp.st, "success")
    @patch.object(rp.st, "markdown")
    @patch.object(rp.st, "warning")
    @patch.object(rp.st, "caption")
    @patch.object(rp.st, "button")
    @patch.object(rp.st, "progress")
    @patch.object(rp.st, "columns")
    def test_stopped_state_shows_resume_button(
        self, mock_columns, mock_progress, mock_button, mock_caption, mock_warning,
        mock_markdown, mock_success, mock_dataframe, mock_update_db, mock_complete_db
    ):
        """Test that stopped state displays resume button in UI."""
        mock_columns.side_effect = lambda n: self._mock_columns(n)
        # Resume button is clicked (True)
        mock_button.return_value = True

        state = rp.ProcessingState(session_id="s1", company_records=[_company(), _company("Beta")])
        state.status = "stopped"
        state.current_index = 1
        state.items.append(rp.ProcessedItem(_company(), _research_result(), is_cached=True))

        import streamlit as st
        st.session_state[rp.PROC_STATE_KEY] = state

        # Mock st.rerun to simulate resume triggering rerun
        with patch.object(rp.st, "rerun") as mock_rerun:
            mock_rerun.side_effect = RuntimeError("RERUN_CALLED")

            with pytest.raises(RuntimeError, match="RERUN_CALLED"):
                rp.render_processor()

        # Verify resume was successful and status changed
        assert state.status == "running"

    @patch.object(rp, "_complete_db_session")
    @patch.object(rp.st, "dataframe")
    @patch.object(rp.st, "markdown")
    @patch.object(rp.st, "warning")
    @patch.object(rp.st, "caption")
    @patch.object(rp.st, "button")
    @patch.object(rp.st, "progress")
    @patch.object(rp.st, "columns")
    def test_stop_button_halts_processing_and_preserves_items(
        self, mock_columns, mock_progress, mock_button, mock_caption, mock_warning,
        mock_markdown, mock_dataframe, mock_complete_db
    ):
        mock_columns.side_effect = lambda n: self._mock_columns(n)
        mock_button.return_value = True  # user clicked Stop

        state = rp.ProcessingState(session_id="s1", company_records=[_company(), _company("Beta")])
        state.items.append(rp.ProcessedItem(_company(), _research_result(), is_cached=True))
        state.current_index = 1
        import streamlit as st
        st.session_state[rp.PROC_STATE_KEY] = state

        result = rp.render_processor()

        assert result is state.items
        assert state.status == "stopped"
        mock_complete_db.assert_called_once_with(state, "stopped")

    @patch.object(rp, "_update_db_progress")
    @patch.object(rp, "get_cache_manager")
    @patch.object(rp.st, "dataframe")
    @patch.object(rp.st, "markdown")
    @patch.object(rp.st, "caption")
    @patch.object(rp.st, "rerun")
    @patch.object(rp.st, "button")
    @patch.object(rp.st, "progress")
    @patch.object(rp.st, "columns")
    def test_running_state_processes_one_company_chunk_and_reruns(
        self, mock_columns, mock_progress, mock_button, mock_rerun, mock_caption,
        mock_markdown, mock_dataframe, mock_get_cache_manager, mock_update_db
    ):
        """
        With state.chunk_size explicitly set to 1, render_processor's chunk
        processing should advance current_index by exactly one company per
        call -- preserving the original one-at-a-time control-flow intent
        even though the production default chunk_size is now 15.
        """
        mock_columns.side_effect = lambda n: self._mock_columns(n)
        mock_button.return_value = False  # stop not clicked
        mock_cache = Mock()
        mock_cache.lookup_cache.return_value = _research_result()
        mock_get_cache_manager.return_value = mock_cache

        # st.rerun() should halt the script in real Streamlit; simulate that
        # by raising, so we can assert it was reached without continuing
        # into code that would only run after a successful rerun.
        mock_rerun.side_effect = RuntimeError("RERUN_CALLED")

        state = rp.ProcessingState(session_id="s1", company_records=[_company(), _company("Beta")])
        state.chunk_size = 1
        import streamlit as st
        st.session_state[rp.PROC_STATE_KEY] = state

        with pytest.raises(RuntimeError, match="RERUN_CALLED"):
            rp.render_processor()

        assert state.current_index == 1  # one company was processed before rerun
        mock_rerun.assert_called_once()

    @patch.object(rp, "_update_db_progress")
    @patch.object(rp, "get_cache_manager")
    @patch.object(rp.st, "dataframe")
    @patch.object(rp.st, "markdown")
    @patch.object(rp.st, "caption")
    @patch.object(rp.st, "rerun")
    @patch.object(rp.st, "button")
    @patch.object(rp.st, "progress")
    @patch.object(rp.st, "columns")
    def test_running_state_processes_up_to_chunk_size_companies_per_call(
        self, mock_columns, mock_progress, mock_button, mock_rerun, mock_caption,
        mock_markdown, mock_dataframe, mock_get_cache_manager, mock_update_db
    ):
        """
        With more un-processed companies than the chunk size, a single
        render_processor call should advance current_index by exactly
        chunk_size (not 1, and not the whole remaining batch) -- this is
        the core behavior change from the old one-company-per-rerun design.
        """
        mock_columns.side_effect = lambda n: self._mock_columns(n)
        mock_button.return_value = False  # stop not clicked
        mock_cache = Mock()
        mock_cache.lookup_cache.return_value = _research_result()
        mock_get_cache_manager.return_value = mock_cache
        mock_rerun.side_effect = RuntimeError("RERUN_CALLED")

        records = [_company(f"Co{i}", row_index=i) for i in range(5)]
        state = rp.ProcessingState(session_id="s1", company_records=records)
        state.chunk_size = 2
        import streamlit as st
        st.session_state[rp.PROC_STATE_KEY] = state

        with pytest.raises(RuntimeError, match="RERUN_CALLED"):
            rp.render_processor()

        assert state.current_index == 2
        assert len(state.items) == 2

    @patch.object(rp, "_complete_db_session")
    @patch.object(rp.st, "dataframe")
    @patch.object(rp.st, "markdown")
    @patch.object(rp.st, "success")
    @patch.object(rp.st, "button")
    @patch.object(rp.st, "progress")
    @patch.object(rp.st, "columns")
    def test_completion_when_all_companies_processed(
        self, mock_columns, mock_progress, mock_button, mock_success,
        mock_markdown, mock_dataframe, mock_complete_db
    ):
        mock_columns.side_effect = lambda n: self._mock_columns(n)
        mock_button.return_value = False  # stop not clicked

        records = [_company()]
        state = rp.ProcessingState(session_id="s1", company_records=records)
        state.items.append(rp.ProcessedItem(records[0], _research_result(), is_cached=False))
        state.current_index = 1  # already processed the only company
        import streamlit as st
        st.session_state[rp.PROC_STATE_KEY] = state

        result = rp.render_processor()

        assert result is state.items
        assert state.status == "completed"
        mock_complete_db.assert_called_once_with(state, "completed")

    @patch.object(rp.st, "dataframe")
    @patch.object(rp.st, "markdown")
    @patch.object(rp.st, "progress")
    @patch.object(rp.st, "columns")
    def test_already_stopped_state_returns_items_without_reprocessing(
        self, mock_columns, mock_progress, mock_markdown, mock_dataframe
    ):
        mock_columns.side_effect = lambda n: self._mock_columns(n)

        records = [_company(), _company("Beta")]
        state = rp.ProcessingState(session_id="s1", company_records=records, status="stopped")
        state.current_index = 1
        state.items.append(rp.ProcessedItem(records[0], _research_result(), is_cached=True))
        import streamlit as st
        st.session_state[rp.PROC_STATE_KEY] = state

        with patch.object(rp.st, "warning"), patch.object(rp.st, "button", return_value=False), \
             patch.object(rp.st, "caption"):
            result = rp.render_processor()

        assert result is state.items
        assert state.current_index == 1  # unchanged -- no further processing

    def test_no_active_state_returns_none(self):
        import streamlit as st
        st.session_state.pop(rp.PROC_STATE_KEY, None)
        assert rp.render_processor() is None
