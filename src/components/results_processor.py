"""
Chunked, concurrent results processor for the GCC Research Intelligence Platform.

Processes companies in CHUNKS of up to `chunk_size` per Streamlit rerun,
researching every company within a chunk concurrently via a
ThreadPoolExecutor (up to `max_workers` in flight at once), checking the
cache before each expensive AI call, with live progress tracking, stop
preservation, and per-company error isolation.

Streamlit scripts run top-to-bottom on every interaction and block while
running, so a single call can't both process a long batch AND stay
responsive to a "Stop" button click -- this module still uses the standard
Streamlit idiom of "do some work, then call st.rerun()", but each rerun now
advances by a whole CHUNK of concurrently-researched companies instead of
exactly one. That's the difference between ~12s/company sequential (the
original design) and, with the default chunk_size=15 / max_workers=10,
roughly 10x-15x higher throughput -- the dominant cost per company is
waiting on the AI provider's network round-trip, which is exactly what
running many in parallel hides. The Stop button is still checked at the top
of every rerun, so the worst-case delay before a stop takes effect is one
chunk's wall-clock time (not one company's).

**Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 10.4**
"""

from __future__ import annotations

import concurrent.futures
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

from ..core.cache_manager import CacheError, get_cache_manager
from ..core.database import db_manager
from ..models.entities import CompanyRecord, ResearchResult
from ..models.repositories import ProcessingSessionRepository
from ..utils.config import get_config
from ..utils.logging import get_logger, log_event
from .authentication import SessionManager
from .gemini_engine import GeminiEngineError, get_gemini_engine
from .research_engine import ResearchEngineError, get_research_engine

logger = get_logger("results_processor")

PROC_STATE_KEY = "gcc_processing_state"

# Supported research providers, selectable by the user before starting a
# batch (see render_upload_widget's provider selector in main.py / task #19).
PROVIDER_OPENAI = "openai"
PROVIDER_GEMINI = "gemini"
SUPPORTED_PROVIDERS = (PROVIDER_OPENAI, PROVIDER_GEMINI)

# How many companies are researched concurrently per Streamlit rerun cycle.
# Tuned for the OpenAI/Gemini web-search-grounded calls' typical latency
# (several seconds each, network-bound) -- a chunk this size keeps each
# rerun's wall-clock time in the same few-second ballpark as the old
# one-company-per-rerun design, while researching many companies within it.
DEFAULT_CHUNK_SIZE = 15

# Cap on how many completed rows the LIVE in-progress table renders per
# rerun. At 20k-50k company scale, re-rendering every completed row on every
# rerun would mean Streamlit re-serializing a steadily-growing dataframe
# (O(n) work repeated O(n/chunk_size) times -> effectively O(n^2) over a
# full run) -- showing only the most recent rows keeps every rerun's render
# cost roughly constant regardless of total batch size. The full result set
# is still always available afterward on the Results page / CSV/Excel export.
LIVE_TABLE_MAX_ROWS = 50


@dataclass
class ProcessedItem:
    """A single company's processing outcome."""

    company_record: CompanyRecord
    research_result: Optional[ResearchResult]
    is_cached: bool
    error: Optional[str] = None


def _default_max_workers() -> int:
    """
    Default worker-pool size for chunk processing, sourced from the existing
    (previously-unused) AppConfig.max_concurrent_requests setting so it's
    configurable via the MAX_CONCURRENT_REQUESTS env var without adding a
    second knob.
    """
    try:
        return max(1, get_config().app.max_concurrent_requests)
    except Exception:  # noqa: BLE001 - never let config resolution block processing
        return 10


@dataclass
class ProcessingState:
    """In-memory (session_state) tracking of an in-progress batch run."""

    session_id: str
    company_records: List[CompanyRecord]
    current_index: int = 0
    items: List[ProcessedItem] = field(default_factory=list)
    status: str = "running"  # running, stopped, completed
    cache_hits: int = 0
    errors: int = 0
    provider: str = PROVIDER_OPENAI  # which research engine to use for cache misses
    chunk_size: int = DEFAULT_CHUNK_SIZE
    max_workers: int = field(default_factory=_default_max_workers)
    started_at: float = field(default_factory=time.time)  # for live ETA display

    # Running tallies of the tri-state research outcome, maintained
    # incrementally as each item is appended (see _process_chunk) rather
    # than recomputed by scanning state.items on every rerun -- at 20k-50k
    # company scale, an O(n) rescan on every single rerun would make the
    # live KPI cards alone cost O(n^2) work over a full batch.
    gcc_no: int = 0
    gcc_yes: int = 0
    gcc_uncertain: int = 0
    fit_strong: int = 0


