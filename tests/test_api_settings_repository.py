"""
Unit tests for ApiSettingsRepository (src/models/repositories.py).

Exercises get/set/upsert/delete/is_set/batch-get against a real in-memory
SQLite database using the actual ApiSetting model, plus the
decrypt-failure-degrades-to-None behavior for get_all_plaintext.

**Validates the "Database, encrypted at rest" requirement: this repository
is the only code path that talks to the api_settings table, so its
encrypt-on-write / decrypt-on-read contract is the core of that guarantee.**
"""

import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.models.repositories import ApiSettingsRepository
from src.models.schemas import ApiSetting, Base
from src.utils.crypto import DecryptionError, generate_encryption_key


@pytest.fixture(autouse=True)
def _encryption_key(monkeypatch):
    monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", generate_encryption_key())
    # The crypto module's lazy singleton must not leak a SecretBox built
    # with a different test's key across tests.
    import src.utils.crypto as crypto_module

    monkeypatch.setattr(crypto_module, "_secret_box", None, raising=False)
    yield


@pytest.fixture
def engine():
    engine = create_engine("sqlite:///:memory:", echo=False)
    # Only create the api_settings table -- the other models in Base use
    # Postgres-specific features not all of which matter for this test.
    ApiSetting.__table__.create(engine)
    return engine


@pytest.fixture
def session(engine):
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def repo(session):
    return ApiSettingsRepository(session)


class TestSetAndGetPlaintext:
    def test_set_then_get_roundtrips_plaintext(self, repo, session):
        repo.set_plaintext("openai_api_key", "sk-test-value")
        session.commit()
        assert repo.get_plaintext("openai_api_key") == "sk-test-value"

    def test_get_unset_key_returns_none(self, repo):
        assert repo.get_plaintext("openai_api_key") is None

    def test_stored_value_is_actually_encrypted_in_the_db(self, repo, session):
        repo.set_plaintext("openai_api_key", "sk-plaintext-value")
        session.commit()
        row = session.query(ApiSetting).filter_by(setting_key="openai_api_key").first()
        assert row.encrypted_value != "sk-plaintext-value"

    def test_set_plaintext_is_upsert_not_duplicate_row(self, repo, session):
        repo.set_plaintext("openai_api_key", "first-value")
        session.commit()
        repo.set_plaintext("openai_api_key", "second-value")
        session.commit()

        rows = session.query(ApiSetting).filter_by(setting_key="openai_api_key").all()
        assert len(rows) == 1
        assert repo.get_plaintext("openai_api_key") == "second-value"

    def test_set_plaintext_records_updated_by(self, repo, session):
        setting = repo.set_plaintext("gemini_api_key_1", "AIza-value", updated_by="42")
        session.commit()
        assert setting.updated_by == "42"


class TestDeleteAndIsSet:
    def test_is_set_false_when_never_stored(self, repo):
        assert repo.is_set("openai_api_key") is False

    def test_is_set_true_after_storing(self, repo, session):
        repo.set_plaintext("openai_api_key", "sk-value")
        session.commit()
        assert repo.is_set("openai_api_key") is True

    def test_delete_setting_removes_row_and_returns_true(self, repo, session):
        repo.set_plaintext("openai_api_key", "sk-value")
        session.commit()
        assert repo.delete_setting("openai_api_key") is True
        session.commit()
        assert repo.is_set("openai_api_key") is False

    def test_delete_setting_on_missing_key_returns_false(self, repo):
        assert repo.delete_setting("openai_api_key") is False


class TestGetAllPlaintext:
    def test_batch_get_returns_dict_with_none_for_unset_keys(self, repo, session):
        repo.set_plaintext("openai_api_key", "sk-value")
        session.commit()

        result = repo.get_all_plaintext(["openai_api_key", "gemini_api_key_1", "gemini_api_key_2"])

        assert result == {
            "openai_api_key": "sk-value",
            "gemini_api_key_1": None,
            "gemini_api_key_2": None,
        }

    def test_batch_get_with_corrupted_entry_degrades_to_none_for_that_key_only(
        self, repo, session, monkeypatch
    ):
        repo.set_plaintext("openai_api_key", "sk-good-value")
        repo.set_plaintext("gemini_api_key_1", "AIza-good-value")
        session.commit()

        # Simulate the gemini_api_key_1 row being undecryptable (e.g. the
        # encryption key rotated) without touching the other, healthy row.
        from src.utils.crypto import get_secret_box

        real_decrypt = get_secret_box().decrypt

        def _flaky_decrypt(ciphertext):
            row = session.query(ApiSetting).filter_by(setting_key="gemini_api_key_1").first()
            if ciphertext == row.encrypted_value:
                raise DecryptionError("simulated corruption")
            return real_decrypt(ciphertext)

        monkeypatch.setattr(get_secret_box(), "decrypt", _flaky_decrypt)

        result = repo.get_all_plaintext(["openai_api_key", "gemini_api_key_1"])

        assert result["openai_api_key"] == "sk-good-value"
        assert result["gemini_api_key_1"] is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
