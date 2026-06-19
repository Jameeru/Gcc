"""
Unit tests for the lazy db_manager proxy (src/core/database.py).

Covers the regression found while adding the Settings UI tests: mock.patch
(both the string-target form, e.g. @patch('module.db_manager'), and
patch.object on the proxy itself) internally does hasattr(obj, '__func__')
-style introspection before substituting a mock. Because _LazyDatabaseManager
previously delegated *every* attribute lookup -- including dunders -- to a
freshly-constructed real DatabaseManager, that introspection alone forced
construction and raised ValueError("SUPABASE_URL environment variable is
required") in any test environment without real Supabase credentials, even
though the whole point of the lazy proxy was to make importing/patching this
module safe without those credentials.
"""

import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch

import pytest

from src.core.database import _LazyDatabaseManager, db_manager


class TestLazyDatabaseManagerDunderSafety:
    def test_hasattr_dunder_does_not_construct_real_manager(self, monkeypatch):
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_KEY", raising=False)
        proxy = _LazyDatabaseManager()

        # Must not raise, and must report False rather than forcing
        # construction (which would raise ValueError, not return False).
        assert hasattr(proxy, "__func__") is False
        assert proxy._instance is None

    def test_mock_patch_string_target_works_without_supabase_env_vars(self, monkeypatch):
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_KEY", raising=False)

        # This is exactly the pattern used throughout tests/test_cache_manager.py
        # etc: @patch('src.core.database.db_manager'). Replicated here via
        # patch.object on the module-level name (equivalent mechanism) to
        # confirm it no longer requires SUPABASE_URL/SUPABASE_KEY.
        import src.core.database as database_module

        with patch.object(database_module, "db_manager") as mock_db_manager:
            mock_db_manager.get_session.return_value.__enter__.return_value = "fake-session"
            assert database_module.db_manager.get_session().__enter__() == "fake-session"

    def test_non_dunder_attribute_access_still_lazily_constructs(self, monkeypatch):
        # Real (non-magic) attribute access is unaffected by the fix --
        # it still requires SUPABASE_URL/SUPABASE_KEY, just as before.
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_KEY", raising=False)
        proxy = _LazyDatabaseManager()

        with pytest.raises(ValueError, match="SUPABASE_URL"):
            proxy.get_session

    def test_importing_module_does_not_require_env_vars(self):
        # db_manager is constructed at import time as a _LazyDatabaseManager
        # proxy, not a real DatabaseManager -- importing must never raise.
        assert isinstance(db_manager, _LazyDatabaseManager)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
