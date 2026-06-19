"""
Unit tests for the history page's pure data-transformation logic: parsing
stored text-array fields and flattening DB result rows for display/export.

The paginated Streamlit rendering itself is glue around already-tested
repository search and export_manager functions, so it isn't re-tested here.

**Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5**
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from datetime import datetime, timezone
from types import SimpleNamespace

from src.components.history import _db_result_to_row, _parse_text_array


class TestParseTextArray:
    def test_none_returns_empty_list(self):
        assert _parse_text_array(None) == []

    def test_empty_string_returns_empty_list(self):
        assert _parse_text_array("") == []

    def test_json_array_string_is_parsed(self):
        assert _parse_text_array('["High costs", "Talent shortage"]') == [
            "High costs",
            "Talent shortage",
        ]

    def test_comma_separated_string_is_split(self):
        assert _parse_text_array("High costs, Talent shortage") == [
            "High costs",
            "Talent shortage",
        ]

    def test_single_value_string_returns_single_item_list(self):
        assert _parse_text_array("High costs") == ["High costs"]

    def test_malformed_json_array_like_string_falls_back_gracefully(self):
        # Starts/ends like a JSON array (so it takes the json.loads branch)
        # but isn't valid JSON -- must not raise, and falls back to [].
        assert _parse_text_array("[not valid json]") == []

    def test_whitespace_only_string_returns_empty_list(self):
        assert _parse_text_array("   ") == []

    def test_comma_separated_with_blank_items_filters_them_out(self):
        assert _parse_text_array("High costs, , Talent shortage") == [
            "High costs",
            "Talent shortage",
        ]


class TestDbResultToRow:
    def _make_db_result(self, **overrides):
        defaults = dict(
            company_name="Acme Inc",
            company_domain="acme.com",
            gcc_presence=True,
            gcc_location="Pune, India",
            suitability_score=7,
            business_pain_points='["High costs"]',
            expansion_indicators='["New funding"]',
            hiring_signals="Active job postings",
            research_summary="Solid candidate.",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def test_flattens_all_fields(self):
        db_result = self._make_db_result()
        row = _db_result_to_row(db_result)

        assert row["company_name"] == "Acme Inc"
        assert row["gcc_presence"] is True
        assert row["suitability_score"] == 7
        assert row["is_cached"] is True
        assert row["error"] is None

    def test_text_array_fields_are_parsed_into_lists(self):
        db_result = self._make_db_result()
        row = _db_result_to_row(db_result)

        assert row["business_pain_points"] == ["High costs"]
        assert row["expansion_indicators"] == ["New funding"]
        assert row["hiring_signals"] == ["Active job postings"]

    def test_preserves_both_timestamps(self):
        db_result = self._make_db_result()
        row = _db_result_to_row(db_result)

        assert row["created_at"] == db_result.created_at
        assert row["updated_at"] == db_result.updated_at

    def test_none_text_array_fields_become_empty_lists(self):
        db_result = self._make_db_result(
            business_pain_points=None, expansion_indicators=None, hiring_signals=None
        )
        row = _db_result_to_row(db_result)

        assert row["business_pain_points"] == []
        assert row["expansion_indicators"] == []
        assert row["hiring_signals"] == []