def resume_processing(session_id: str) -> bool:
    """
    Resume a previously stopped processing session from where it left off.

    Args:
        session_id: The session identifier of the stopped processing batch.

    Returns:
        True if resume was successful, False if the session couldn't be found
        or was already completed.

    **Validates: Requirements 6.3, 6.4**
    """
    state = get_current_state()
    if state is not None and state.status == "running":
        logger.warning(f"Cannot resume session {session_id}: another batch is already running")
        return False

    if state is not None and state.session_id == session_id and state.status == "stopped":
        # Resume the existing stopped session
        state.status = "running"
        log_event(
            logger,
            "INFO", 
            "processing_resumed_by_user",
            details={"session_id": session_id, "resume_from": state.current_index},
        )
        return True
    
    logger.warning(f"Cannot resume session {session_id}: session not found or not in stopped state")
    return False


def _create_db_session(session_id: str, total_companies: int) -> None:
    try:
        with db_manager.get_session() as session:
            ProcessingSessionRepository(session).create_session(session_id, total_companies)
    except Exception as exc:  # noqa: BLE001 - tracking shouldn't block processing
        logger.warning(f"Failed to create processing session record: {exc}")


def _update_db_progress(state: ProcessingState) -> None:
    try:
        with db_manager.get_session() as session:
            ProcessingSessionRepository(session).update_progress(
                state.session_id,
                processed_companies=state.current_index,
                cache_hits=state.cache_hits,
                errors=state.errors,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Failed to update processing session progress: {exc}")


def _complete_db_session(state: ProcessingState, status: str) -> None:
    try:
        with db_manager.get_session() as session:
            ProcessingSessionRepository(session).complete_session(state.session_id, status=status)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Failed to mark processing session as {status}: {exc}")


def _research_one_company(
    record: CompanyRecord,
    provider: str,
    processing_session_id: str,
    user_session_id: Optional[str],
) -> ProcessedItem:
    """
    Research exactly one company: cache lookup first, AI research on miss.

    Thread-safe and side-effect-free on shared state (it returns a
    ProcessedItem rather than mutating a ProcessingState) so it can be
    submitted to a ThreadPoolExecutor by `_process_chunk` -- many of these
    can run concurrently, each against its own cache lookup/AI call/cache
    store sequence, without any shared mutable state between them.

    Any failure researching this specific company is caught here and
    returned as an error on this item only -- it must not abort the
    remaining batch.

    **Validates: Requirements 6.1, 10.4**
    """
    cache_manager = get_cache_manager()

    try:
        cached = cache_manager.lookup_cache(record.normalized_key)
    except CacheError as exc:
        logger.warning(f"Cache lookup failed for '{record.name}', proceeding to research: {exc}")
        cached = None

    if cached is not None:
        log_event(
            logger,
            "INFO",
            "company_cache_hit",
            user_session=user_session_id,
            details={"company_name": record.name, "row_index": record.row_index},
        )
        return ProcessedItem(company_record=record, research_result=cached, is_cached=True)

    try:
        if provider == PROVIDER_GEMINI:
            engine = get_gemini_engine()
        else:
            engine = get_research_engine()

        result = engine.research_company(
            record.name, record.domain, session_id=processing_session_id
        )
        try:
            cache_manager.store_cache(record, result, provider=provider)
        except CacheError as exc:
            # Research succeeded; failing to persist to cache shouldn't
            # discard a perfectly good result for this run.
            logger.warning(f"Failed to store cache entry for '{record.name}': {exc}")

        return ProcessedItem(company_record=record, research_result=result, is_cached=False)
    except (ResearchEngineError, GeminiEngineError) as exc:
        # Property 19: Error Isolation -- a failure researching this one
        # company (with either provider) must not abort the remaining
        # batch, so it's recorded against this item only.
        log_event(
            logger,
            "ERROR",
            "company_research_failed",
            user_session=user_session_id,
            details={"company_name": record.name, "provider": provider, "error": str(exc)},
        )
        return ProcessedItem(
            company_record=record, research_result=None, is_cached=False, error=str(exc)
        )


def _process_chunk(state: ProcessingState, user_session_id: Optional[str]) -> None:
    """
    Process the next chunk of up to `state.chunk_size` un-processed
    companies concurrently, via a ThreadPoolExecutor with up to
    `state.max_workers` requests in flight at once.

    Order matters for the results table/exports, but `as_completed()`
    yields futures in COMPLETION order, not submission order -- so results
    are collected into an offset-keyed dict first and appended to
    `state.items` in original submission order afterward.

    **Validates: Requirements 6.1, 6.2, 10.4**
    """
    start = state.current_index
    end = min(start + state.chunk_size, len(state.company_records))
    chunk = state.company_records[start:end]
    if not chunk:
        return

    results_by_offset: Dict[int, ProcessedItem] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=state.max_workers) as executor:
        future_to_offset = {
            executor.submit(
                _research_one_company,
                record,
                state.provider,
                state.session_id,
                user_session_id,
            ): offset
            for offset, record in enumerate(chunk)
        }
        for future in concurrent.futures.as_completed(future_to_offset):
            offset = future_to_offset[future]
            results_by_offset[offset] = future.result()

    for offset in range(len(chunk)):
        item = results_by_offset[offset]
        state.items.append(item)
        if item.is_cached:
            state.cache_hits += 1
        elif item.error is not None:
            state.errors += 1

        result = item.research_result
        if result is not None:
            status = result.gcc_status or ("Yes" if result.gcc_presence else "No")
            if status == "No":
                state.gcc_no += 1
            elif status == "Yes":
                state.gcc_yes += 1
            elif status == "Uncertain":
                state.gcc_uncertain += 1
            if result.fit_rating == "Strong":
                state.fit_strong += 1

    state.current_index = end


