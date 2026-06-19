"""
Main Streamlit application entry point for the GCC Research Intelligence Platform.

Wires together authentication, CSV upload, sequential AI-powered research
processing, results display/export, and historical search into a single
cohesive application, presented through an enterprise-styled sidebar
navigation shell (see src/utils/theme.py for the shared visual theme).

Note on file location: design.md specifies `src/main.py` as the entry point,
but the project's setup script and operational docs (`setup_database.py`)
reference `streamlit run main.py` at the repository root, so this root-level
file remains the canonical entry point to avoid breaking that existing
convention.

**Validates: Requirements 6.5, 13.1, 14.6, 14.7**
"""

import secrets

import streamlit as st

from src.components.authentication import render_session_info, require_authentication
from src.components.file_upload import render_upload_widget
from src.components.history import render_history_page
from src.components.results_display import render_results_table
from src.components.results_processor import (
    PROVIDER_GEMINI,
    PROVIDER_OPENAI,
    get_current_state,
    render_processor,
    resume_processing,
    start_new_batch,
)
from src.components.settings import render_settings_tab
from src.core.database import check_database_health, db_manager, init_database
from src.models.repositories import ProcessingSessionRepository, ResearchResultRepository
from src.utils.api_keys import get_gemini_api_keys, is_configured
from src.utils.api_keys import OPENAI_API_KEY as OPENAI_API_KEY_SETTING
from src.utils.config import get_config
from src.utils.logging import get_logger, log_event
from src.utils.theme import ACCENT_RED, clean_html, inject_enterprise_theme, kpi_card, pill, render_page_header

logger = get_logger("main")

LAST_BATCH_ITEMS_KEY = "gcc_last_batch_items"
NAV_KEY = "gcc_nav_radio"

# (internal key, sidebar label, page title, page subtitle)
NAV_ITEMS = [
    ("dashboard", "📊  Dashboard", "Dashboard", "Live overview of research activity and system health"),
    ("upload", "📤  Upload & Process", "Upload & Process", "Upload a company list and run AI-powered GCC research"),
    ("results", "📋  Results", "Research Results", "Results from the most recently completed or stopped batch"),
    ("history", "📈  History", "Research History", "Search and export every result ever researched"),
    ("settings", "⚙️  Settings", "Settings", "Manage the API keys used for company research"),
]
_LABEL_TO_KEY = {label: key for key, label, _, _ in NAV_ITEMS}
_KEY_TO_TITLE = {key: (title, subtitle) for key, _, title, subtitle in NAV_ITEMS}


