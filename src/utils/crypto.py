"""
Symmetric encryption utility for storing secrets (API keys) at rest in the
database.

Uses Fernet (AES-128-CBC + HMAC, from the `cryptography` package) with a key
sourced from the SETTINGS_ENCRYPTION_KEY environment variable. This is a
separate concern from the OPENAI_API_KEY/SUPABASE_KEY env vars themselves:
those are read directly by their respective configs, while this key encrypts
*other* secrets (the user-managed OpenAI/Gemini API keys) that get stored in
the api_settings table via the Settings UI, per the user's explicit choice
of "Database, encrypted at rest".

Follows the same lazy-singleton pattern used elsewhere in this codebase
(core/database.py's _LazyDatabaseManager, research_engine.py's _engine) so
importing this module never crashes just because SETTINGS_ENCRYPTION_KEY
isn't set yet -- the error only surfaces when encryption/decryption is
actually attempted.
"""

from __future__ import annotations

import base64
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken


class CryptoConfigError(ValueError):
    """Raised when SETTINGS_ENCRYPTION_KEY is missing or malformed."""


class DecryptionError(ValueError):
    """Raised when a stored ciphertext cannot be decrypted with the current key."""


def generate_encryption_key() -> str:
    """
    Generate a new, valid Fernet key suitable for SETTINGS_ENCRYPTION_KEY.

    Intended for one-time use when setting up a new environment (e.g. a
    setup script or a CLI prompt), not called by the app at runtime.

    Returns:
        A url-safe base64-encoded 32-byte key, as a str.
    """
    return Fernet.generate_key().decode("utf-8")


def _load_fernet_key(raw_key: str) -> bytes:
    """
    Normalize SETTINGS_ENCRYPTION_KEY into the exact form Fernet expects.

    Accepts a key already in Fernet's url-safe-base64(32 bytes) form. Raises
    a clear, actionable error rather than letting Fernet's own less-specific
    binascii/ValueError bubble up, since a misconfigured key here would
    otherwise look like a confusing crash deep in the crypto library.
    """
    key_bytes = raw_key.strip().encode("utf-8")
    try:
        decoded = base64.urlsafe_b64decode(key_bytes)
    except Exception as exc:
        raise CryptoConfigError(
            "SETTINGS_ENCRYPTION_KEY is not valid url-safe base64. "
            "Generate one with crypto.generate_encryption_key() and set it "
            "as SETTINGS_ENCRYPTION_KEY."
        ) from exc

    if len(decoded) != 32:
        raise CryptoConfigError(
            f"SETTINGS_ENCRYPTION_KEY must decode to exactly 32 bytes, got "
            f"{len(decoded)}. Generate one with crypto.generate_encryption_key()."
        )
    return key_bytes


class SecretBox:
    """
    Thin wrapper around Fernet for encrypting/decrypting secret strings.

    Constructed lazily (see get_secret_box()) so that simply importing this
    module doesn't require SETTINGS_ENCRYPTION_KEY to already be set.
    """

    def __init__(self, encryption_key: Optional[str] = None):
        """
        Args:
            encryption_key: Explicit Fernet key (for testing/dependency
                injection). If not provided, read from the
                SETTINGS_ENCRYPTION_KEY environment variable on first use.
        """
        self._explicit_key = encryption_key
        self._fernet: Optional[Fernet] = None

    @property
    def fernet(self) -> Fernet:
        if self._fernet is None:
            raw_key = self._explicit_key or os.getenv("SETTINGS_ENCRYPTION_KEY")
            if not raw_key:
                raise CryptoConfigError(
                    "SETTINGS_ENCRYPTION_KEY environment variable is required to "
                    "store or read encrypted API keys. Generate one with "
                    "`python -c \"from src.utils.crypto import generate_encryption_key as g; print(g())\"` "
                    "and add it to your .env file."
                )
            self._fernet = Fernet(_load_fernet_key(raw_key))
        return self._fernet

    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt a plaintext secret for storage.

        Args:
            plaintext: The secret string to encrypt (e.g. an API key).

        Returns:
            A str ciphertext token, safe to store directly in a text column.

        Raises:
            CryptoConfigError: If SETTINGS_ENCRYPTION_KEY is unset/invalid.
            ValueError: If plaintext is empty.
        """
        if plaintext is None or plaintext == "":
            raise ValueError("Cannot encrypt an empty value")
        token = self.fernet.encrypt(plaintext.encode("utf-8"))
        return token.decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        """
        Decrypt a ciphertext token produced by encrypt().

        Args:
            ciphertext: The stored ciphertext token.

        Returns:
            The original plaintext secret.

        Raises:
            CryptoConfigError: If SETTINGS_ENCRYPTION_KEY is unset/invalid.
            DecryptionError: If the ciphertext is malformed, was encrypted
                with a different key, or has been tampered with.
        """
        if not ciphertext:
            raise ValueError("Cannot decrypt an empty value")
        try:
            plaintext = self.fernet.decrypt(ciphertext.encode("utf-8"))
        except InvalidToken as exc:
            raise DecryptionError(
                "Could not decrypt value -- it may have been encrypted with a "
                "different SETTINGS_ENCRYPTION_KEY, or is corrupted."
            ) from exc
        return plaintext.decode("utf-8")


# Module-level singleton, constructed lazily on first attribute access so
# importing this module never requires SETTINGS_ENCRYPTION_KEY to be set yet.
_secret_box: Optional[SecretBox] = None


def get_secret_box() -> SecretBox:
    """Get the global SecretBox instance, constructing it on first use."""
    global _secret_box
    if _secret_box is None:
        _secret_box = SecretBox()
    return _secret_box


def encrypt_secret(plaintext: str) -> str:
    """Module-level convenience wrapper around get_secret_box().encrypt()."""
    return get_secret_box().encrypt(plaintext)


def decrypt_secret(ciphertext: str) -> str:
    """Module-level convenience wrapper around get_secret_box().decrypt()."""
    return get_secret_box().decrypt(ciphertext)
