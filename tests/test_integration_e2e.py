"""
End-to-end integration tests covering full cross-component workflows.

Unlike the rest of the test suite (which tests one module's properties or
units in isolation), these tests wire several real modules together --
exactly the way main.py does -- with only the true external boundaries
(Streamlit's runtime, the database, and the AI research engines) mocked.

Workflows covered:
  1. Login -> CSV upload/validation -> column detection -> normalization ->
     sequential processing -> results table -> CSV/Excel export.
  2. Error/recovery: one company's research call fails mid-batch; the batch
     must isolate that failure (Property 19) and still complete the
     remaining companies and produce a correct, complete export.

**Validates: Requirements 1.2, 1.3, 5.1-5.5, 6.1-6.5, 7.1-7.5, 8.1-8.5, 10.4**
"""

import io
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import Mock, patch
import uuid

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

import pandas as pd
import pytest

from src.utils.security import hash_passcode
from src.models.schemas import User
from src.components.authentication import SessionManager, SessionInfo
from src.utils.validation import (
    detect_company_columns,
    read_csv_with_fallback_encoding,
    validate_csv_structure,
    validate_selected_columns,
)
from src.core.normalization import create_company_record_with_normalization
from src.components.results_processor import (
    PROVIDER_OPENAI,
    ProcessedItem,
    ResearchEngineError,
    clear_state,
    get_current_state,
    start_new_batch,
    _process_one,
)
from src.models.entities import ResearchResult
from src.components.results_display import _item_to_row
from src.core.export_manager import export_to_csv_bytes, export_to_excel_bytes


SAMPLE_CSV = b"""Company Name,Website
Acme Corp,acme.com
Globex Inc,globex.com
Initech,initech.io
"""


class _MockCacheManager:
    """Always misses cache -- forces every company through the engine."""

    def lookup_cache(self, normalized_key):
        return None

    def store_cache(self, company_record, result, provider="openai"):
        return True


class _MockResearchEngine:
    """Returns a deterministic, distinguishable result per company name."""

    def __init__(self, failing_company: str = None):
        self.failing_company = failing_company
        self.calls = []

    def research_company(self, name, domain, session_id):
        self.calls.append(name)
        if self.failing_company and name == self.failing_company:
            raise ResearchEngineError(f"simulated failure researching {name}")
        return ResearchResult(
            company_name=name,
            company_domain=domain,
            gcc_presence=True,
            gcc_location="Bengaluru",
            suitability_score=8,
            business_pain_points=["Scaling support team"],
            expansion_indicators=["New India office"],
            hiring_signals=["10 open roles"],
            research_summary=f"{name} is a strong GCC candidate.",
            is_cached=False,
            created_at=datetime.now(timezone.utc),
        )


@pytest.fixture(autouse=True)
def _clean_processing_state():
    clear_state()
    yield
    clear_state()


