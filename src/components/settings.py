"""
Settings UI for managing OpenAI and Gemini API keys.

Lets any authenticated user (no admin gating, per the user's explicit
"Any authenticated user (Recommended for this internal tool)" answer) view
configuration status and update the API keys used for company research.

Keys are stored encrypted at rest (via ApiSettingsRepository / SecretBox,
see src/utils/crypto.py and src/models/repositories.py) and are resolved
fresh from the DB on every research call (src/utils/api_keys.py), so a key
saved here takes effect immediately -- no app restart required.

**Validates the user's explicit request: "make it as ui to update the api
key. through the authenticate user update the api key."**
"""

from __future__ import annotations

import streamlit as st

from ..core.database import db_manager
from ..models.repositories import ApiSettingsRepository
from ..utils.api_keys import GEMINI_API_KEY_1, GEMINI_API_KEY_2, OPENAI_API_KEY
from ..utils.logging import get_logger, log_event
from .authentication import SessionManager

logger = get_logger("settings")

# Display metadata for each managed setting key.
_SETTINGS_FIELDS = [
    {
        "setting_key": OPENAI_API_KEY,
        "label": "OpenAI API Key",
        "help": "Used for GPT-4o-powered research. Get a key at platform.openai.com.",
        "placeholder": "sk-...",
    },
    {
        "setting_key": GEMINI_API_KEY_1,
        "label": "Gemini API Key (1)",
        "help": "Primary Gemini key. Used for Gemini-powered research, with "
        "round-robin/failover against key 2 if both are set.",
        "placeholder": "AIza...",
    },
    {
        "setting_key": GEMINI_API_KEY_2,
        "label": "Gemini API Key (2)",
        "help": "Optional second Gemini key, for load-spreading and failover "
        "alongside key 1.",
        "placeholder": "AIza...",
    },
]


def _mask(value: str) -> str:
    """Mask a secret for display, showing only the last 4 characters."""
    if not value:
        return ""
    if len(value) <= 4:
        return "•" * len(value)
    return "•" * (len(value) - 4) + value[-4:]


def render_settings_tab() -> None:
    """
    Render the Settings tab: status + update form for each API key.

    Accessible to any authenticated user -- this internal tool has no
    admin/role distinction, per the user's explicit answer.
    """
    st.subheader("⚙️ Settings")
    st.markdown(
        "Manage the API keys used for company research. Keys are encrypted "
        "at rest and take effect immediately for the next research run -- "
        "no restart needed."
    )

    session_manager = SessionManager()
    session_info = session_manager.get_session_info()
    user_session_id = session_info.session_id if session_info else None
    current_user_id = session_manager.get_current_user_id()

    try:
        with db_manager.get_session() as session:
            repo = ApiSettingsRepository(session)
            statuses = {
                field["setting_key"]: repo.is_set(field["setting_key"])
                for field in _SETTINGS_FIELDS
            }
    except Exception as exc:  # noqa: BLE001
        st.error(f"❌ Could not load API key status from the database: {exc}")
        logger.error(f"Failed to load API settings status: {exc}")
        statuses = {field["setting_key"]: False for field in _SETTINGS_FIELDS}

    st.markdown("#### Status")
    status_cols = st.columns(len(_SETTINGS_FIELDS))
    for col, field in zip(status_cols, _SETTINGS_FIELDS):
        with col:
            if statuses.get(field["setting_key"]):
                st.success(f"✅ {field['label']}")
            else:
                st.warning(f"⚠️ {field['label']} not set")

    st.markdown("---")
    st.markdown("#### Update API Keys")
    st.caption(
        "Leave a field blank to keep its current value unchanged. "
        "Entering a new value replaces the stored key for that provider."
    )

    with st.form("api_settings_form"):
        new_values = {}
        for field in _SETTINGS_FIELDS:
            new_values[field["setting_key"]] = st.text_input(
                field["label"],
                type="password",
                placeholder=field["placeholder"],
                help=field["help"],
                key=f"settings_input_{field['setting_key']}",
            )

        col_save, col_clear = st.columns(2)
        with col_save:
            save_clicked = st.form_submit_button(
                "💾 Save Changes", type="primary", width='stretch'
            )
        with col_clear:
            clear_options = [field["label"] for field in _SETTINGS_FIELDS]
            clear_selection = st.multiselect(
                "Clear (remove) these keys",
                options=clear_options,
                key="settings_clear_selection",
                help="Selected keys will be deleted, falling back to the "
                "matching environment variable (if any) instead of the UI value.",
            )
            clear_clicked = st.form_submit_button(
                "🗑️ Clear Selected", width='stretch'
            )

    if save_clicked:
        _handle_save(new_values, current_user_id, user_session_id)

    if clear_clicked:
        _handle_clear(clear_selection, user_session_id)


def _handle_save(new_values: dict, current_user_id, user_session_id) -> None:
    """Persist any non-blank field values, encrypted at rest."""
    to_save = {key: value.strip() for key, value in new_values.items() if value and value.strip()}

    if not to_save:
        st.info("ℹ️ No new values entered -- nothing to save.")
        return

    try:
        with db_manager.get_session() as session:
            repo = ApiSettingsRepository(session)
            for setting_key, plaintext_value in to_save.items():
                repo.set_plaintext(
                    setting_key,
                    plaintext_value,
                    updated_by=str(current_user_id) if current_user_id else None,
                )
            session.commit()

        saved_labels = [
            field["label"] for field in _SETTINGS_FIELDS if field["setting_key"] in to_save
        ]
        st.success(f"✅ Saved: {', '.join(saved_labels)}")
        log_event(
            logger,
            "INFO",
            "api_settings_updated",
            user_session=user_session_id,
            details={"updated_keys": list(to_save.keys()), "user_id": current_user_id},
        )
        st.rerun()
    except Exception as exc:  # noqa: BLE001
        st.error(f"❌ Failed to save API key(s): {exc}")
        logger.error(f"Failed to save API settings: {exc}")


def _handle_clear(clear_selection, user_session_id) -> None:
    """Delete selected stored keys, falling back to env vars (if any)."""
    if not clear_selection:
        st.info("ℹ️ No keys selected to clear.")
        return

    labels_to_keys = {field["label"]: field["setting_key"] for field in _SETTINGS_FIELDS}
    keys_to_clear = [labels_to_keys[label] for label in clear_selection if label in labels_to_keys]

    try:
        with db_manager.get_session() as session:
            repo = ApiSettingsRepository(session)
            cleared = [key for key in keys_to_clear if repo.delete_setting(key)]
            session.commit()

        if cleared:
            st.success(f"✅ Cleared {len(cleared)} key(s).")
            log_event(
                logger,
                "INFO",
                "api_settings_cleared",
                user_session=user_session_id,
                details={"cleared_keys": cleared},
            )
        else:
            st.info("ℹ️ Nothing was stored for the selected key(s).")
        st.rerun()
    except Exception as exc:  # noqa: BLE001
        st.error(f"❌ Failed to clear API key(s): {exc}")
        logger.error(f"Failed to clear API settings: {exc}")
