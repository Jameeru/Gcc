"""
Main Streamlit application entry point for the GCC Research Intelligence Platform.

Wires together authentication, CSV upload, sequential AI-powered research
processing, results display/export, and historical search into a single
cohesive application.

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
from src.core.database import check_database_health, init_database
from src.utils.api_keys import get_gemini_api_keys, is_configured
from src.utils.api_keys import OPENAI_API_KEY as OPENAI_API_KEY_SETTING
from src.utils.config import get_config
from src.utils.logging import get_logger, log_event

logger = get_logger("main")

LAST_BATCH_ITEMS_KEY = "gcc_last_batch_items"


def main():
    """Main application entry point."""

    st.set_page_config(
        page_title="GCC Research Intelligence Platform",
        page_icon="🏢",
        layout="wide",
        initial_sidebar_state="expanded",
    )

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


def render_main_app(session_manager):
    """
    Render the main authenticated application interface.

    Args:
        session_manager: Authenticated session manager instance.
    """
    render_session_info()

    st.title("🏢 GCC Research Intelligence Platform")
    st.markdown(
        "Upload company lists, research their GCC potential in India with AI, "
        "and export the results."
    )

    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        ["📊 Dashboard", "📤 Upload", "📋 Results", "📈 History", "⚙️ Settings"]
    )

    with tab1:
        render_dashboard_tab(session_manager)

    with tab2:
        render_upload_tab(session_manager)

    with tab3:
        render_results_tab()

    with tab4:
        render_history_page()

    with tab5:
        render_settings_tab()


def render_dashboard_tab(session_manager):
    """Render dashboard tab with session information and system status."""

    st.subheader("📊 Dashboard")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### 👤 Session Status")
        session_status = session_manager.get_session_status()

        if session_status["authenticated"]:
            st.success("✅ Authenticated")
            st.write(f"**User ID:** {session_status['user_id']}")
            st.write(f"**Session ID:** {session_status['session_id'][:8]}...")
            st.write(f"**Time Remaining:** {session_status['time_remaining']}")
        else:
            st.error("❌ Not Authenticated")

    with col2:
        st.markdown("#### 🗄️ Database Status")
        db_health = check_database_health()

        if db_health["status"] == "healthy":
            st.success("✅ Database Connected")
            st.write(f"**Host:** {db_health.get('database_url_host', 'N/A')}")
            if db_health.get("pool_size") is not None:
                st.write(f"**Pool Size:** {db_health['pool_size']}")
        else:
            st.error("❌ Database Error")
            if db_health.get("error"):
                st.error(f"Error: {db_health['error']}")

    st.markdown("#### ⚙️ Configuration")
    config = get_config()
    config_summary = config.get_config_summary()

    with st.expander("View Configuration Details"):
        st.json(config_summary)

    active_state = get_current_state()
    if active_state and active_state.status == "running":
        st.markdown("#### ⏳ Active Processing")
        st.info(
            f"A batch is currently processing: {active_state.current_index}/"
            f"{len(active_state.company_records)} companies. Go to the Upload tab to view progress."
        )


def render_upload_tab(session_manager):
    """
    Render file upload + processing workflow with resume capability.

    **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 6.1, 6.2, 6.3, 6.4, 6.5**
    """
    st.subheader("📤 Upload & Process")

    active_state = get_current_state()

    if active_state and active_state.status == "running":
        # A batch is mid-flight: keep advancing it rather than showing the
        # upload widget again, so the in-progress work isn't disrupted.
        st.info("Processing in progress...")
        result = render_processor()
        if result is not None:
            st.session_state[LAST_BATCH_ITEMS_KEY] = result
            st.info("👉 View full results in the **Results** tab.")
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
                "API key in the ⚙️ Settings tab before starting research."
            )
            return

        provider_label = st.radio(
            "Research provider",
            options=provider_options,
            horizontal=True,
            help="Choose which AI provider researches these companies. "
            "Manage API keys in the ⚙️ Settings tab.",
        )
        provider = PROVIDER_GEMINI if provider_label == "Gemini" else PROVIDER_OPENAI

        button_text = "🚀 Start Research Processing"
        if active_state and active_state.status == "stopped":
            button_text = "🚀 Start New Batch (Replace Paused Session)"
            
        if st.button(button_text, type="primary", use_container_width=True):
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


def render_results_tab():
    """
    Render the results table for the most recently completed/stopped batch.

    **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 8.1, 8.2, 8.3, 8.4, 8.5**
    """
    st.subheader("📋 Research Results")

    items = st.session_state.get(LAST_BATCH_ITEMS_KEY)
    if not items:
        active_state = get_current_state()
        if active_state and active_state.status == "running":
            st.info(
                "A batch is still processing — results will appear here once it "
                "finishes or is stopped. Check the Upload tab for live progress."
            )
        else:
            st.info("No results yet. Upload a CSV file in the Upload tab to get started.")
        return

    render_results_table(items)


if __name__ == "__main__":
    main()