def main():
    """Main application entry point."""

    st.set_page_config(
        page_title="GCC Research Intelligence Platform",
        page_icon="🏢",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_enterprise_theme()

    try:
        init_database()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        st.error(f"❌ Database connection failed: {e}")
        st.info(
            "Make sure SUPABASE_URL and SUPABASE_KEY are set correctly in your .env file, "
            "and that the database is reachable."
        )
        st.stop()

    session_manager = require_authentication()

    logger.info(
        f"Authenticated user accessing main app: user_id={session_manager.get_current_user_id()}"
    )

    render_main_app(session_manager)


def render_sidebar() -> str:
    """
    Render the enterprise sidebar shell: brand header, nav menu, live batch
    badge, and the user/session panel. Returns the selected nav page key.
    """
    with st.sidebar:
        st.markdown(
            """
            <div class="gcc-brand">
                <div class="gcc-brand-icon">🏢</div>
                <div>
                    <div class="gcc-brand-text-title">GCC Research</div>
                    <div class="gcc-brand-text-sub">Intelligence Platform</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        active_state = get_current_state()
        if active_state and active_state.status == "running":
            st.markdown(
                f'<span class="gcc-badge gcc-badge-running">● Batch running '
                f'{active_state.current_index}/{len(active_state.company_records)}</span>',
                unsafe_allow_html=True,
            )
            st.markdown("<div style='height:0.6rem'></div>", unsafe_allow_html=True)
        elif active_state and active_state.status == "stopped":
            st.markdown(
                f'<span class="gcc-badge gcc-badge-stopped">⏸ Batch paused '
                f'{active_state.current_index}/{len(active_state.company_records)}</span>',
                unsafe_allow_html=True,
            )
            st.markdown("<div style='height:0.6rem'></div>", unsafe_allow_html=True)

        st.markdown('<div class="gcc-nav-label">Navigate</div>', unsafe_allow_html=True)
        labels = [label for _, label, _, _ in NAV_ITEMS]
        selected_label = st.radio(
            "Navigate",
            options=labels,
            key=NAV_KEY,
            label_visibility="collapsed",
        )

        st.markdown("---")
        render_session_info()

    return _LABEL_TO_KEY[selected_label]


def render_main_app(session_manager):
    """
    Render the main authenticated application interface.

    Args:
        session_manager: Authenticated session manager instance.
    """
    page_key = render_sidebar()
    title, subtitle = _KEY_TO_TITLE[page_key]
    render_page_header(title, subtitle)

    if page_key == "dashboard":
        render_dashboard_page(session_manager)
    elif page_key == "upload":
        render_upload_page(session_manager)
    elif page_key == "results":
        render_results_page()
    elif page_key == "history":
        render_history_page()
    elif page_key == "settings":
        render_settings_tab()


def _status_pill(status: str) -> str:
    kind = {
        "running": "blue",
        "completed": "green",
        "stopped": "amber",
        "error": "red",
    }.get(status, "slate")
    return pill(status.capitalize(), kind)


def render_dashboard_page(session_manager):
    """Enterprise dashboard: KPI cards, system health, and recent activity."""

    active_state = get_current_state()
    if active_state and active_state.status == "running":
        st.info(
            f"⏳ A batch is currently processing: **{active_state.current_index}/"
            f"{len(active_state.company_records)}** companies. Open **Upload & Process** "
            "in the sidebar to view live progress."
        )
    elif active_state and active_state.status == "stopped":
        st.warning(
            f"⏸️ A batch is paused at **{active_state.current_index}/"
            f"{len(active_state.company_records)}** companies. Open **Upload & Process** "
            "to resume it."
        )

    try:
        with db_manager.get_session() as session:
            cache_stats = ResearchResultRepository(session).get_cache_statistics()
            recent_sessions = ProcessingSessionRepository(session).get_recent_sessions(limit=6)
        stats_error = None
    except Exception as exc:  # noqa: BLE001
        cache_stats = {
            "total_cached_results": 0,
            "results_with_gcc": 0,
            "gcc_presence_rate": 0,
            "average_suitability_score": 0,
        }
        recent_sessions = []
        stats_error = str(exc)

    if stats_error:
        st.error(f"❌ Could not load dashboard metrics: {stats_error}")

    col1, col2, col3, col4 = st.columns(4)
    kpi_card(
        col1,
        "Companies Researched",
        f"{cache_stats['total_cached_results']:,}",
        icon="🏢",
        delta="All-time, across every provider",
    )
    kpi_card(
        col2,
        "GCC Presence Rate",
        f"{cache_stats['gcc_presence_rate']:.1f}%",
        icon="🇮🇳",
        delta=f"{cache_stats['results_with_gcc']:,} companies with a GCC in India",
    )
    kpi_card(
        col3,
        "Avg Suitability Score",
        f"{cache_stats['average_suitability_score']:.1f} / 10",
        icon="📈",
        delta="Across all scored results",
    )
    batch_value = "Idle"
    batch_kind = "neutral"
    if active_state and active_state.status == "running":
        batch_value = f"{active_state.current_index}/{len(active_state.company_records)}"
        batch_kind = "positive"
    elif active_state and active_state.status == "stopped":
        batch_value = "Paused"
        batch_kind = "negative"
    kpi_card(
        col4,
        "Active Batch",
        batch_value,
        icon="⚙️",
        delta=active_state.provider.title() if active_state else "No batch running",
        delta_kind=batch_kind,
    )

    st.markdown("<div style='height:1.25rem'></div>", unsafe_allow_html=True)

    col_left, col_right = st.columns([1, 1.4])

    with col_left:
        db_health = check_database_health()
        config = get_config()
        db_pill = pill("Connected", "green") if db_health["status"] == "healthy" else pill("Error", "red")

        openai_ready = is_configured(OPENAI_API_KEY_SETTING)
        gemini_ready = len(get_gemini_api_keys()) > 0
        openai_pill = pill("Configured", "green") if openai_ready else pill("Not Set", "slate")
        gemini_pill = pill("Configured", "green") if gemini_ready else pill("Not Set", "slate")

        session_status = session_manager.get_session_status()
        session_pill = pill("Active", "green") if session_status["authenticated"] else pill("Inactive", "red")

        db_error_row = ""
        if db_health.get("status") != "healthy" and db_health.get("error"):
            db_error_row = f"""
                <div class="gcc-status-row">
                    <span class="gcc-status-label">DB Error Detail</span>
                    <span class="gcc-status-value" style="color:{ACCENT_RED};font-weight:600;font-size:0.78rem;">
                        {db_health.get('error')}
                    </span>
                </div>
            """

        st.markdown(
            clean_html(
                f"""
                <div class="gcc-card">
                    <div class="gcc-card-title">🩺 System Health</div>
                    <div class="gcc-status-row">
                        <span class="gcc-status-label">Database</span>
                        <span class="gcc-status-value">{db_pill}</span>
                    </div>
                    <div class="gcc-status-row">
                        <span class="gcc-status-label">DB Host</span>
                        <span class="gcc-status-value">{db_health.get('database_url_host', 'N/A')}</span>
                    </div>
                    {db_error_row}
                    <div class="gcc-status-row">
                        <span class="gcc-status-label">OpenAI Provider</span>
                        <span class="gcc-status-value">{openai_pill}</span>
                    </div>
                    <div class="gcc-status-row">
                        <span class="gcc-status-label">Gemini Provider</span>
                        <span class="gcc-status-value">{gemini_pill}</span>
                    </div>
                    <div class="gcc-status-row">
                        <span class="gcc-status-label">Your Session</span>
                        <span class="gcc-status-value">{session_pill}</span>
                    </div>
                    <div class="gcc-status-row">
                        <span class="gcc-status-label">Session Time Remaining</span>
                        <span class="gcc-status-value">{session_status.get('time_remaining', 'N/A')}</span>
                    </div>
                </div>
                """
            ),
            unsafe_allow_html=True,
        )

        st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)
        with st.expander("View raw configuration"):
            st.json(config.get_config_summary())

    with col_right:
        if not recent_sessions:
            rows_html = (
                '<div class="gcc-status-row"><span class="gcc-status-label">'
                "No processing sessions yet — upload a CSV to get started.</span></div>"
            )
        else:
            row_parts = []
            for sess in recent_sessions:
                row_parts.append(
                    clean_html(
                        f"""
                        <div class="gcc-status-row">
                            <span class="gcc-status-label">{sess.session_id[:10]}…</span>
                            <span class="gcc-status-value">
                                {sess.processed_companies}/{sess.total_companies} · {_status_pill(sess.status)}
                            </span>
                        </div>
                        """
                    )
                )
            rows_html = "\n".join(row_parts)

        st.markdown(
            clean_html(
                f"""
                <div class="gcc-card">
                    <div class="gcc-card-title">🕒 Recent Processing Activity</div>
                    {rows_html}
                </div>
                """
            ),
            unsafe_allow_html=True,
        )


def render_upload_page(session_manager):
    """
    Render file upload + processing workflow with resume capability.

    **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 6.1, 6.2, 6.3, 6.4, 6.5**
    """
    active_state = get_current_state()

    if active_state and active_state.status == "running":
        # A batch is mid-flight: keep advancing it rather than showing the
        # upload widget again, so the in-progress work isn't disrupted.
        st.info("Processing in progress...")
        result = render_processor()
        if result is not None:
            st.session_state[LAST_BATCH_ITEMS_KEY] = result
            st.info("👉 View full results on the **Results** page.")
        return

    if active_state and active_state.status == "stopped":
        # Show information about the stopped session and resume option
        total = len(active_state.company_records)
        st.info(f"⏸️ **Session paused:** {active_state.current_index}/{total} companies processed")

        col1, col2 = st.columns([2, 1])
        with col1:
            st.write(f"**Session ID:** `{active_state.session_id}`")
            st.write(f"**Provider:** {active_state.provider.title()}")
            st.write(f"**Progress:** {active_state.current_index}/{total} companies ({active_state.current_index/total*100:.1f}%)")

        with col2:
            if st.button("▶️ Resume Processing", key="resume_from_upload", type="primary"):
                if resume_processing(active_state.session_id):
                    st.rerun()
                else:
                    st.error("Failed to resume processing")

        st.markdown("---")
        st.subheader("Start New Batch")
        st.caption("Upload a new CSV file to start a fresh processing session (will replace the current stopped session)")

    outcome = render_upload_widget()

    if outcome and outcome.company_records:
        openai_ready = is_configured(OPENAI_API_KEY_SETTING)
        gemini_ready = len(get_gemini_api_keys()) > 0

        provider_options = []
        if openai_ready:
            provider_options.append("OpenAI (GPT-4o)")
        if gemini_ready:
            provider_options.append("Gemini")

        if not provider_options:
            st.error(
                "❌ No research provider is configured. Add an OpenAI or Gemini "
                "API key on the ⚙️ Settings page before starting research."
            )
            return

        provider_label = st.radio(
            "Research provider",
            options=provider_options,
            horizontal=True,
            help="Choose which AI provider researches these companies. "
            "Manage API keys on the ⚙️ Settings page.",
        )
        provider = PROVIDER_GEMINI if provider_label == "Gemini" else PROVIDER_OPENAI

        button_text = "🚀 Start Research Processing"
        if active_state and active_state.status == "stopped":
            button_text = "🚀 Start New Batch (Replace Paused Session)"

        if st.button(button_text, type="primary", width='stretch'):
            session_id = secrets.token_urlsafe(16)
            session_info = session_manager.get_session_info()
            log_event(
                logger,
                "INFO",
                "batch_processing_started",
                user_session=session_info.session_id if session_info else None,
                details={
                    "company_count": len(outcome.company_records),
                    "source_filename": outcome.source_filename,
                    "provider": provider,
                    "replaced_stopped_session": active_state is not None and active_state.status == "stopped",
                },
            )
            start_new_batch(outcome.company_records, session_id, provider=provider)
            st.rerun()

    elif active_state and active_state.status in ("stopped", "completed"):
        if active_state.status == "completed":
            st.markdown("---")
            st.markdown("#### Last Batch Outcome")
        result = render_processor()
        if result is not None:
            st.session_state[LAST_BATCH_ITEMS_KEY] = result


def render_results_page():
    """
    Render the results table for the most recently completed/stopped batch.

    **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 8.1, 8.2, 8.3, 8.4, 8.5**
    """
    items = st.session_state.get(LAST_BATCH_ITEMS_KEY)
    if not items:
        active_state = get_current_state()
        if active_state and active_state.status == "running":
            st.info(
                "A batch is still processing — results will appear here once it "
                "finishes or is stopped. Check the Upload & Process page for live progress."
            )
        else:
            st.info("No results yet. Upload a CSV file on the Upload & Process page to get started.")
        return

    render_results_table(items)


if __name__ == "__main__":
    main()