class TestLoginToExportWorkflow:
    """Workflow 1: login -> upload -> process -> results -> export."""

    def _authenticated_session_manager(self, passcode="correct-horse-battery"):
        """Build a SessionManager backed by a mocked DB containing one real
        (bcrypt-hashed) user, and authenticate with the matching passcode."""
        hashed = hash_passcode(passcode)
        user = User(id=1, passcode=hashed, is_active=True)

        mock_session = Mock()
        mock_session.query.return_value.filter.return_value.all.return_value = [user]
        mock_session.query.return_value.filter.return_value.first.return_value = user
        mock_session.commit.return_value = None

        @contextmanager
        def get_session():
            yield mock_session

        mock_db_manager = Mock()
        mock_db_manager.get_session = get_session

        session_state = {}
        with patch('src.components.authentication.db_manager', mock_db_manager), \
             patch('src.components.authentication.get_config') as mock_config, \
             patch('streamlit.session_state', session_state):
            mock_app_config = Mock()
            mock_app_config.session_timeout_hours = 24
            mock_config.return_value.app = mock_app_config

            manager = SessionManager()
            authenticated = manager.authenticate_user(passcode)
            assert authenticated is True, "Login step of the workflow must succeed"
            assert manager.is_authenticated() is True
        return manager, session_state

    def test_full_workflow_login_upload_process_results_export(self):
        # Step 1: login.
        manager, session_state = self._authenticated_session_manager()

        # Step 2: upload + validate CSV.
        df = read_csv_with_fallback_encoding(io.BytesIO(SAMPLE_CSV))
        structure_errors = validate_csv_structure(df)
        assert structure_errors == [], f"Sample CSV should be structurally valid: {structure_errors}"

        # Step 3: column auto-detection + selection validation.
        detection = detect_company_columns(df)
        assert detection.name_column == "Company Name"
        assert detection.domain_column == "Website"
        selection_result = validate_selected_columns(df, detection.name_column, detection.domain_column)
        assert selection_result.is_valid, \
            f"Auto-detected columns should be valid: {selection_result.errors}"

        # Step 4: build normalized CompanyRecords from validated rows.
        company_records = []
        for idx, row in df.iterrows():
            record = create_company_record_with_normalization(
                name=row[detection.name_column],
                domain=row.get(detection.domain_column),
                row_index=idx,
            )
            company_records.append(record)
        assert len(company_records) == 3

        # Step 5: sequential processing with mocked engine/cache.
        mock_engine = _MockResearchEngine()
        mock_cache = _MockCacheManager()
        session_id = str(uuid.uuid4())

        with patch('streamlit.session_state', session_state):
            start_new_batch(company_records, session_id, PROVIDER_OPENAI)
            state = get_current_state()
            with patch('src.components.results_processor.get_research_engine', return_value=mock_engine), \
                 patch('src.components.results_processor.get_cache_manager', return_value=mock_cache), \
                 patch('src.components.results_processor.db_manager'):
                while state.current_index < len(company_records):
                    _process_one(state, user_session_id="test-session")

        assert state.status != "stopped"
        assert len(state.items) == 3
        assert state.errors == 0
        assert {c for c in mock_engine.calls} == {"Acme Corp", "Globex Inc", "Initech"}

        # Step 6: results table rows.
        rows = [_item_to_row(item) for item in state.items]
        assert {r["company_name"] for r in rows} == {"Acme Corp", "Globex Inc", "Initech"}
        assert all(r["suitability_score"] == 8 for r in rows)
        assert all(r["error"] is None for r in rows)

        # Step 7: export to CSV and Excel; verify no data loss end-to-end.
        csv_bytes = export_to_csv_bytes(rows)
        csv_text = csv_bytes.decode("utf-8-sig")
        for name in ("Acme Corp", "Globex Inc", "Initech"):
            assert name in csv_text, f"Exported CSV should contain {name}"
        assert "Bengaluru" in csv_text

        excel_bytes = export_to_excel_bytes(rows)
        roundtrip_df = pd.read_excel(io.BytesIO(excel_bytes))
        assert set(roundtrip_df["Company Name"]) == {"Acme Corp", "Globex Inc", "Initech"}
        assert set(roundtrip_df["Suitability Score"]) == {8}


class TestErrorRecoveryWorkflow:
    """Workflow 2: a mid-batch failure must isolate (Property 19) and the
    workflow must still complete with a correct, complete export."""

    def test_one_company_failure_does_not_abort_batch_or_corrupt_export(self):
        manager, session_state = TestLoginToExportWorkflow()._authenticated_session_manager()

        df = read_csv_with_fallback_encoding(io.BytesIO(SAMPLE_CSV))
        detection = detect_company_columns(df)
        company_records = [
            create_company_record_with_normalization(
                name=row[detection.name_column],
                domain=row.get(detection.domain_column),
                row_index=idx,
            )
            for idx, row in df.iterrows()
        ]

        mock_engine = _MockResearchEngine(failing_company="Globex Inc")
        mock_cache = _MockCacheManager()
        session_id = str(uuid.uuid4())

        with patch('streamlit.session_state', session_state):
            start_new_batch(company_records, session_id, PROVIDER_OPENAI)
            state = get_current_state()
            with patch('src.components.results_processor.get_research_engine', return_value=mock_engine), \
                 patch('src.components.results_processor.get_cache_manager', return_value=mock_cache), \
                 patch('src.components.results_processor.db_manager'):
                while state.current_index < len(company_records):
                    _process_one(state, user_session_id="test-session")

        # All three companies were attempted despite the failure.
        assert len(state.items) == 3
        assert state.errors == 1
        assert {c for c in mock_engine.calls} == {"Acme Corp", "Globex Inc", "Initech"}

        failed_items = [i for i in state.items if i.error is not None]
        succeeded_items = [i for i in state.items if i.error is None]
        assert len(failed_items) == 1
        assert failed_items[0].company_record.name == "Globex Inc"
        assert len(succeeded_items) == 2

        rows = [_item_to_row(item) for item in state.items]
        globex_row = next(r for r in rows if r["company_name"] == "Globex Inc")
        assert globex_row["error"] is not None
        assert globex_row["suitability_score"] is None

        other_rows = [r for r in rows if r["company_name"] != "Globex Inc"]
        assert all(r["error"] is None and r["suitability_score"] == 8 for r in other_rows)

        # The export must still include every row -- failures are surfaced,
        # not dropped.
        csv_text = export_to_csv_bytes(rows).decode("utf-8-sig")
        assert "Acme Corp" in csv_text
        assert "Globex Inc" in csv_text
        assert "Initech" in csv_text
        assert "simulated failure researching Globex Inc" in csv_text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
