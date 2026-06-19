"""
Tests for Property 20: Logging Completeness.

For any user action or system operation in the platform, a corresponding
structured log entry shall be written containing, at minimum: timestamp,
level, component, action, and (when relevant) user_session/duration_ms/
details/exception info -- and ERROR-level events shall always appear in the
dedicated error log while never being suppressed from it by level filtering.

Covers src/utils/logging.py: setup_logging, get_logger, log_event,
log_duration, and StructuredFormatter.

**Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5**
"""

import json
import logging
import os
import sys
import tempfile
import time

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

import pytest

import src.utils.logging as logging_module
from src.utils.logging import (
    StructuredFormatter,
    get_logger,
    log_duration,
    log_event,
    setup_logging,
)


@pytest.fixture
def fresh_logging_state():
    """
    Each test gets its own temp log directory and a reset `_CONFIGURED` flag,
    since `setup_logging` is deliberately idempotent (safe to call multiple
    times in the real app) and would otherwise silently no-op across tests
    that each want their own handlers/log files.
    """
    tmp_dir = tempfile.mkdtemp()
    original_configured = logging_module._CONFIGURED
    original_handlers = logging.getLogger().handlers[:]
    logging_module._CONFIGURED = False
    yield tmp_dir
    logging_module._CONFIGURED = original_configured
    root = logging.getLogger()
    root.handlers.clear()
    root.handlers.extend(original_handlers)


class TestStructuredFormatterCompleteness:
    """The formatter must always include the required fields."""

    def _format(self, level=logging.INFO, action="did_a_thing", **extra):
        record = logging.LogRecord(
            name="test_component", level=level, pathname=__file__, lineno=1,
            msg=action, args=(), exc_info=None,
        )
        for k, v in extra.items():
            setattr(record, k, v)
        return json.loads(StructuredFormatter().format(record))

    def test_required_fields_always_present(self):
        payload = self._format()
        for field in ("timestamp", "level", "component", "action"):
            assert field in payload, f"Structured log entry missing required field: {field}"

    def test_component_defaults_to_logger_name_when_not_set(self):
        payload = self._format()
        assert payload["component"] == "test_component"

    def test_component_uses_explicit_extra_when_provided(self):
        payload = self._format(component="research_engine")
        assert payload["component"] == "research_engine"

    def test_user_session_and_duration_included_when_provided(self):
        payload = self._format(user_session="sess-123", duration_ms=42.5,
                                details={"company": "Acme"})
        assert payload["user_session"] == "sess-123"
        assert payload["duration_ms"] == 42.5
        assert payload["details"] == {"company": "Acme"}

    def test_none_fields_are_dropped_for_compact_output(self):
        payload = self._format()
        assert "user_session" not in payload
        assert "duration_ms" not in payload
        assert "details" not in payload

    def test_exception_info_included_when_present(self):
        record = logging.LogRecord(
            name="test_component", level=logging.ERROR, pathname=__file__, lineno=1,
            msg="failure", args=(), exc_info=None,
        )
        try:
            raise ValueError("boom")
        except ValueError:
            record.exc_info = sys.exc_info()
        payload = json.loads(StructuredFormatter().format(record))
        assert "exception" in payload
        assert "ValueError" in payload["exception"]
        assert "boom" in payload["exception"]

    def test_output_is_single_line_valid_json(self):
        """Required for log aggregation tooling to parse line-by-line."""
        record = logging.LogRecord(
            name="c", level=logging.INFO, pathname=__file__, lineno=1,
            msg="x", args=(), exc_info=None,
        )
        formatted = StructuredFormatter().format(record)
        assert "\n" not in formatted
        json.loads(formatted)  # raises if not valid JSON


