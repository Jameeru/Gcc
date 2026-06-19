"""
Historical research access page for the GCC Research Intelligence Platform.

Provides a paginated, searchable, date-range-filterable view over all
research results ever cached in the database (across all users), with
bulk export support.

**Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5, 8.1**
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timezone
from typing import Any, Dict, List, Optional

import streamlit as st

from ..core.database import db_manager
from ..core.export_manager import export_to_csv_bytes, export_to_excel_bytes, generate_export_filename
from ..models.repositories import ResearchResultRepository
from ..utils.logging import get_logger, log_event

logger = get_logger("history")

PAGE_SIZE_OPTIONS = [10, 25, 50, 100]


def _parse_text_array(text_value: Optional[str]) -> List[str]:
    """Parse the JSON/CSV text-array fields stored on ResearchResult rows."""
    if not text_value:
        return []
    try:
        if text_value.startswith("[") and text_value.endswith("]"):
            return json.loads(text_value)
        if "," in text_value:
            return [item.strip() for item in text_value.split(",") if item.strip()]
        return [text_value.strip()] if text_value.strip() else []
    except Exception:
        return []


def _db_result_to_row(db_result) -> Dict[str, Any]:
    return {
        "company_name": db_result.company_name,
        "company_domain": db_result.company_domain,
        "gcc_presence": db_result.gcc_presence,
        "gcc_location": db_result.gcc_location,
        "suitability_score": db_result.suitability_score,
        "business_pain_points": _parse_text_array(db_result.business_pain_points),
        "expansion_indicators": _parse_text_array(db_result.expansion_indicators),
        "hiring_signals": _parse_text_array(db_result.hiring_signals),
        "research_summary": db_result.research_summary,
        "is_cached": True,
        "error": None,
        "created_at": db_result.created_at,
        "updated_at": db_result.updated_at,
    }


def render_history_page() -> None:
    """
    Render the full history page: filters, paginated results table, and
    bulk export.

    **Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5**
    """
    st.title("📚 Research History")
    st.caption("Browse and search all previously researched companies across the platform.")

    if "gcc_history_page" not in st.session_state:
        st.session_state["gcc_history_page"] = 1

    st.markdown("#### 🔍 Search & Filter")
    col1, col2 = st.columns([2, 1])
    with col1:
        search_term = st.text_input(
            "Search by company name or domain",
            key="gcc_history_search",
            placeholder="e.g. Microsoft, microsoft.com...",
        )
    with col2:
        gcc_filter = st.selectbox(
            "GCC Status", options=["All", "Has GCC", "No GCC"], key="gcc_history_gcc_filter"
        )

    score_col, date_col1, date_col2 = st.columns(3)
    with score_col:
        score_range = st.slider(
            "Suitability Score", min_value=1, max_value=10, value=(1, 10), key="gcc_history_score_range"
        )
    with date_col1:
        start_date_input: Optional[date] = st.date_input(
            "From date", value=None, key="gcc_history_start_date"
        )
    with date_col2:
        end_date_input: Optional[date] = st.date_input(
            "To date", value=None, key="gcc_history_end_date"
        )

    page_size = st.selectbox("Results per page", options=PAGE_SIZE_OPTIONS, index=1, key="gcc_history_page_size")

    # Reset to page 1 whenever filters change, so the user doesn't end up on
    # an out-of-range page for the new filter set.
    filter_signature = (search_term, gcc_filter, score_range, start_date_input, end_date_input, page_size)
    if st.session_state.get("gcc_history_filter_sig") != filter_signature:
        st.session_state["gcc_history_filter_sig"] = filter_signature
        st.session_state["gcc_history_page"] = 1

    current_page = st.session_state["gcc_history_page"]
    offset = (current_page - 1) * page_size

    gcc_presence_param = None
    if gcc_filter == "Has GCC":
        gcc_presence_param = True
    elif gcc_filter == "No GCC":
        gcc_presence_param = False

    start_datetime = (
        datetime.combine(start_date_input, time.min).replace(tzinfo=timezone.utc)
        if start_date_input
        else None
    )
    end_datetime = (
        datetime.combine(end_date_input, time.max).replace(tzinfo=timezone.utc)
        if end_date_input
        else None
    )

    try:
        with db_manager.get_session() as session:
            repo = ResearchResultRepository(session)
            db_results, total_count = repo.search_results(
                search_term=search_term or None,
                gcc_presence=gcc_presence_param,
                min_suitability_score=score_range[0],
                max_suitability_score=score_range[1],
                start_date=start_datetime,
                end_date=end_datetime,
                limit=page_size,
                offset=offset,
                order_by="created_at",
                order_direction="desc",
            )
            rows = [_db_result_to_row(r) for r in db_results]
    except Exception as exc:
        st.error(f"❌ Failed to load research history: {exc}")
        logger.error(f"History search failed: {exc}")
        return

    log_event(
        logger,
        "INFO",
        "history_search",
        details={"search_term": search_term, "results_returned": len(rows), "total_count": total_count},
    )

    total_pages = max(1, (total_count + page_size - 1) // page_size)
    st.caption(f"Found **{total_count}** matching results — page {current_page} of {total_pages}")

    if not rows:
        st.info("No historical results match these filters.")
        return

    import pandas as pd

    df = pd.DataFrame(rows)
    display_df = df.copy()
    display_df["gcc_presence"] = display_df["gcc_presence"].map(
        lambda v: "✅ Yes" if v is True else ("❌ No" if v is False else "❓ Unknown")
    )
    display_df = display_df.rename(
        columns={
            "company_name": "Company",
            "company_domain": "Domain",
            "gcc_presence": "GCC Presence",
            "gcc_location": "GCC Location",
            "suitability_score": "Score",
            "research_summary": "Summary",
            "created_at": "First Researched",
            "updated_at": "Last Updated",
        }
    )
    st.dataframe(
        display_df[
            ["Company", "Domain", "GCC Presence", "GCC Location", "Score", "Summary", "First Researched", "Last Updated"]
        ],
        width='stretch',
        hide_index=True,
    )

    nav_col1, nav_col2, nav_col3 = st.columns([1, 2, 1])
    with nav_col1:
        if st.button("⬅️ Previous", disabled=current_page <= 1, key="gcc_history_prev"):
            st.session_state["gcc_history_page"] = current_page - 1
            st.rerun()
    with nav_col3:
        if st.button("Next ➡️", disabled=current_page >= total_pages, key="gcc_history_next"):
            st.session_state["gcc_history_page"] = current_page + 1
            st.rerun()

    st.markdown("#### 📤 Bulk Export (current filtered page)")
    exp_col1, exp_col2 = st.columns(2)
    with exp_col1:
        st.download_button(
            "⬇️ Download CSV",
            data=export_to_csv_bytes(rows),
            file_name=generate_export_filename("gcc_research_history", "csv"),
            mime="text/csv",
            width='stretch',
        )
    with exp_col2:
        st.download_button(
            "⬇️ Download Excel",
            data=export_to_excel_bytes(rows),
            file_name=generate_export_filename("gcc_research_history", "xlsx"),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width='stretch',
        )
