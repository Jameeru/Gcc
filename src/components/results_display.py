"""
Results display component for the GCC Research Intelligence Platform.

Renders an interactive, searchable, filterable, sortable table of the
current batch's research results, with cache-hit/error indicators and
CSV/Excel export controls.

**Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 8.1, 8.2, 8.3, 8.4, 8.5**
"""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from ..core.export_manager import (
    export_to_csv_bytes,
    export_to_excel_bytes,
    generate_export_filename,
)
from .results_processor import ProcessedItem

SORT_COLUMNS = {
    "Company Name": "company_name",
    "Suitability Score": "suitability_score",
    "GCC Presence": "gcc_presence",
    "Researched At": "created_at",
}


def _item_to_row(item: ProcessedItem) -> Dict[str, Any]:
    """Flatten a ProcessedItem into a plain dict row for display/export."""
    record = item.company_record
    result = item.research_result

    if result is not None:
        return {
            "company_name": result.company_name,
            "company_domain": result.company_domain,
            "gcc_presence": result.gcc_presence,
            "gcc_location": result.gcc_location,
            "suitability_score": result.suitability_score,
            "business_pain_points": result.business_pain_points,
            "expansion_indicators": result.expansion_indicators,
            "hiring_signals": result.hiring_signals,
            "research_summary": result.research_summary,
            "is_cached": item.is_cached,
            "error": None,
            "created_at": result.created_at,
        }

    # Research failed for this company -- still surfaced as a row so the
    # user knows it needs attention, per Requirements 7.5 and Property 19.
    return {
        "company_name": record.name,
        "company_domain": record.domain,
        "gcc_presence": None,
        "gcc_location": None,
        "suitability_score": None,
        "business_pain_points": [],
        "expansion_indicators": [],
        "hiring_signals": [],
        "research_summary": None,
        "is_cached": False,
        "error": item.error or "Unknown error",
        "created_at": None,
    }


def _apply_filters(
    df: pd.DataFrame,
    search_term: str,
    gcc_filter: str,
    score_range: tuple,
    show_errors_only: bool,
) -> pd.DataFrame:
    """
    Apply search/filter criteria to the results DataFrame.

    **Validates: Requirements 7.2 — Property 14: Filtering Accuracy**
    """
    filtered = df

    if show_errors_only:
        filtered = filtered[filtered["error"].notna()]

    if search_term:
        term = search_term.lower()
        mask = (
            filtered["company_name"].fillna("").str.lower().str.contains(term)
            | filtered["company_domain"].fillna("").str.lower().str.contains(term)
            | filtered["research_summary"].fillna("").str.lower().str.contains(term)
        )
        filtered = filtered[mask]

    if gcc_filter == "Has GCC":
        filtered = filtered[filtered["gcc_presence"] == True]  # noqa: E712
    elif gcc_filter == "No GCC":
        filtered = filtered[filtered["gcc_presence"] == False]  # noqa: E712

    min_score, max_score = score_range
    filtered = filtered[
        filtered["suitability_score"].isna()
        | filtered["suitability_score"].between(min_score, max_score)
    ]

    return filtered


def render_results_table(items: List[ProcessedItem]) -> None:
    """
    Render the full results view: search/filter controls, sortable table,
    cache-hit indicators, and export buttons.

    **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 8.1, 8.2, 8.3, 8.4, 8.5**
    """
    if not items:
        st.info("No results to display yet. Upload a file and start processing.")
        return

    rows = [_item_to_row(item) for item in items]
    df = pd.DataFrame(rows)

    st.markdown("#### 🔍 Search & Filter")
    col1, col2, col3 = st.columns([2, 1, 1])

    with col1:
        search_term = st.text_input(
            "Search company, domain, or summary",
            key="gcc_results_search",
            placeholder="e.g. Microsoft, fintech, hiring...",
        )

    with col2:
        gcc_filter = st.selectbox(
            "GCC Status", options=["All", "Has GCC", "No GCC"], key="gcc_results_gcc_filter"
        )

    with col3:
        show_errors_only = st.checkbox("Errors only", key="gcc_results_errors_only")

    score_range = st.slider(
        "Suitability Score Range", min_value=1, max_value=10, value=(1, 10), key="gcc_results_score_range"
    )

    filtered_df = _apply_filters(df, search_term, gcc_filter, score_range, show_errors_only)

    st.markdown("#### 📊 Sort")
    sort_col1, sort_col2 = st.columns(2)
    with sort_col1:
        sort_label = st.selectbox("Sort by", options=list(SORT_COLUMNS.keys()), key="gcc_results_sort_col")
    with sort_col2:
        sort_direction = st.radio(
            "Direction", options=["Descending", "Ascending"], horizontal=True, key="gcc_results_sort_dir"
        )

    sort_column = SORT_COLUMNS[sort_label]
    ascending = sort_direction == "Ascending"
    if sort_column in filtered_df.columns:
        filtered_df = filtered_df.sort_values(
            by=sort_column, ascending=ascending, na_position="last"
        )

    st.caption(f"Showing {len(filtered_df)} of {len(df)} results")

    display_df = filtered_df.copy()
    display_df.insert(
        0,
        "Status",
        display_df.apply(
            lambda r: "⚠️ Error" if pd.notna(r["error"]) else ("💾 Cached" if r["is_cached"] else "✨ New"),
            axis=1,
        ),
    )
    display_df = display_df.rename(
        columns={
            "company_name": "Company",
            "company_domain": "Domain",
            "gcc_presence": "GCC Presence",
            "gcc_location": "GCC Location",
            "suitability_score": "Score",
            "research_summary": "Summary",
            "error": "Error",
        }
    )
    display_columns = [
        "Status",
        "Company",
        "Domain",
        "GCC Presence",
        "GCC Location",
        "Score",
        "Summary",
        "Error",
    ]
    st.dataframe(display_df[display_columns], width='stretch', hide_index=True)

    st.markdown("#### 📤 Export")
    export_rows = filtered_df.to_dict(orient="records")
    exp_col1, exp_col2 = st.columns(2)

    with exp_col1:
        csv_bytes = export_to_csv_bytes(export_rows)
        st.download_button(
            "⬇️ Download CSV",
            data=csv_bytes,
            file_name=generate_export_filename("gcc_research_results", "csv"),
            mime="text/csv",
            width='stretch',
        )

    with exp_col2:
        excel_bytes = export_to_excel_bytes(export_rows)
        st.download_button(
            "⬇️ Download Excel",
            data=excel_bytes,
            file_name=generate_export_filename("gcc_research_results", "xlsx"),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width='stretch',
        )