class TestSetupLoggingCompleteness:
    """setup_logging must wire up rotating info/error handlers correctly."""

    def test_creates_log_directory_and_files_on_first_write(self, fresh_logging_state):
        tmp_dir = fresh_logging_state
        setup_logging(log_dir=tmp_dir)
        logger = get_logger("test_setup")
        logger.info("hello")
        for handler in logging.getLogger().handlers:
            if hasattr(handler, "flush"):
                handler.flush()

        assert os.path.exists(os.path.join(tmp_dir, "app.log"))
        assert os.path.exists(os.path.join(tmp_dir, "error.log"))

    def test_info_level_goes_to_app_log_not_error_log(self, fresh_logging_state):
        tmp_dir = fresh_logging_state
        setup_logging(log_dir=tmp_dir)
        logger = get_logger("test_info_routing")
        log_event(logger, "INFO", "routine_action")
        for handler in logging.getLogger().handlers:
            if hasattr(handler, "flush"):
                handler.flush()

        with open(os.path.join(tmp_dir, "app.log")) as f:
            app_contents = f.read()
        with open(os.path.join(tmp_dir, "error.log")) as f:
            error_contents = f.read()

        assert "routine_action" in app_contents
        assert "routine_action" not in error_contents

    def test_error_level_goes_to_both_app_log_and_error_log(self, fresh_logging_state):
        tmp_dir = fresh_logging_state
        setup_logging(log_dir=tmp_dir)
        logger = get_logger("test_error_routing")
        log_event(logger, "ERROR", "failure_action")
        for handler in logging.getLogger().handlers:
            if hasattr(handler, "flush"):
                handler.flush()

        with open(os.path.join(tmp_dir, "app.log")) as f:
            app_contents = f.read()
        with open(os.path.join(tmp_dir, "error.log")) as f:
            error_contents = f.read()

        # The MaxLevelFilter on the info handler keeps ERROR out of app.log;
        # the dedicated error handler always captures it.
        assert "failure_action" not in app_contents
        assert "failure_action" in error_contents

    def test_idempotent_does_not_duplicate_handlers(self, fresh_logging_state):
        tmp_dir = fresh_logging_state
        setup_logging(log_dir=tmp_dir)
        handler_count_after_first = len(logging.getLogger().handlers)
        setup_logging(log_dir=tmp_dir)
        handler_count_after_second = len(logging.getLogger().handlers)
        assert handler_count_after_first == handler_count_after_second

    def test_get_logger_auto_configures_if_not_yet_configured(self, fresh_logging_state):
        # Don't call setup_logging explicitly -- get_logger should do it lazily.
        logger = get_logger("auto_configured_component")
        assert logging_module._CONFIGURED is True
        assert logger.name == "auto_configured_component"


def _attach_capture_handler():
    """
    setup_logging() clears the root logger's handlers on every call (by
    design, so repeated calls don't pile up duplicate handlers in the real
    app). That means pytest's own `caplog` handler -- which is also attached
    to the root logger -- gets wiped out the moment a test calls
    setup_logging(). So instead of relying on `caplog`, attach a small
    in-memory list-handler directly, *after* setup_logging() has run, and
    read records off of it.
    """
    captured = []

    class _ListHandler(logging.Handler):
        def emit(self, record):
            captured.append(record)

    handler = _ListHandler()
    handler.setLevel(logging.DEBUG)
    logging.getLogger().addHandler(handler)
    return captured


class TestLogEventCompleteness:
    """log_event must always pass through the documented structured fields."""

    def test_log_event_emits_with_all_fields(self, fresh_logging_state):
        setup_logging(log_dir=fresh_logging_state)
        captured = _attach_capture_handler()
        logger = get_logger("test_log_event")
        log_event(
            logger, "INFO", "company_researched",
            user_session="sess-abc", duration_ms=12.3,
            details={"company": "Acme"},
        )
        assert len(captured) >= 1
        record = captured[-1]
        assert record.action == "company_researched"
        assert record.user_session == "sess-abc"
        assert record.duration_ms == 12.3
        assert record.details == {"company": "Acme"}

    def test_log_event_defaults_level_to_info_for_unknown_level_name(self, fresh_logging_state):
        setup_logging(log_dir=fresh_logging_state)
        captured = _attach_capture_handler()
        logger = get_logger("test_unknown_level")
        log_event(logger, "NOT_A_REAL_LEVEL", "some_action")
        assert captured[-1].levelno == logging.INFO


class TestLogDurationCompleteness:
    """log_duration must log on both the success and exception paths."""

    def test_success_path_logs_with_measured_duration(self, fresh_logging_state):
        setup_logging(log_dir=fresh_logging_state)
        captured = _attach_capture_handler()
        logger = get_logger("test_duration_success")
        with log_duration(logger, "openai_call", user_session="sess-1"):
            time.sleep(0.01)

        record = captured[-1]
        assert record.action == "openai_call"
        assert record.user_session == "sess-1"
        assert record.duration_ms is not None
        assert record.duration_ms > 0

    def test_exception_path_logs_error_and_reraises(self, fresh_logging_state):
        setup_logging(log_dir=fresh_logging_state)
        captured = _attach_capture_handler()
        logger = get_logger("test_duration_failure")

        with pytest.raises(ValueError):
            with log_duration(logger, "risky_call"):
                raise ValueError("simulated failure")

        record = captured[-1]
        assert record.levelno == logging.ERROR
        assert record.action == "risky_call"
        assert record.duration_ms is not None
        assert record.details["error"] == "simulated failure"
        assert record.details["error_type"] == "ValueError"

    def test_exception_path_writes_to_error_log_file(self, fresh_logging_state):
        tmp_dir = fresh_logging_state
        setup_logging(log_dir=tmp_dir)
        logger = get_logger("test_duration_error_file")

        with pytest.raises(RuntimeError):
            with log_duration(logger, "db_write"):
                raise RuntimeError("disk full")

        for handler in logging.getLogger().handlers:
            if hasattr(handler, "flush"):
                handler.flush()

        with open(os.path.join(tmp_dir, "error.log")) as f:
            error_contents = f.read()
        assert "db_write" in error_contents
        assert "disk full" in error_contents


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