def _format_eta(seconds: Optional[float]) -> str:
    """Format a remaining-time estimate as a short human-readable string."""
    if seconds is None or seconds < 0:
        return "Calculating..."
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours, mins = divmod(minutes, 60)
    return f"{hours}h {mins}m"


def _item_to_live_row(item: ProcessedItem) -> Dict[str, Any]:
    """Flatten one completed ProcessedItem into a live-table row."""
    record = item.company_record
    result = item.research_result

    if item.error is not None:
        return {
            "COMPANY": record.name,
            "DOMAIN": record.domain or "—",
            "HAS GCC": "⚠️ Error",
            "FIT": "—",
            "PAIN POINTS": item.error,
        }

    if result is None:
        return {
            "COMPANY": record.name,
            "DOMAIN": record.domain or "—",
            "HAS GCC": "—",
            "FIT": "—",
            "PAIN POINTS": "—",
        }

    has_gcc = result.gcc_status or ("Yes" if result.gcc_presence else "No")
    fit = result.fit_rating or "—"
    pain_points = result.pain_points_summary or result.research_summary or "—"
    cache_tag = " 💾" if item.is_cached else ""
    return {
        "COMPANY": record.name,
        "DOMAIN": record.domain or "—",
        "HAS GCC": f"{has_gcc}{cache_tag}",
        "FIT": fit,
        "PAIN POINTS": pain_points,
    }


def _in_flight_row(record: CompanyRecord) -> Dict[str, Any]:
    """Placeholder row for a company currently being researched."""
    return {
        "COMPANY": record.name,
        "DOMAIN": record.domain or "—",
        "HAS GCC": "🔄 Researching...",
        "FIT": "...",
        "PAIN POINTS": "...",
    }


def _render_live_table(state: ProcessingState, in_flight: Optional[List[CompanyRecord]] = None) -> None:
    """
    Render the live, streaming results table: COMPANY / DOMAIN / HAS GCC /
    FIT / PAIN POINTS, showing the most recently completed rows plus
    "Researching..." placeholder rows for the chunk about to be processed.

    Only the most recent `LIVE_TABLE_MAX_ROWS` completed rows are shown to
    keep render cost flat regardless of total batch size -- the full
    result set is always available on the Results page / exports once the
    batch finishes (or is stopped).

    **Validates: Requirements 7.1, 7.5**
    """
    recent_items = state.items[-LIVE_TABLE_MAX_ROWS:]
    rows = [_item_to_live_row(item) for item in recent_items]
    for record in in_flight or []:
        rows.append(_in_flight_row(record))

    if not rows:
        st.caption("No companies processed yet.")
        return

    df = pd.DataFrame(rows, columns=["COMPANY", "DOMAIN", "HAS GCC", "FIT", "PAIN POINTS"])
    if len(state.items) > LIVE_TABLE_MAX_ROWS:
        st.caption(
            f"Showing the most recent {LIVE_TABLE_MAX_ROWS} of {len(state.items)} "
            f"processed companies. Full results available on the Results page once done."
        )
    st.dataframe(df, width="stretch", hide_index=True)


def start_new_batch(
    company_records: List[CompanyRecord],
    session_id: str,
    provider: str = PROVIDER_OPENAI,
) -> None:
    """
    Initialize a fresh processing batch in session_state and the database.

    Args:
        company_records: Companies to process, in the exact order they
            should be researched.
        session_id: Unique identifier for this processing run.
        provider: Which research engine to use for cache misses in this
            batch ('openai' or 'gemini'). Defaults to 'openai' to preserve
            existing behavior for callers that don't pass it explicitly.

    **Validates: Requirements 6.1, 6.5**
    """
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(
            f"Unsupported provider '{provider}'; must be one of {SUPPORTED_PROVIDERS}"
        )
    state = ProcessingState(
        session_id=session_id, company_records=list(company_records), provider=provider
    )
    st.session_state[PROC_STATE_KEY] = state
    _create_db_session(session_id, len(company_records))


