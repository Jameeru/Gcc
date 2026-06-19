"""
Unit tests for the Settings UI component (src/components/settings.py).

Covers the pure masking helper and the save/clear handlers' logic (blank
fields are no-ops, non-blank fields get encrypted+upserted, errors surface
as st.error rather than raising) with Streamlit and the DB session mocked
out, mirroring test_results_processor.py's approach to testing Streamlit
glue code.

**Validates the user's explicit request: "make it as ui to update the api
key. through the authenticate user update the api key", specifically that
any authenticated user can update keys and that saving them goes through
the encrypted-at-rest repository rather than storing plaintext anywhere.**
"""

import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, Mock, patch

import pytest

import src.components.settings as settings_module
from src.utils.api_keys import GEMINI_API_KEY_1, GEMINI_API_KEY_2, OPENAI_API_KEY


@pytest.fixture(autouse=True)
def _fake_db_env(monkeypatch):
    """
    db_manager is a lazy proxy (src/core/database.py) that only constructs
    the real DatabaseManager -- which requires SUPABASE_URL/SUPABASE_KEY --
    on first attribute access. Even patch.object(settings_module.db_manager,
    ...) triggers that construction while mock introspects the original
    attribute, so these must be set for any test that touches db_manager at
    all, even though the mocked-out get_session means no real connection is
    ever opened.
    """
    monkeypatch.setenv("SUPABASE_URL", "postgresql://fake.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "fake-key")
    settings_module.db_manager._instance = None
    yield
    settings_module.db_manager._instance = None


class TestMask:
    def test_masks_all_but_last_four_characters(self):
        assert settings_module._mask("sk-1234567890abcdef") == "•" * 15 + "cdef"

    def test_short_value_is_fully_masked(self):
        assert settings_module._mask("abc") == "•" * 3

    def test_empty_value_masks_to_empty_string(self):
        assert settings_module._mask("") == ""


class TestHandleSave:
    def _mock_session_cm(self, mock_session):
        """Build a context-manager mock mimicking db_manager.get_session()."""
        cm = MagicMock()
        cm.__enter__.return_value = mock_session
        cm.__exit__.return_value = False
        return cm

    @patch.object(settings_module, "log_event")
    @patch.object(settings_module.st, "rerun")
    @patch.object(settings_module.st, "success")
    @patch.object(settings_module, "ApiSettingsRepository")
    @patch.object(settings_module, "db_manager")
    def test_blank_fields_are_a_no_op(
        self, mock_db_manager, mock_repo_cls, mock_success, mock_rerun, mock_log_event
    ):
        with patch.object(settings_module.st, "info") as mock_info:
            settings_module._handle_save(
                {OPENAI_API_KEY: "", GEMINI_API_KEY_1: "   ", GEMINI_API_KEY_2: ""},
                current_user_id=1,
                user_session_id="sess-1",
            )

        mock_info.assert_called_once()
        mock_db_manager.get_session.assert_not_called()
        mock_rerun.assert_not_called()

    @patch.object(settings_module, "log_event")
    @patch.object(settings_module.st, "rerun")
    @patch.object(settings_module.st, "success")
    @patch.object(settings_module, "ApiSettingsRepository")
    @patch.object(settings_module, "db_manager")
    def test_non_blank_field_is_saved_via_repository_encrypted(
        self, mock_db_manager, mock_repo_cls, mock_success, mock_rerun, mock_log_event
    ):
        mock_session = Mock()
        mock_db_manager.get_session.return_value = self._mock_session_cm(mock_session)
        mock_repo = Mock()
        mock_repo_cls.return_value = mock_repo

        settings_module._handle_save(
            {OPENAI_API_KEY: "sk-new-value", GEMINI_API_KEY_1: "", GEMINI_API_KEY_2: ""},
            current_user_id=7,
            user_session_id="sess-1",
        )

        mock_repo.set_plaintext.assert_called_once_with(
            OPENAI_API_KEY, "sk-new-value", updated_by="7"
        )
        mock_session.commit.assert_called_once()
        mock_success.assert_called_once()
        mock_rerun.assert_called_once()

    @patch.object(settings_module, "log_event")
    @patch.object(settings_module.st, "rerun")
    @patch.object(settings_module.st, "success")
    @patch.object(settings_module, "ApiSettingsRepository")
    @patch.object(settings_module, "db_manager")
    def test_multiple_non_blank_fields_are_all_saved(
        self, mock_db_manager, mock_repo_cls, mock_success, mock_rerun, mock_log_event
    ):
        mock_session = Mock()
        mock_db_manager.get_session.return_value = self._mock_session_cm(mock_session)
        mock_repo = Mock()
        mock_repo_cls.return_value = mock_repo

        settings_module._handle_save(
            {
                OPENAI_API_KEY: "sk-value",
                GEMINI_API_KEY_1: "AIza-key-1",
                GEMINI_API_KEY_2: "",
            },
            current_user_id=None,
            user_session_id=None,
        )

        assert mock_repo.set_plaintext.call_count == 2
        saved_keys = {call.args[0] for call in mock_repo.set_plaintext.call_args_list}
        assert saved_keys == {OPENAI_API_KEY, GEMINI_API_KEY_1}

    @patch.object(settings_module, "db_manager")
    def test_db_failure_surfaces_as_error_not_an_exception(self, mock_db_manager):
        mock_db_manager.get_session.side_effect = Exception("DB unreachable")

        with patch.object(settings_module.st, "error") as mock_error:
            # Must not raise -- the Settings UI should degrade to an error
            # message, not crash the whole app.
            settings_module._handle_save(
                {OPENAI_API_KEY: "sk-value"}, current_user_id=1, user_session_id=None
            )

        mock_error.assert_called_once()


class TestHandleClear:
    def _mock_session_cm(self, mock_session):
        cm = MagicMock()
        cm.__enter__.return_value = mock_session
        cm.__exit__.return_value = False
        return cm

    @patch.object(settings_module, "log_event")
    @patch.object(settings_module.st, "rerun")
    @patch.object(settings_module.st, "success")
    @patch.object(settings_module, "ApiSettingsRepository")
    @patch.object(settings_module, "db_manager")
    def test_clearing_selected_key_deletes_via_repository(
        self, mock_db_manager, mock_repo_cls, mock_success, mock_rerun, mock_log_event
    ):
        mock_session = Mock()
        mock_db_manager.get_session.return_value = self._mock_session_cm(mock_session)
        mock_repo = Mock()
        mock_repo.delete_setting.return_value = True
        mock_repo_cls.return_value = mock_repo

        settings_module._handle_clear(["OpenAI API Key"], user_session_id=None)

        mock_repo.delete_setting.assert_called_once_with(OPENAI_API_KEY)
        mock_success.assert_called_once()
        mock_rerun.assert_called_once()

    def test_empty_selection_is_a_no_op(self):
        with patch.object(settings_module, "db_manager") as mock_db_manager:
            with patch.object(settings_module.st, "info") as mock_info:
                settings_module._handle_clear([], user_session_id=None)

        mock_info.assert_called_once()
        mock_db_manager.get_session.assert_not_called()

    @patch.object(settings_module.st, "rerun")
    @patch.object(settings_module.st, "info")
    @patch.object(settings_module, "ApiSettingsRepository")
    @patch.object(settings_module, "db_manager")
    def test_nothing_stored_for_selected_key_shows_info_not_success(
        self, mock_db_manager, mock_repo_cls, mock_info, mock_rerun
    ):
        mock_session = Mock()
        mock_db_manager.get_session.return_value = self._mock_session_cm(mock_session)
        mock_repo = Mock()
        mock_repo.delete_setting.return_value = False
        mock_repo_cls.return_value = mock_repo

        with patch.object(settings_module.st, "success") as mock_success:
            settings_module._handle_clear(["OpenAI API Key"], user_session_id=None)

        mock_success.assert_not_called()
        mock_info.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
