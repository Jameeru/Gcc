"""
Structured logging setup for the GCC Research Intelligence Platform.

Provides rotating file handlers with separate info/error logs, a JSON-structured
log format (timestamp, level, component, user_session, action, duration_ms,
details), and a small helper API for emitting structured log events from
anywhere in the application.

**Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5**
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Generator, Optional

# Directory where rotating log files are written. Overridable via LOG_DIR env var
# so tests / containers can redirect logs without touching application code.
LOG_DIR = os.getenv("LOG_DIR", os.path.join(os.getcwd(), "logs"))

_CONFIGURED = False


class StructuredFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects.

    Matches the LOG_FORMAT defined in design.md:
    timestamp, level, component, user_session, action, duration_ms, details.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "component": getattr(record, "component", record.name),
            "user_session": getattr(record, "user_session", None),
            "action": getattr(record, "action", record.getMessage()),
            "duration_ms": getattr(record, "duration_ms", None),
            "details": getattr(record, "details", None),
        }

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        # Drop None values for compact, readable logs.
        payload = {k: v for k, v in payload.items() if v is not None}
        return json.dumps(payload, default=str)


class _MaxLevelFilter(logging.Filter):
    """Allows only records below a given level through (used to keep INFO log clean)."""

    def __init__(self, max_level: int) -> None:
        super().__init__()
        self.max_level = max_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno < self.max_level


def setup_logging(
    log_level: str = "INFO",
    log_dir: Optional[str] = None,
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 5,
) -> None:
    """
    Configure application-wide structured logging.

    Sets up three handlers on the root logger:
      - Rotating file handler for INFO and above -> logs/app.log
      - Rotating file handler for ERROR and above only -> logs/error.log
      - Console handler (INFO and above) for local development visibility

    Safe to call multiple times; only configures handlers once per process.

    Args:
        log_level: Minimum level to log (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_dir: Directory to write rotating log files to. Defaults to ./logs.
        max_bytes: Max size per log file before rotation.
        backup_count: Number of rotated backups to keep.

    **Validates: Requirements 11.3, 11.4**
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    directory = log_dir or LOG_DIR
    os.makedirs(directory, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    formatter = StructuredFormatter()

    info_handler = logging.handlers.RotatingFileHandler(
        os.path.join(directory, "app.log"),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    info_handler.setLevel(logging.INFO)
    info_handler.addFilter(_MaxLevelFilter(logging.ERROR))
    info_handler.setFormatter(formatter)

    error_handler = logging.handlers.RotatingFileHandler(
        os.path.join(directory, "error.log"),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    root_logger.handlers.clear()
    root_logger.addHandler(info_handler)
    root_logger.addHandler(error_handler)
    root_logger.addHandler(console_handler)

    _CONFIGURED = True


def get_logger(component: str) -> logging.Logger:
    """
    Get a logger for a specific application component.

    Ensures logging is configured (using sane defaults) the first time
    any component requests a logger, so modules never need to worry
    about initialization order.

    Args:
        component: Name of the component requesting the logger
            (e.g. "research_engine", "cache_manager").

    Returns:
        A standard library Logger bound to the given component name.
    """
    if not _CONFIGURED:
        setup_logging(log_level=os.getenv("LOG_LEVEL", "INFO"))
    return logging.getLogger(component)


def log_event(
    logger: logging.Logger,
    level: str,
    action: str,
    *,
    user_session: Optional[str] = None,
    duration_ms: Optional[float] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Emit a structured log event with consistent fields.

    This is the primary logging entry point for the platform. All user
    actions and system operations should be logged through this function
    (or the `log_duration` context manager below) so that every entry
    carries timestamp, session, action, and contextual details.

    Args:
        logger: Logger instance (typically from get_logger()).
        level: Log level name ("INFO", "WARNING", "ERROR", etc.).
        action: Short description of the action performed.
        user_session: Session identifier for the acting user, if any.
        duration_ms: Execution duration in milliseconds, if measured.
        details: Arbitrary additional context (will be JSON-serialized).

    **Validates: Requirements 11.1, 11.2, 11.5**
    """
    log_level = getattr(logging, level.upper(), logging.INFO)
    logger.log(
        log_level,
        action,
        extra={
            "component": logger.name,
            "user_session": user_session,
            "action": action,
            "duration_ms": duration_ms,
            "details": details,
        },
    )


@contextmanager
def log_duration(
    logger: logging.Logger,
    action: str,
    *,
    user_session: Optional[str] = None,
    level_on_success: str = "INFO",
) -> Generator[None, None, None]:
    """
    Context manager that logs an action's outcome and execution time.

    On success, logs `level_on_success` with the measured duration. On
    exception, logs an ERROR with the duration and exception details, then
    re-raises so calling code can still handle the failure.

    Usage:
        with log_duration(logger, "openai_research_call", user_session=sid):
            result = call_openai(...)

    **Validates: Requirements 11.2, 11.5**
    """
    start = time.perf_counter()
    try:
        yield
    except Exception as exc:
        duration_ms = (time.perf_counter() - start) * 1000
        log_event(
            logger,
            "ERROR",
            action,
            user_session=user_session,
            duration_ms=duration_ms,
            details={"error": str(exc), "error_type": type(exc).__name__},
        )
        raise
    else:
        duration_ms = (time.perf_counter() - start) * 1000
        log_event(
            logger,
            level_on_success,
            action,
            user_session=user_session,
            duration_ms=duration_ms,
        )
