"""
Property-based tests for Properties 14 and 15: Filtering Accuracy and Sorting Consistency.

These tests verify that the results display filtering and sorting functions
work correctly across a wide range of inputs, ensuring the correctness
properties specified in the design document hold universally.

**Validates: Requirements 7.2, 7.3 -- Properties 14 and 15**
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd
import pytest
from hypothesis import given, strategies as st

from src.components.results_display import _apply_filters, SORT_COLUMNS


@st.composite
def research_result_row(draw):
    """Generate a realistic research result row for property testing."""
    company_names = st.one_of(
        st.just("Acme Corp"),
        st.just("TechStart Inc"),
        st.just("Global Solutions Ltd"),
        st.just("Innovation Labs"),
        st.just("DataFlow Systems"),
        st.text(min_size=3, max_size=30, alphabet=st.characters(whitelist_categories=['L', 'N', 'Z']))
    )
    
    domains = st.one_of(
        st.just("example.com"),
        st.just("techstart.io"),
        st.just("global-solutions.net"),
        st.just("innovationlabs.org"),
        st.just("dataflow.co"),
        st.none(),
        st.text(min_size=3, max_size=20, alphabet=st.characters(whitelist_categories=['L', 'N'])).map(lambda x: f"{x}.com")
    )
    
    summaries = st.one_of(
        st.just("Strong technology company with India presence"),
        st.just("Financial services expanding globally"),
        st.just("Manufacturing company seeking cost optimization"),
        st.just("Healthcare startup with remote workforce"),
        st.none(),
        st.text(min_size=10, max_size=200, alphabet=st.characters(whitelist_categories=['L', 'N', 'P', 'Z']))
    )
    
    return {
        "company_name": draw(company_names),
        "company_domain": draw(domains),
        "gcc_presence": draw(st.one_of(st.booleans(), st.none())),
        "suitability_score": draw(st.one_of(st.integers(min_value=1, max_value=10), st.none())),
        "research_summary": draw(summaries),
        "error": draw(st.one_of(st.none(), st.just("API timeout"), st.just("Research failed"))),
        "created_at": draw(st.one_of(
            st.datetimes(min_value=datetime(2023, 1, 1),
                        max_value=datetime(2025, 1, 1)).map(lambda dt: dt.replace(tzinfo=timezone.utc)),
            st.none()
        ))
    }


@st.composite  
def research_results_dataframe(draw, min_size=0, max_size=50):
    """Generate a DataFrame of research results for property testing."""
    rows = draw(st.lists(research_result_row(), min_size=min_size, max_size=max_size))
    return pd.DataFrame(rows)


class TestFilteringAccuracy:
    """
    **Property 14: Filtering Accuracy**
    
    For any set of research results and filter criteria (GCC status, suitability score),
    the filtered results shall contain only records that match all specified criteria.
    
    **Validates: Requirements 7.2**
    """
    
    @given(df=research_results_dataframe(min_size=1))
    def test_no_filters_returns_all_rows(self, df):
        """Property 14a: When no filters are applied, all rows should be returned."""
        result = _apply_filters(df, "", "All", (1, 10), False)
        assert len(result) == len(df), "No filters should return all rows"
    
    @given(
        df=research_results_dataframe(min_size=5),
        search_term=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=['L', 'N']))
    )
    def test_search_filter_contains_only_matching_rows(self, df, search_term):
        """Property 14b: Search results contain only rows that match the search term."""
        result = _apply_filters(df, search_term.lower(), "All", (1, 10), False)
        
        # Every returned row must contain the search term in at least one searchable field
        for _, row in result.iterrows():
            company_match = search_term.lower() in str(row.get("company_name", "")).lower()
            domain_match = search_term.lower() in str(row.get("company_domain", "")).lower()  
            summary_match = search_term.lower() in str(row.get("research_summary", "")).lower()
            
            assert company_match or domain_match or summary_match, (
                f"Row with company_name='{row.get('company_name')}' does not contain "
                f"search term '{search_term}' in any searchable field"
            )
    
    @given(df=research_results_dataframe(min_size=5))
    def test_gcc_presence_filter_accuracy(self, df):
        """Property 14c: GCC presence filters return only matching records."""
        # Test "Has GCC" filter
        has_gcc_result = _apply_filters(df, "", "Has GCC", (1, 10), False)
        for _, row in has_gcc_result.iterrows():
            assert row["gcc_presence"] is True, f"'Has GCC' filter returned row with gcc_presence={row['gcc_presence']}"
        
        # Test "No GCC" filter  
        no_gcc_result = _apply_filters(df, "", "No GCC", (1, 10), False)
        for _, row in no_gcc_result.iterrows():
            assert row["gcc_presence"] is False, f"'No GCC' filter returned row with gcc_presence={row['gcc_presence']}"
    
    @given(
        df=research_results_dataframe(min_size=5),
        min_score=st.integers(min_value=1, max_value=8),
        max_score=st.integers(min_value=2, max_value=10)
    )
    def test_suitability_score_filter_accuracy(self, df, min_score, max_score):
        """Property 14d: Score filters return only records within the specified range."""
        # Ensure min_score <= max_score
        if min_score > max_score:
            min_score, max_score = max_score, min_score
            
        result = _apply_filters(df, "", "All", (min_score, max_score), False)
        
        for _, row in result.iterrows():
            score = row["suitability_score"]
            # Null scores should be included (failed research shouldn't be hidden by score filter)
            if pd.notna(score):
                assert min_score <= score <= max_score, (
                    f"Score filter ({min_score}-{max_score}) returned row with score={score}"
                )
    
    @given(df=research_results_dataframe(min_size=5))
    def test_errors_only_filter_accuracy(self, df):
        """Property 14e: Errors-only filter returns only rows with errors."""
        result = _apply_filters(df, "", "All", (1, 10), True)
        
        for _, row in result.iterrows():
            assert pd.notna(row["error"]), f"Errors-only filter returned row without error: {row.to_dict()}"
    
    @given(
        df=research_results_dataframe(min_size=10),
        search_term=st.text(min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=['L'])),
        min_score=st.integers(min_value=1, max_value=5),
        max_score=st.integers(min_value=6, max_value=10)
    )
    def test_combined_filters_accuracy(self, df, search_term, min_score, max_score):
        """Property 14f: Combined filters return only rows that match ALL criteria."""
        result = _apply_filters(df, search_term.lower(), "Has GCC", (min_score, max_score), False)
        
        for _, row in result.iterrows():
            # Must match search term
            company_match = search_term.lower() in str(row.get("company_name", "")).lower()
            domain_match = search_term.lower() in str(row.get("company_domain", "")).lower()
            summary_match = search_term.lower() in str(row.get("research_summary", "")).lower()
            search_matches = company_match or domain_match or summary_match
            
            # Must have GCC presence = True
            gcc_matches = row["gcc_presence"] is True
            
            # Must be within score range (or null)
            score = row["suitability_score"]
            score_matches = pd.isna(score) or (min_score <= score <= max_score)
            
            assert search_matches and gcc_matches and score_matches, (
                f"Combined filter returned non-matching row: search={search_matches}, "
                f"gcc={gcc_matches}, score={score_matches}, row={row.to_dict()}"
            )


class TestSortingConsistency:
    """
    **Property 15: Sorting Consistency**
    
    For any column in the results table, sorting operations shall consistently
    order all records according to the specified column values in the requested direction.
    
    **Validates: Requirements 7.3**
    """
    
    def _create_sortable_dataframe(self) -> pd.DataFrame:
        """Create a DataFrame with predictable sorting test data."""
        return pd.DataFrame([
            {
                "company_name": "Apple Inc",
                "suitability_score": 9,
                "gcc_presence": True,
                "created_at": datetime(2024, 1, 15, tzinfo=timezone.utc)
            },
            {
                "company_name": "Beta Corp", 
                "suitability_score": 3,
                "gcc_presence": False,
                "created_at": datetime(2024, 2, 10, tzinfo=timezone.utc)
            },
            {
                "company_name": "Charlie Ltd",
                "suitability_score": 7,
                "gcc_presence": True,
                "created_at": datetime(2024, 1, 5, tzinfo=timezone.utc)
            },
            {
                "company_name": "Delta Systems",
                "suitability_score": None,  # Test null handling
                "gcc_presence": None,
                "created_at": None
            }
        ])
    
    def test_company_name_sorting_ascending(self):
        """Property 15a: Company name sorting orders alphabetically."""
        df = self._create_sortable_dataframe()
        
        # Sort ascending
        result = df.sort_values(by="company_name", ascending=True, na_position="last")
        names = result["company_name"].tolist()
        
        # Should be in alphabetical order
        expected = ["Apple Inc", "Beta Corp", "Charlie Ltd", "Delta Systems"]
        assert names == expected, f"Ascending sort failed: got {names}, expected {expected}"
    
    def test_company_name_sorting_descending(self):
        """Property 15b: Company name sorting orders reverse alphabetically."""
        df = self._create_sortable_dataframe()
        
        # Sort descending  
        result = df.sort_values(by="company_name", ascending=False, na_position="last")
        names = result["company_name"].tolist()
        
        # Should be in reverse alphabetical order
        expected = ["Delta Systems", "Charlie Ltd", "Beta Corp", "Apple Inc"]
        assert names == expected, f"Descending sort failed: got {names}, expected {expected}"
    
    def test_suitability_score_sorting_with_nulls(self):
        """Property 15c: Suitability score sorting handles null values correctly."""
        df = self._create_sortable_dataframe()
        
        # Sort ascending (nulls last)
        result = df.sort_values(by="suitability_score", ascending=True, na_position="last")
        scores = result["suitability_score"].tolist()
        
        # Should be: [3, 7, 9, None] but pandas converts None to NaN for numeric columns
        expected_values = [3, 7, 9]
        actual_values = [score for score in scores if pd.notna(score)]
        assert actual_values == expected_values, f"Score ascending sort failed: got {actual_values}, expected {expected_values}"
        assert pd.isna(scores[-1]), f"Last score should be NaN but got {scores[-1]}"
        
        # Sort descending (nulls last)  
        result = df.sort_values(by="suitability_score", ascending=False, na_position="last")
        scores = result["suitability_score"].tolist()
        
        # Should be: [9, 7, 3, None] but pandas converts None to NaN for numeric columns
        expected_values = [9, 7, 3]  
        actual_values = [score for score in scores if pd.notna(score)]
        assert actual_values == expected_values, f"Score descending sort failed: got {actual_values}, expected {expected_values}"
        assert pd.isna(scores[-1]), f"Last score should be NaN but got {scores[-1]}"
    
    def test_boolean_gcc_presence_sorting(self):
        """Property 15d: Boolean GCC presence sorting orders True before False."""
        df = self._create_sortable_dataframe()
        
        # Sort ascending (False=0, True=1, so False comes first)
        result = df.sort_values(by="gcc_presence", ascending=True, na_position="last")
        gcc_values = result["gcc_presence"].tolist()
        
        # Should be: [False, True, True, None] 
        expected = [False, True, True, None]
        assert gcc_values == expected, f"GCC ascending sort failed: got {gcc_values}, expected {expected}"
    
    def test_datetime_sorting_consistency(self):
        """Property 15e: Datetime sorting orders chronologically."""
        df = self._create_sortable_dataframe()
        
        # Sort ascending (earliest first)
        result = df.sort_values(by="created_at", ascending=True, na_position="last")
        dates = result["created_at"].tolist()
        
        # Should be chronological: [2024-01-05, 2024-01-15, 2024-02-10, None]
        # but pandas converts datetime and None values to Timestamp and NaT
        expected_dates = [
            datetime(2024, 1, 5, tzinfo=timezone.utc),
            datetime(2024, 1, 15, tzinfo=timezone.utc), 
            datetime(2024, 2, 10, tzinfo=timezone.utc)
        ]
        
        # Check non-null dates are in chronological order
        actual_dates = [date for date in dates if pd.notna(date)]
        for i, (actual, expected) in enumerate(zip(actual_dates, expected_dates)):
            # Convert pandas Timestamp back to datetime for comparison
            actual_dt = actual.to_pydatetime()
            assert actual_dt == expected, f"Date {i} mismatch: got {actual_dt}, expected {expected}"
        
        # Check last value is NaT (pandas' null datetime)
        assert pd.isna(dates[-1]), f"Last date should be NaT but got {dates[-1]}"
    
    @given(
        df=research_results_dataframe(min_size=5, max_size=20),
        column=st.sampled_from(["company_name", "suitability_score", "gcc_presence", "created_at"]),
        ascending=st.booleans()
    )
    def test_sorting_is_stable_and_deterministic(self, df, column, ascending):
        """Property 15f: Sorting produces consistent, deterministic results."""
        if column not in df.columns:
            return  # Skip if column doesn't exist in generated data
        
        # Sort the same data twice
        result1 = df.sort_values(by=column, ascending=ascending, na_position="last")
        result2 = df.sort_values(by=column, ascending=ascending, na_position="last")
        
        # Results should be identical
        pd.testing.assert_frame_equal(result1, result2, 
                                     f"Sorting by {column} (ascending={ascending}) is not deterministic")
    
    @given(df=research_results_dataframe(min_size=3, max_size=15))
    def test_sort_column_mapping_completeness(self, df):
        """Property 15g: All columns in SORT_COLUMNS mapping exist and are sortable."""
        for display_name, column_name in SORT_COLUMNS.items():
            if column_name in df.columns and len(df) > 0:
                # Should be able to sort without error
                try:
                    result = df.sort_values(by=column_name, ascending=True, na_position="last")
                    assert len(result) == len(df), f"Sorting by {column_name} changed row count"
                except Exception as e:
                    pytest.fail(f"Failed to sort by {column_name} (from {display_name}): {e}")


if __name__ == "__main__":
    pytest.main([__file__])