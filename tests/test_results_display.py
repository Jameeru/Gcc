"""
Unit tests for the results display component's pure data-transformation
logic: flattening ProcessedItem rows and filtering (Property 14).

The Streamlit rendering portion of render_results_table is thin glue over
these already-tested functions and over export_manager (covered in
test_export_manager.py), so it isn't separately re-tested here.

**Validates: Requirements 7.1, 7.2, 7.5 -- Property 14: Filtering Accuracy**
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from datetime import datetime, timezone

import pandas as pd
import pytest

from src.components.results_display import _apply_filters, _item_to_row
from src.components.results_processor import ProcessedItem
from src.models.entities import CompanyRecord, ResearchResult


def _company(name="Acme Inc", domain="acme.com"):
    return CompanyRecord(name=name, domain=domain, normalized_key=f"{name}_{domain}", row_index=0)


def _result(**overrides):
    defaults = dict(
        company_name="Acme Inc",
        company_domain="acme.com",
        gcc_presence=True,
        gcc_location="Chennai, India",
        suitability_score=7,
        business_pain_points=["Cost pressure"],
        expansion_indicators=["Growth"],
        hiring_signals=["Hiring"],
        research_summary="Promising fintech expanding into India.",
        is_cached=False,
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return ResearchResult(**defaults)


class TestItemToRow:
    def test_successful_item_pulls_all_research_fields(self):
        item = ProcessedItem(company_record=_company(), research_result=_result(), is_cached=True)
        row = _item_to_row(item)

        assert row["company_name"] == "Acme Inc"
        assert row["gcc_presence"] is True
        assert row["suitability_score"] == 7
        assert row["is_cached"] is True
        assert row["error"] is None

    def test_failed_item_still_produces_a_visible_row(self):
        """Requirement 7.5 / Property 19: failed companies must still appear
        as a row (with null research fields) rather than being dropped."""
        item = ProcessedItem(
            company_record=_company("Failed Co"),
            research_result=None,
            is_cached=False,
            error="OpenAI API call failed after 3 attempts",
        )
        row = _item_to_row(item)

        assert row["company_name"] == "Failed Co"
        assert row["gcc_presence"] is None
        assert row["suitability_score"] is None
        assert row["error"] == "OpenAI API call failed after 3 attempts"

    def test_failed_item_with_no_error_message_gets_fallback_text(self):
        item = ProcessedItem(company_record=_company(), research_result=None, is_cached=False, error=None)
        row = _item_to_row(item)
        assert row["error"] == "Unknown error"


class TestApplyFilters:
    def _df(self):
        rows = [
            {
                "company_name": "Acme Fintech",
                "company_domain": "acme.com",
                "gcc_presence": True,
                "suitability_score": 9,
                "research_summary": "Strong India presence already.",
                "error": None,
            },
            {
                "company_name": "Beta Retail",
                "company_domain": "beta.com",
                "gcc_presence": False,
                "suitability_score": 4,
                "research_summary": "No current GCC plans.",
                "error": None,
            },
            {
                "company_name": "Gamma Corp",
                "company_domain": "gamma.com",
                "gcc_presence": None,
                "suitability_score": None,
                "research_summary": None,
                "error": "Timed out",
            },
        ]
        return pd.DataFrame(rows)

    def test_no_filters_returns_all_rows(self):
        result = _apply_filters(self._df(), "", "All", (1, 10), False)
        assert len(result) == 3

    def test_search_term_matches_company_name_case_insensitive(self):
        result = _apply_filters(self._df(), "acme", "All", (1, 10), False)
        assert list(result["company_name"]) == ["Acme Fintech"]

    def test_search_term_matches_research_summary(self):
        result = _apply_filters(self._df(), "india presence", "All", (1, 10), False)
        assert list(result["company_name"]) == ["Acme Fintech"]

    def test_search_term_matches_domain(self):
        result = _apply_filters(self._df(), "beta.com", "All", (1, 10), False)
        assert list(result["company_name"]) == ["Beta Retail"]

    def test_gcc_filter_has_gcc(self):
        result = _apply_filters(self._df(), "", "Has GCC", (1, 10), False)
        assert list(result["company_name"]) == ["Acme Fintech"]

    def test_gcc_filter_no_gcc(self):
        result = _apply_filters(self._df(), "", "No GCC", (1, 10), False)
        assert list(result["company_name"]) == ["Beta Retail"]

    def test_score_range_filter_excludes_out_of_range_but_keeps_null(self):
        result = _apply_filters(self._df(), "", "All", (5, 10), False)
        # Acme (9) is in-range; Beta (4) is excluded; Gamma (null score) is
        # kept since a failed/unscored row shouldn't be hidden by a score filter.
        assert set(result["company_name"]) == {"Acme Fintech", "Gamma Corp"}

    def test_errors_only_filter(self):
        result = _apply_filters(self._df(), "", "All", (1, 10), True)
        assert list(result["company_name"]) == ["Gamma Corp"]

    def test_combined_filters(self):
        result = _apply_filters(self._df(), "fintech", "Has GCC", (8, 10), False)
        assert list(result["company_name"]) == ["Acme Fintech"]

    def test_no_matches_returns_empty_dataframe(self):
        result = _apply_filters(self._df(), "nonexistent company", "All", (1, 10), False)
        assert len(result) == 0
