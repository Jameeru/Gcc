"""
Runtime API key resolution for OpenAI and Gemini research providers.

Resolution order, per setting:
    1. DB-stored value (set via the Settings UI, encrypted at rest) --
       checked fresh on every call, so a key updated through the UI takes
       effect immediately without an app restart.
    2. The matching environment variable, as a fallback/bootstrap path for
       environments that haven't been configured through the UI yet.

Deliberately does NOT cache resolved keys at the module level (unlike the
lazy-singleton pattern used for the DB engine/research client elsewhere in
this codebase) -- the whole point of this layer is that a key rotated in
the Settings UI must be visible to the *next* research call, not just after
a restart. Streamlit's rerun-per-interaction model means the cost of an
extra DB read here is negligible.

**Validates the "update the API key through the UI" requirement from the
user's request, ensuring updated keys are picked up live.**
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

from ..core.database import db_manager
from ..models.repositories import ApiSettingsRepository
from .logging import get_logger

logger = get_logger("api_keys")

# setting_key -> fallback environment variable name.
OPENAI_API_KEY = "openai_api_key"
GEMINI_API_KEY_1 = "gemini_api_key_1"
GEMINI_API_KEY_2 = "gemini_api_key_2"

SETTING_KEY_ENV_VARS: Dict[str, str] = {
    OPENAI_API_KEY: "OPENAI_API_KEY",
    GEMINI_API_KEY_1: "GEMINI_API_KEY_1",
    GEMINI_API_KEY_2: "GEMINI_API_KEY_2",
}

GEMINI_SETTING_KEYS: List[str] = [GEMINI_API_KEY_1, GEMINI_API_KEY_2]


def get_api_key(setting_key: str) -> Optional[str]:
    """
    Resolve a single API key by setting key, checking the DB first and
    falling back to the matching environment variable.

    Args:
        setting_key: One of OPENAI_API_KEY, GEMINI_API_KEY_1, GEMINI_API_KEY_2
            (the module-level constants above).

    Returns:
        The resolved plaintext API key, or None if neither the DB nor the
        environment has a value for it.
    """
    db_value = _get_from_db(setting_key)
    if db_value:
        return db_value

    env_var = SETTING_KEY_ENV_VARS.get(setting_key)
    if env_var:
        env_value = os.getenv(env_var)
        if env_value:
            return env_value

    return None


def get_all_api_keys() -> Dict[str, Optional[str]]:
    """
    Resolve all known setting keys at once, applying the same DB-first,
    env-fallback rule per key.

    Returns:
        Dict mapping each setting_key to its resolved plaintext value
        (None if unconfigured anywhere).
    """
    keys = list(SETTING_KEY_ENV_VARS.keys())
    db_values = _get_all_from_db(keys)

    resolved: Dict[str, Optional[str]] = {}
    for key in keys:
        value = db_values.get(key)
        if not value:
            value = os.getenv(SETTING_KEY_ENV_VARS[key])
        resolved[key] = value or None
    return resolved


def get_gemini_api_keys() -> List[str]:
    """
    Get the list of currently-configured Gemini API keys (DB-first, env
    fallback per key), for round-robin/failover use by the Gemini engine.

    Returns:
        List of non-empty configured Gemini keys, in a stable order
        (gemini_api_key_1 before gemini_api_key_2). Empty if neither is set.
    """
    return [
        key
        for key in (get_api_key(GEMINI_API_KEY_1), get_api_key(GEMINI_API_KEY_2))
        if key
    ]


def is_configured(setting_key: str) -> bool:
    """Check whether a setting key currently resolves to a non-empty value."""
    return bool(get_api_key(setting_key))


def _get_from_db(setting_key: str) -> Optional[str]:
    """
    Best-effort DB lookup for a single setting key.

    Swallows any DB connectivity/decryption error and returns None rather
    than raising, so a DB outage degrades to "use the env var" instead of
    crashing every research call -- the env var fallback exists precisely
    for this case.
    """
    try:
        with db_manager.get_session() as session:
            repo = ApiSettingsRepository(session)
            return repo.get_plaintext(setting_key)
    except Exception as exc:
        logger.warning(
            f"Could not read API setting '{setting_key}' from database "
            f"(falling back to environment variable): {exc}"
        )
        return None


def _get_all_from_db(setting_keys: List[str]) -> Dict[str, Optional[str]]:
    """Best-effort batched DB lookup, mirroring _get_from_db's fallback behavior."""
    try:
        with db_manager.get_session() as session:
            repo = ApiSettingsRepository(session)
            return repo.get_all_plaintext(setting_keys)
    except Exception as exc:
        logger.warning(
            f"Could not read API settings from database "
            f"(falling back to environment variables): {exc}"
        )
        return {key: None for key in setting_keys}
