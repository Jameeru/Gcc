"""
Unit tests for the encryption-at-rest utility (src/utils/crypto.py).

Covers key generation/validation, SecretBox encrypt/decrypt roundtrip,
failure modes (missing env var, malformed key, wrong key), and the
module-level lazy singleton / convenience wrapper functions.

**Validates the "Database, encrypted at rest" requirement from the user's
explicit answer on API key storage.**
"""

import base64
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import pytest

from src.utils import crypto as crypto_module
from src.utils.crypto import (
    CryptoConfigError,
    DecryptionError,
    SecretBox,
    decrypt_secret,
    encrypt_secret,
    generate_encryption_key,
    get_secret_box,
)


@pytest.fixture(autouse=True)
def _reset_singleton(monkeypatch):
    """Ensure the module-level singleton doesn't leak state between tests."""
    monkeypatch.setattr(crypto_module, "_secret_box", None, raising=False)
    yield
    monkeypatch.setattr(crypto_module, "_secret_box", None, raising=False)


def _fresh_key() -> str:
    return generate_encryption_key()


class TestGenerateEncryptionKey:
    def test_generates_urlsafe_base64_32_byte_key(self):
        key = generate_encryption_key()
        raw = base64.urlsafe_b64decode(key)
        assert len(raw) == 32

    def test_generates_a_different_key_each_call(self):
        assert generate_encryption_key() != generate_encryption_key()


class TestSecretBoxRoundtrip:
    def test_encrypt_then_decrypt_returns_original_plaintext(self, monkeypatch):
        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", _fresh_key())
        box = SecretBox()
        ciphertext = box.encrypt("sk-super-secret-value")
        assert ciphertext != "sk-super-secret-value"
        assert box.decrypt(ciphertext) == "sk-super-secret-value"

    def test_encrypting_same_plaintext_twice_produces_different_ciphertext(self, monkeypatch):
        # Fernet includes a random nonce/timestamp, so re-encrypting the same
        # plaintext should not be deterministic (no ECB-style fingerprinting).
        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", _fresh_key())
        box = SecretBox()
        c1 = box.encrypt("same-value")
        c2 = box.encrypt("same-value")
        assert c1 != c2
        assert box.decrypt(c1) == box.decrypt(c2) == "same-value"


class TestSecretBoxFailureModes:
    def test_missing_env_var_raises_crypto_config_error(self, monkeypatch):
        monkeypatch.delenv("SETTINGS_ENCRYPTION_KEY", raising=False)
        box = SecretBox()
        with pytest.raises(CryptoConfigError):
            box.encrypt("anything")

    def test_malformed_key_raises_crypto_config_error(self, monkeypatch):
        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", "not-a-valid-fernet-key")
        box = SecretBox()
        with pytest.raises(CryptoConfigError):
            box.encrypt("anything")

    def test_wrong_length_key_raises_crypto_config_error(self, monkeypatch):
        # Valid urlsafe-base64 but not exactly 32 raw bytes.
        short_key = base64.urlsafe_b64encode(os.urandom(16)).decode()
        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", short_key)
        box = SecretBox()
        with pytest.raises(CryptoConfigError):
            box.encrypt("anything")

    def test_decrypting_with_a_different_key_raises_decryption_error(self, monkeypatch):
        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", _fresh_key())
        box1 = SecretBox()
        ciphertext = box1.encrypt("secret-value")

        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", _fresh_key())
        box2 = SecretBox()
        with pytest.raises(DecryptionError):
            box2.decrypt(ciphertext)

    def test_decrypting_garbage_raises_decryption_error(self, monkeypatch):
        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", _fresh_key())
        box = SecretBox()
        with pytest.raises(DecryptionError):
            box.decrypt("not-valid-ciphertext-at-all")


class TestLazySingletonAndWrappers:
    def test_get_secret_box_returns_same_instance(self, monkeypatch):
        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", _fresh_key())
        box1 = get_secret_box()
        box2 = get_secret_box()
        assert box1 is box2

    def test_importing_module_does_not_require_env_var(self, monkeypatch):
        monkeypatch.delenv("SETTINGS_ENCRYPTION_KEY", raising=False)
        # Constructing a SecretBox (or calling get_secret_box) must not raise
        # just from instantiation -- only an actual encrypt/decrypt call
        # should fail, mirroring the lazy-singleton pattern used elsewhere.
        box = get_secret_box()
        assert box is not None

    def test_convenience_wrappers_roundtrip(self, monkeypatch):
        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", _fresh_key())
        ciphertext = encrypt_secret("wrapper-roundtrip-value")
        assert decrypt_secret(ciphertext) == "wrapper-roundtrip-value"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
