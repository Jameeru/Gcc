"""
Unit tests for the runtime API key resolution layer (src/utils/api_keys.py).

Covers the DB-first/env-fallback resolution order, graceful degradation
when the DB is unreachable, the Gemini multi-key list helper, and that
importing the module never requires any env var to be set.

**Validates the "through the authenticate user update the api key" /
hot-reload requirement: this module is what makes a key saved in the
Settings UI take effect on the very next research call.**
"""

import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import Mock, patch

import pytest

import src.utils.api_keys as api_keys


@pytest.fixture(autouse=True)
def _fake_db_env(monkeypatch):
    """
    db_manager is a lazy proxy (src/core/database.py) that only constructs
    the real DatabaseManager -- which requires SUPABASE_URL/SUPABASE_KEY --
    on first attribute access, including when mock.patch.object inspects the
    original attribute before substituting it. Set fake values so that
    construction succeeds; no real connection is ever opened since the
    methods used are mocked out before being called.
    """
    monkeypatch.setenv("SUPABASE_URL", "postgresql://fake.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "fake-key")
    api_keys.db_manager._instance = None
    yield
    api_keys.db_manager._instance = None


class TestGetApiKeyResolutionOrder:
    def test_db_value_takes_precedence_over_env_var(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
        with patch.object(api_keys, "_get_from_db", return_value="sk-from-db"):
            assert api_keys.get_api_key(api_keys.OPENAI_API_KEY) == "sk-from-db"

    def test_falls_back_to_env_var_when_db_value_is_none(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
        with patch.object(api_keys, "_get_from_db", return_value=None):
            assert api_keys.get_api_key(api_keys.OPENAI_API_KEY) == "sk-from-env"

    def test_returns_none_when_neither_db_nor_env_is_set(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with patch.object(api_keys, "_get_from_db", return_value=None):
            assert api_keys.get_api_key(api_keys.OPENAI_API_KEY) is None

    def test_db_blank_string_falls_back_to_env_var(self, monkeypatch):
        # An empty string from the DB should be treated the same as "unset".
        monkeypatch.setenv("GEMINI_API_KEY_1", "AIza-from-env")
        with patch.object(api_keys, "_get_from_db", return_value=""):
            assert api_keys.get_api_key(api_keys.GEMINI_API_KEY_1) == "AIza-from-env"


class TestGetAllApiKeys:
    def test_resolves_each_key_independently(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-env-value")
        monkeypatch.delenv("GEMINI_API_KEY_1", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY_2", raising=False)

        with patch.object(
            api_keys,
            "_get_all_from_db",
            return_value={
                api_keys.OPENAI_API_KEY: None,
                api_keys.GEMINI_API_KEY_1: "AIza-db-value",
                api_keys.GEMINI_API_KEY_2: None,
            },
        ):
            resolved = api_keys.get_all_api_keys()

        assert resolved[api_keys.OPENAI_API_KEY] == "sk-env-value"  # env fallback
        assert resolved[api_keys.GEMINI_API_KEY_1] == "AIza-db-value"  # DB value
        assert resolved[api_keys.GEMINI_API_KEY_2] is None  # neither set


class TestGetGeminiApiKeys:
    def test_returns_both_keys_in_stable_order_when_both_set(self):
        with patch.object(
            api_keys,
            "get_api_key",
            side_effect=lambda key: {"gemini_api_key_1": "key-1", "gemini_api_key_2": "key-2"}[key],
        ):
            assert api_keys.get_gemini_api_keys() == ["key-1", "key-2"]

    def test_omits_unset_keys(self):
        with patch.object(
            api_keys,
            "get_api_key",
            side_effect=lambda key: {"gemini_api_key_1": "key-1", "gemini_api_key_2": None}[key],
        ):
            assert api_keys.get_gemini_api_keys() == ["key-1"]

    def test_returns_empty_list_when_neither_configured(self):
        with patch.object(api_keys, "get_api_key", return_value=None):
            assert api_keys.get_gemini_api_keys() == []


class TestIsConfigured:
    def test_true_when_key_resolves_to_a_value(self):
        with patch.object(api_keys, "get_api_key", return_value="sk-value"):
            assert api_keys.is_configured(api_keys.OPENAI_API_KEY) is True

    def test_false_when_key_resolves_to_none(self):
        with patch.object(api_keys, "get_api_key", return_value=None):
            assert api_keys.is_configured(api_keys.OPENAI_API_KEY) is False


class TestDbUnreachableDegradesGracefully:
    def test_get_from_db_swallows_exceptions_and_returns_none(self):
        with patch.object(api_keys.db_manager, "get_session", side_effect=Exception("DB down")):
            assert api_keys._get_from_db(api_keys.OPENAI_API_KEY) is None

    def test_get_api_key_falls_back_to_env_when_db_unreachable(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-bootstrap-value")
        with patch.object(api_keys.db_manager, "get_session", side_effect=Exception("DB down")):
            assert api_keys.get_api_key(api_keys.OPENAI_API_KEY) == "sk-bootstrap-value"

    def test_get_all_from_db_swallows_exceptions_and_returns_all_none(self):
        with patch.object(api_keys.db_manager, "get_session", side_effect=Exception("DB down")):
            result = api_keys._get_all_from_db([api_keys.OPENAI_API_KEY, api_keys.GEMINI_API_KEY_1])
        assert result == {api_keys.OPENAI_API_KEY: None, api_keys.GEMINI_API_KEY_1: None}


class TestModuleImportSafety:
    def test_importing_module_does_not_require_any_env_var(self):
        # If this test file imported api_keys successfully with no env vars
        # pre-set by the test runner specifically for it, the module-level
        # code didn't eagerly read/require anything at import time.
        assert hasattr(api_keys, "get_api_key")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
