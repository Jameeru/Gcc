"""
Security helpers for the GCC Research Intelligence Platform.

Provides bcrypt-based passcode hashing/verification and session token
generation, used by the authentication component and the passcode seeding
script. Keeping this isolated from authentication.py (which depends on
Streamlit) lets these helpers be unit tested and reused by CLI scripts.

**Validates: Requirements 1.1, 14.6**
"""

from __future__ import annotations

import secrets

import bcrypt


def hash_passcode(passcode: str) -> str:
    """
    Hash a plaintext passcode for storage using bcrypt.

    Args:
        passcode: The plaintext passcode to hash.

    Returns:
        A bcrypt hash string, safe to store in the Users.passcode column.

    Raises:
        ValueError: If the passcode is empty.
    """
    if not passcode or not passcode.strip():
        raise ValueError("Passcode cannot be empty")
    hashed = bcrypt.hashpw(passcode.encode("utf-8"), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_passcode(passcode: str, hashed: str) -> bool:
    """
    Verify a plaintext passcode against a stored bcrypt hash.

    Args:
        passcode: The plaintext passcode entered by the user.
        hashed: The bcrypt hash retrieved from the database.

    Returns:
        True if the passcode matches the hash, False otherwise (including
        on malformed input rather than raising, since this sits on the
        authentication hot path and must fail closed).
    """
    if not passcode or not hashed:
        return False
    try:
        return bcrypt.checkpw(passcode.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def generate_session_token() -> str:
    """
    Generate a cryptographically secure random session token.

    Returns:
        A URL-safe random token suitable for use as a session identifier.
    """
    return secrets.token_urlsafe(32)