def get_current_state() -> Optional[ProcessingState]:
    """Return the active ProcessingState, if any."""
    return st.session_state.get(PROC_STATE_KEY)


def clear_state() -> None:
    """Clear processing state, e.g. when the user starts a brand new upload."""
    st.session_state.pop(PROC_STATE_KEY, None)


def render_processor() -> Optional[List[ProcessedItem]]:
    """
    Render the live batch-run dashboard for the active batch and advance it
    by one CHUNK of concurrently-researched companies per call: a run
    header, a progress bar with ETA, four KPI summary cards (No GCC found /
    Has GCC / Uncertain / Strong fit), and a live-updating results table
    (COMPANY / DOMAIN / HAS GCC / FIT / PAIN POINTS) with in-flight
    "Researching..." rows for the chunk about to be processed.

    Intended to be called on every script run while a batch is in
    progress; the caller is responsible for triggering reruns (this
    function calls `st.rerun()` itself while still running).

    Returns:
        The final list of ProcessedItem once the batch reaches a terminal
        state (completed or stopped), otherwise None (still in progress).

    **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 7.1, 7.5, 10.4**
    """
    state = get_current_state()
    if state is None:
        return None

    session_manager = SessionManager()
    user_session_info = session_manager.get_session_info()
    user_session_id = user_session_info.session_id if user_session_info else None

    total = len(state.company_records)

    # --- Run header ---
    st.markdown(f"### 🔄 Batch Run · {state.provider.upper()} · {total:,} companies")
    st.caption(f"Session `{state.session_id[:12]}…`")

    # --- Progress bar + ETA ---
    elapsed = time.time() - state.started_at
    processed = state.current_index
    rate = (processed / elapsed) if (elapsed > 0 and processed > 0) else None
    eta_seconds = ((total - processed) / rate) if rate else None

    progress_fraction = (processed / total) if total > 0 else 1.0
    st.progress(min(progress_fraction, 1.0))
    p_col1, p_col2, p_col3 = st.columns(3)
    p_col1.metric("Processed", f"{processed:,}/{total:,}")
    p_col2.metric("ETA", _format_eta(eta_seconds) if state.status == "running" else "—")
    p_col3.metric("Status", state.status.capitalize())

    # --- KPI summary cards ---
    k_col1, k_col2, k_col3, k_col4 = st.columns(4)
    k_col1.metric("No GCC found", f"{state.gcc_no:,}")
    k_col2.metric("Has GCC", f"{state.gcc_yes:,}")
    k_col3.metric("Uncertain", f"{state.gcc_uncertain:,}")
    k_col4.metric("Strong fit", f"{state.fit_strong:,}")

    if state.status == "running":
        stop_clicked = st.button("⏹️ Stop Processing", key="gcc_stop_processing_btn")
        if stop_clicked:
            state.status = "stopped"
            _update_db_progress(state)
            _complete_db_session(state, "stopped")
            log_event(
                logger,
                "INFO",
                "processing_stopped_by_user",
                user_session=user_session_id,
                details={"session_id": state.session_id, "processed": state.current_index},
            )
            st.warning(f"⏹️ Processing stopped. {state.current_index}/{total} companies completed and preserved.")
            _render_live_table(state)
            return state.items

        if state.current_index < total:
            chunk_end = min(state.current_index + state.chunk_size, total)
            in_flight = state.company_records[state.current_index : chunk_end]
            st.caption(f"🔬 Researching {len(in_flight)} companies concurrently...")
            _render_live_table(state, in_flight=in_flight)
            _process_chunk(state, user_session_id)
            _update_db_progress(state)
            st.rerun()
        else:
            state.status = "completed"
            _complete_db_session(state, "completed")
            log_event(
                logger,
                "INFO",
                "processing_completed",
                user_session=user_session_id,
                details={
                    "session_id": state.session_id,
                    "total": total,
                    "cache_hits": state.cache_hits,
                    "errors": state.errors,
                },
            )
            st.success(f"✅ Processing complete! {total} companies researched.")
            _render_live_table(state)
            return state.items

    elif state.status == "stopped":
        st.warning(f"⏹️ Processing was stopped. {state.current_index}/{total} companies completed and preserved.")

        # Show resume button
        col1, col2 = st.columns([1, 3])
        with col1:
            resume_clicked = st.button("▶️ Resume Processing", key="gcc_resume_processing_btn", type="primary")
        with col2:
            st.caption("Click to continue processing from where you left off")

        if resume_clicked:
            if resume_processing(state.session_id):
                st.rerun()
            else:
                st.error("Failed to resume processing. Please try starting a new batch.")

        _render_live_table(state)
        return state.items

    elif state.status == "completed":
        st.success(f"✅ Processing complete! {total} companies researched.")
        _render_live_table(state)
        return state.items

    return None
