"""
Sequential results processor for the GCC Research Intelligence Platform.

Processes a list of CompanyRecord objects one at a time (to respect OpenAI
rate limits), checking the cache before each expensive AI call, with live
progress tracking, stop preservation, and per-company error isolation.

Streamlit scripts run top-to-bottom on every interaction and block while
running, so a single call can't both process a long batch AND stay
responsive to a "Stop" button click. This module uses the standard
Streamlit idiom for that: process exactly one company per script run, then
call `st.rerun()` to continue, checking the stop flag at the top of each
run before doing more work. That keeps the UI responsive between every
single company (the Stop button click is processed on the very next rerun)
while still implementing genuinely sequential, one-at-a-time processing of
the cache and AI calls.

**Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 10.4**
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import streamlit as st

from ..core.cache_manager import CacheError, get_cache_manager
from ..core.database import db_manager
from ..models.entities import CompanyRecord, ResearchResult
from ..models.repositories import ProcessingSessionRepository
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


@dataclass
class ProcessedItem:
    """A single company's processing outcome."""

    company_record: CompanyRecord
    research_result: Optional[ResearchResult]
    is_cached: bool
    error: Optional[str] = None


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


def _process_one(state: ProcessingState, user_session_id: Optional[str]) -> None:
    """
    Process exactly one company: cache lookup first, AI research on miss.

    Any failure researching this specific company is caught and recorded as
    an error on this item only -- it must not abort the remaining batch.

    **Validates: Requirements 6.1, 10.4**
    """
    record = state.company_records[state.current_index]
    cache_manager = get_cache_manager()

    try:
        cached = cache_manager.lookup_cache(record.normalized_key)
    except CacheError as exc:
        logger.warning(f"Cache lookup failed for '{record.name}', proceeding to research: {exc}")
        cached = None

    if cached is not None:
        state.items.append(ProcessedItem(company_record=record, research_result=cached, is_cached=True))
        state.cache_hits += 1
        log_event(
            logger,
            "INFO",
            "company_cache_hit",
            user_session=user_session_id,
            details={"company_name": record.name, "row_index": record.row_index},
        )
    else:
        try:
            if state.provider == PROVIDER_GEMINI:
                engine = get_gemini_engine()
            else:
                engine = get_research_engine()

            result = engine.research_company(
                record.name, record.domain, session_id=state.session_id
            )
            try:
                cache_manager.store_cache(record, result, provider=state.provider)
            except CacheError as exc:
                # Research succeeded; failing to persist to cache shouldn't
                # discard a perfectly good result for this run.
                logger.warning(f"Failed to store cache entry for '{record.name}': {exc}")

            state.items.append(
                ProcessedItem(company_record=record, research_result=result, is_cached=False)
            )
        except (ResearchEngineError, GeminiEngineError) as exc:
            # Property 19: Error Isolation -- a failure researching this one
            # company (with either provider) must not abort the remaining
            # batch, so it's recorded against this item only.
            state.errors += 1
            state.items.append(
                ProcessedItem(
                    company_record=record,
                    research_result=None,
                    is_cached=False,
                    error=str(exc),
                )
            )
            log_event(
                logger,
                "ERROR",
                "company_research_failed",
                user_session=user_session_id,
                details={
                    "company_name": record.name,
                    "provider": state.provider,
                    "error": str(exc),
                },
            )

    state.current_index += 1


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
    Render progress UI for the active batch and advance it by one company
    per call. Intended to be called on every script run while a batch is
    in progress; the caller is responsible for triggering reruns (this
    function calls `st.rerun()` itself while still running).

    Returns:
        The final list of ProcessedItem once the batch reaches a terminal
        state (completed or stopped), otherwise None (still in progress).

    **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 10.4**
    """
    state = get_current_state()
    if state is None:
        return None

    session_manager = SessionManager()
    user_session_info = session_manager.get_session_info()
    user_session_id = user_session_info.session_id if user_session_info else None

    total = len(state.company_records)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Processed", f"{state.current_index}/{total}")
    col2.metric("Cache Hits", state.cache_hits)
    col3.metric("Errors", state.errors)
    col4.metric("Status", state.status.capitalize())

    progress_fraction = (state.current_index / total) if total > 0 else 1.0
    st.progress(min(progress_fraction, 1.0))

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
            return state.items

        if state.current_index < total:
            current_company = state.company_records[state.current_index].name
            st.caption(f"Processing: **{current_company}**...")
            _process_one(state, user_session_id)
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
        
        return state.items

    elif state.status == "completed":
        st.success(f"✅ Processing complete! {total} companies researched.")
        return state.items

    return None
