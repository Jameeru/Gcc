"""
Unit tests for authentication flows.

This module implements comprehensive unit tests for authentication functionality
including passcode validation, session management, and error handling.

**Validates: Requirements 1.2, 1.3, 14.4**
"""

import pytest
from unittest.mock import Mock, patch, MagicMock, call
from datetime import datetime, timezone, timedelta
import secrets
import sys
import os
from contextlib import contextmanager

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# NOTE: this module used to do `sys.modules['streamlit'] = Mock()` here to
# avoid needing a real Streamlit runtime at import time. That's unnecessary
# -- importing `streamlit` and `src.components.authentication` works fine
# with the real package (see the per-test `patch('streamlit.session_state',
# ...)` / `patch('streamlit.form')` etc. fixtures and tests below, which
# already mock only what's actually called, scoped to each test). The old
# approach permanently overwrote `sys.modules['streamlit']` for the rest of
# the pytest process with no teardown, so every test file collected
# afterward (alphabetically: test_column_detection_properties.py,
# test_login_ui_component.py, test_processing_order_properties.py,
# test_progress_accuracy_properties.py, test_results_processor.py,
# test_stop_resume_properties.py, ...) ended up importing the *same* Mock
# instance as `streamlit`, so any later module-level `import streamlit as
# st` followed by `st.session_state[...] = ...` failed with
# "TypeError: 'Mock' object does not support item assignment" -- but only
# when the full suite was run together, since collection order matters.
from src.utils.security import hash_passcode, verify_passcode

from src.components.authentication import SessionManager, SessionInfo, create_user_with_passcode
from src.models.schemas import User


class TestAuthenticationFlows:
    """Unit tests for authentication flow scenarios."""
    
    @pytest.fixture
    def mock_db_session(self):
        """Mock database session for testing."""
        session = Mock()
        session.query.return_value.filter.return_value.all.return_value = []
        session.query.return_value.filter.return_value.first.return_value = None
        session.commit.return_value = None
        session.add.return_value = None
        session.flush.return_value = None
        return session
    
    @pytest.fixture
    def mock_db_manager(self, mock_db_session):
        """Mock database manager for testing."""
        db_manager = Mock()
        
        @contextmanager
        def get_session():
            yield mock_db_session
        
        db_manager.get_session = get_session
        return db_manager
    
    @pytest.fixture
    def session_manager(self):
        """Create session manager instance for testing."""
        with patch('src.components.authentication.db_manager'), \
             patch('src.components.authentication.get_config') as mock_config:
            
            # Mock configuration
            mock_app_config = Mock()
            mock_app_config.session_timeout_hours = 24
            mock_config.return_value.app = mock_app_config
            
            return SessionManager()


class TestValidPasscodeScenarios:
    """Test valid passcode authentication scenarios."""
    
    @pytest.fixture
    def mock_streamlit_session(self):
        """Mock Streamlit session state."""
        session_state = {}
        with patch('streamlit.session_state', session_state):
            yield session_state
    
    @pytest.fixture
    def session_manager(self):
        """Create session manager instance for testing."""
        with patch('src.components.authentication.db_manager'), \
             patch('src.components.authentication.get_config') as mock_config:
            
            # Mock configuration
            mock_app_config = Mock()
            mock_app_config.session_timeout_hours = 24
            mock_config.return_value.app = mock_app_config
            
            return SessionManager()
    
    @pytest.fixture
    def mock_streamlit_session(self):
        """Mock Streamlit session state."""
        session_state = {}
        with patch('streamlit.session_state', session_state):
            yield session_state
    
    @pytest.fixture
    def valid_user(self):
        """Create a valid test user."""
        user = Mock(spec=User)
        user.id = 1
        user.passcode = hash_passcode("valid_passcode_123")
        user.is_active = True
        user.created_at = datetime.now(timezone.utc)
        user.last_login = None
        return user
    
    def test_authenticate_valid_passcode_success(self, session_manager, mock_streamlit_session, valid_user):
        """Test successful authentication with valid passcode."""
        test_passcode = "valid_passcode_123"
        
        with patch.object(session_manager, '_get_user_by_passcode', return_value=valid_user), \
             patch.object(session_manager, '_update_last_login'), \
             patch.object(session_manager, '_generate_session_id', return_value="test_session_123"):
            
            # Authenticate user
            result = session_manager.authenticate_user(test_passcode)
            
            # Verify authentication succeeded
            assert result is True, "Authentication should succeed with valid passcode"
            
            # Verify session state was set
            assert SessionManager.AUTHENTICATED_KEY in mock_streamlit_session
            assert mock_streamlit_session[SessionManager.AUTHENTICATED_KEY] is True
            assert SessionManager.USER_KEY in mock_streamlit_session
            assert mock_streamlit_session[SessionManager.USER_KEY] == valid_user.id
            assert SessionManager.SESSION_KEY in mock_streamlit_session
            
            # Verify session info object
            session_info = mock_streamlit_session[SessionManager.SESSION_KEY]
            assert isinstance(session_info, SessionInfo)
            assert session_info.user_id == valid_user.id
            assert session_info.session_id == "test_session_123"
            assert session_info.is_active is True
            assert not session_info.is_expired
    
    def test_authenticate_valid_passcode_with_whitespace(self, session_manager, mock_streamlit_session, valid_user):
        """Test authentication with valid passcode containing whitespace."""
        test_passcode = "  valid_passcode_123  "  # Leading/trailing spaces
        
        with patch.object(session_manager, '_get_user_by_passcode', return_value=valid_user), \
             patch.object(session_manager, '_update_last_login'), \
             patch.object(session_manager, '_generate_session_id', return_value="test_session_456"):
            
            # Authenticate user
            result = session_manager.authenticate_user(test_passcode)
            
            # Verify authentication succeeded (whitespace should be stripped)
            assert result is True, "Authentication should succeed with whitespace-padded valid passcode"
    
    def test_session_creation_properties(self, session_manager, mock_streamlit_session, valid_user):
        """Test that session creation sets correct properties."""
        test_passcode = "valid_passcode_123"
        
        with patch.object(session_manager, '_get_user_by_passcode', return_value=valid_user), \
             patch.object(session_manager, '_update_last_login'), \
             patch.object(session_manager, '_generate_session_id', return_value="session_789"):
            
            # Capture the time before authentication
            before_auth = datetime.now(timezone.utc)
            
            # Authenticate user
            result = session_manager.authenticate_user(test_passcode)
            
            # Capture the time after authentication
            after_auth = datetime.now(timezone.utc)
            
            assert result is True
            
            # Get session info
            session_info = mock_streamlit_session[SessionManager.SESSION_KEY]
            
            # Verify session timing
            assert before_auth <= session_info.created_at <= after_auth
            assert session_info.expires_at > session_info.created_at
            
            # Verify session duration (should be approximately 24 hours)
            duration = session_info.expires_at - session_info.created_at
            expected_duration = timedelta(hours=24)
            tolerance = timedelta(minutes=1)  # Allow 1 minute tolerance
            
            assert abs(duration - expected_duration) < tolerance
    
    def test_update_last_login_called(self, session_manager, mock_streamlit_session, valid_user):
        """Test that last login timestamp is updated on successful authentication."""
        test_passcode = "valid_passcode_123"
        
        with patch.object(session_manager, '_get_user_by_passcode', return_value=valid_user), \
             patch.object(session_manager, '_update_last_login') as mock_update, \
             patch.object(session_manager, '_generate_session_id', return_value="session_abc"):
            
            # Authenticate user
            result = session_manager.authenticate_user(test_passcode)
            
            assert result is True
            
            # Verify last login update was called
            mock_update.assert_called_once_with(valid_user.id)


class TestInvalidPasscodeScenarios:
    """Test invalid passcode authentication scenarios."""
    
    @pytest.fixture
    def mock_streamlit_session(self):
        """Mock Streamlit session state."""
        session_state = {}
        with patch('streamlit.session_state', session_state):
            yield session_state
    
    @pytest.fixture
    def session_manager(self):
        """Create session manager instance for testing."""
        with patch('src.components.authentication.db_manager'), \
             patch('src.components.authentication.get_config') as mock_config:
            
            # Mock configuration
            mock_app_config = Mock()
            mock_app_config.session_timeout_hours = 24
            mock_config.return_value.app = mock_app_config
            
            return SessionManager()
    
    @pytest.fixture
    def mock_streamlit_session(self):
        """Mock Streamlit session state."""
        session_state = {}
        with patch('streamlit.session_state', session_state):
            yield session_state
    
    def test_authenticate_wrong_passcode_fails(self, session_manager, mock_streamlit_session):
        """Test authentication failure with incorrect passcode."""
        wrong_passcode = "wrong_passcode_123"
        
        with patch.object(session_manager, '_get_user_by_passcode', return_value=None):
            # Authenticate with wrong passcode
            result = session_manager.authenticate_user(wrong_passcode)
            
            # Verify authentication failed
            assert result is False, "Authentication should fail with wrong passcode"
            
            # Verify session state was not set
            assert SessionManager.AUTHENTICATED_KEY not in mock_streamlit_session
            assert SessionManager.USER_KEY not in mock_streamlit_session
            assert SessionManager.SESSION_KEY not in mock_streamlit_session
    
    def test_authenticate_empty_passcode_fails(self, session_manager, mock_streamlit_session):
        """Test authentication failure with empty passcode."""
        empty_passcodes = ["", "   ", "\t", "\n", None]
        
        for empty_passcode in empty_passcodes:
            # Clear session state between tests
            mock_streamlit_session.clear()
            
            # Authenticate with empty passcode
            result = session_manager.authenticate_user(empty_passcode)
            
            # Verify authentication failed
            assert result is False, f"Authentication should fail with empty passcode: {repr(empty_passcode)}"
            
            # Verify session state was not set
            assert SessionManager.AUTHENTICATED_KEY not in mock_streamlit_session
    
    def test_authenticate_inactive_user_fails(self, session_manager, mock_streamlit_session):
        """Test authentication failure with inactive user."""
        inactive_user = Mock(spec=User)
        inactive_user.id = 2
        inactive_user.passcode = hash_passcode("inactive_user_passcode")
        inactive_user.is_active = False  # User is inactive
        
        test_passcode = "inactive_user_passcode"
        
        with patch.object(session_manager, '_get_user_by_passcode', return_value=None):
            # _get_user_by_passcode should return None for inactive users
            result = session_manager.authenticate_user(test_passcode)
            
            # Verify authentication failed
            assert result is False, "Authentication should fail with inactive user"
            
            # Verify session state was not set
            assert SessionManager.AUTHENTICATED_KEY not in mock_streamlit_session
    
    def test_authenticate_database_error_fails(self, session_manager, mock_streamlit_session):
        """Test authentication failure when database error occurs."""
        test_passcode = "valid_passcode_123"
        
        # Mock database error - _get_user_by_passcode handles exceptions internally and returns None
        with patch.object(session_manager, '_get_user_by_passcode', return_value=None):
            result = session_manager.authenticate_user(test_passcode)
            
            # Verify authentication failed gracefully
            assert result is False, "Authentication should fail gracefully on database error"
            
            # Verify session state was not set
            assert SessionManager.AUTHENTICATED_KEY not in mock_streamlit_session
    
    def test_authenticate_user_not_found_fails(self, session_manager, mock_streamlit_session):
        """Test authentication failure when user is not found in database."""
        nonexistent_passcode = "nonexistent_passcode_123"
        
        with patch.object(session_manager, '_get_user_by_passcode', return_value=None):
            # Authenticate with non-existent user passcode
            result = session_manager.authenticate_user(nonexistent_passcode)
            
            # Verify authentication failed
            assert result is False, "Authentication should fail when user not found"
            
            # Verify session state was not set
            assert SessionManager.AUTHENTICATED_KEY not in mock_streamlit_session


class TestSessionManagement:
    """Test session creation, validation, and expiry logic."""
    
    @pytest.fixture
    def mock_streamlit_session(self):
        """Mock Streamlit session state."""
        session_state = {}
        with patch('streamlit.session_state', session_state):
            yield session_state
    
    @pytest.fixture
    def session_manager(self):
        """Create session manager instance for testing."""
        with patch('src.components.authentication.db_manager'), \
             patch('src.components.authentication.get_config') as mock_config:
            
            # Mock configuration
            mock_app_config = Mock()
            mock_app_config.session_timeout_hours = 24
            mock_config.return_value.app = mock_app_config
            
            return SessionManager()
    
    def test_is_authenticated_with_valid_session(self, session_manager, mock_streamlit_session):
        """Test session validation with active, non-expired session."""
        # Create valid session info
        current_time = datetime.now(timezone.utc)
        session_info = SessionInfo(
            user_id=1,
            session_id="valid_session_123",
            created_at=current_time - timedelta(hours=1),  # 1 hour ago
            expires_at=current_time + timedelta(hours=23),  # 23 hours from now
            is_active=True
        )
        
        # Set up session state
        mock_streamlit_session[SessionManager.AUTHENTICATED_KEY] = True
        mock_streamlit_session[SessionManager.SESSION_KEY] = session_info
        mock_streamlit_session[SessionManager.USER_KEY] = 1
        
        # Test authentication status
        result = session_manager.is_authenticated()
        assert result is True, "Should be authenticated with valid session"
    
    def test_is_authenticated_with_expired_session(self, session_manager, mock_streamlit_session):
        """Test session validation with expired session."""
        # Create expired session info
        current_time = datetime.now(timezone.utc)
        session_info = SessionInfo(
            user_id=1,
            session_id="expired_session_123",
            created_at=current_time - timedelta(hours=25),  # 25 hours ago
            expires_at=current_time - timedelta(hours=1),   # 1 hour ago (expired)
            is_active=True
        )
        
        # Set up session state
        mock_streamlit_session[SessionManager.AUTHENTICATED_KEY] = True
        mock_streamlit_session[SessionManager.SESSION_KEY] = session_info
        mock_streamlit_session[SessionManager.USER_KEY] = 1
        
        # Test authentication status
        result = session_manager.is_authenticated()
        assert result is False, "Should not be authenticated with expired session"
        
        # Verify session was cleared
        assert SessionManager.AUTHENTICATED_KEY not in mock_streamlit_session
        assert SessionManager.SESSION_KEY not in mock_streamlit_session
        assert SessionManager.USER_KEY not in mock_streamlit_session
    
    def test_is_authenticated_with_inactive_session(self, session_manager, mock_streamlit_session):
        """Test session validation with inactive session."""
        # Create inactive session info
        current_time = datetime.now(timezone.utc)
        session_info = SessionInfo(
            user_id=1,
            session_id="inactive_session_123",
            created_at=current_time - timedelta(hours=1),
            expires_at=current_time + timedelta(hours=23),
            is_active=False  # Inactive session
        )
        
        # Set up session state
        mock_streamlit_session[SessionManager.AUTHENTICATED_KEY] = True
        mock_streamlit_session[SessionManager.SESSION_KEY] = session_info
        mock_streamlit_session[SessionManager.USER_KEY] = 1
        
        # Test authentication status
        result = session_manager.is_authenticated()
        assert result is False, "Should not be authenticated with inactive session"
        
        # Verify session was cleared
        assert SessionManager.AUTHENTICATED_KEY not in mock_streamlit_session
    
    def test_is_authenticated_no_session(self, session_manager, mock_streamlit_session):
        """Test authentication status with no session."""
        # Empty session state
        result = session_manager.is_authenticated()
        assert result is False, "Should not be authenticated with no session"
    
    def test_get_session_info_success(self, session_manager, mock_streamlit_session):
        """Test retrieving valid session information."""
        # Create valid session info
        current_time = datetime.now(timezone.utc)
        session_info = SessionInfo(
            user_id=1,
            session_id="valid_session_456",
            created_at=current_time - timedelta(hours=1),
            expires_at=current_time + timedelta(hours=23),
            is_active=True
        )
        
        # Set up session state
        mock_streamlit_session[SessionManager.AUTHENTICATED_KEY] = True
        mock_streamlit_session[SessionManager.SESSION_KEY] = session_info
        
        # Get session info
        result = session_manager.get_session_info()
        assert result == session_info, "Should return correct session info"
    
    def test_get_session_info_not_authenticated(self, session_manager, mock_streamlit_session):
        """Test retrieving session information when not authenticated."""
        # No session state set
        result = session_manager.get_session_info()
        assert result is None, "Should return None when not authenticated"
    
    def test_get_current_user_id_success(self, session_manager, mock_streamlit_session):
        """Test retrieving current user ID from valid session."""
        # Create valid session info
        current_time = datetime.now(timezone.utc)
        session_info = SessionInfo(
            user_id=42,
            session_id="user_session_789",
            created_at=current_time - timedelta(hours=1),
            expires_at=current_time + timedelta(hours=23),
            is_active=True
        )
        
        # Set up session state
        mock_streamlit_session[SessionManager.AUTHENTICATED_KEY] = True
        mock_streamlit_session[SessionManager.SESSION_KEY] = session_info
        mock_streamlit_session[SessionManager.USER_KEY] = 42
        
        # Get current user ID
        result = session_manager.get_current_user_id()
        assert result == 42, "Should return correct user ID"
    
    def test_get_current_user_id_not_authenticated(self, session_manager, mock_streamlit_session):
        """Test retrieving user ID when not authenticated."""
        # No session state set
        result = session_manager.get_current_user_id()
        assert result is None, "Should return None when not authenticated"
    
    def test_logout_clears_session(self, session_manager, mock_streamlit_session):
        """Test that logout properly clears session state."""
        # Set up active session
        current_time = datetime.now(timezone.utc)
        session_info = SessionInfo(
            user_id=1,
            session_id="logout_test_session",
            created_at=current_time - timedelta(hours=1),
            expires_at=current_time + timedelta(hours=23),
            is_active=True
        )
        
        mock_streamlit_session[SessionManager.AUTHENTICATED_KEY] = True
        mock_streamlit_session[SessionManager.SESSION_KEY] = session_info
        mock_streamlit_session[SessionManager.USER_KEY] = 1
        
        # Verify session is active
        assert session_manager.is_authenticated() is True
        
        # Logout
        session_manager.logout()
        
        # Verify session was cleared
        assert SessionManager.AUTHENTICATED_KEY not in mock_streamlit_session
        assert SessionManager.SESSION_KEY not in mock_streamlit_session
        assert SessionManager.USER_KEY not in mock_streamlit_session
        
        # Verify no longer authenticated
        assert session_manager.is_authenticated() is False
    
    def test_extend_session_success(self, session_manager, mock_streamlit_session):
        """Test successful session extension."""
        # Create session close to expiry
        current_time = datetime.now(timezone.utc)
        original_expiry = current_time + timedelta(minutes=30)
        session_info = SessionInfo(
            user_id=1,
            session_id="extend_session_test",
            created_at=current_time - timedelta(hours=23, minutes=30),
            expires_at=original_expiry,
            is_active=True
        )
        
        mock_streamlit_session[SessionManager.SESSION_KEY] = session_info
        
        # Extend session
        result = session_manager.extend_session()
        assert result is True, "Session extension should succeed"
        
        # Verify expiry time was extended
        updated_session = mock_streamlit_session[SessionManager.SESSION_KEY]
        assert updated_session.expires_at > original_expiry, "Session should be extended"
        
        # Verify extension is approximately 24 hours from now
        expected_expiry = current_time + timedelta(hours=24)
        tolerance = timedelta(minutes=1)
        assert abs(updated_session.expires_at - expected_expiry) < tolerance
    
    def test_extend_session_no_session(self, session_manager, mock_streamlit_session):
        """Test session extension when no session exists."""
        # No session in state
        result = session_manager.extend_session()
        assert result is False, "Session extension should fail with no session"
    
    def test_get_session_status_authenticated(self, session_manager, mock_streamlit_session):
        """Test session status for authenticated user."""
        # Create valid session
        current_time = datetime.now(timezone.utc)
        session_info = SessionInfo(
            user_id=1,
            session_id="status_test_session",
            created_at=current_time - timedelta(hours=1),
            expires_at=current_time + timedelta(hours=23),
            is_active=True
        )
        
        mock_streamlit_session[SessionManager.AUTHENTICATED_KEY] = True
        mock_streamlit_session[SessionManager.SESSION_KEY] = session_info
        
        # Get session status
        status = session_manager.get_session_status()
        
        # Verify status content
        assert status["authenticated"] is True
        assert status["user_id"] == 1
        assert status["session_id"] == "status_test_session"
        assert status["is_expired"] is False
        assert "created_at" in status
        assert "expires_at" in status
        assert "time_remaining" in status
    
    def test_get_session_status_not_authenticated(self, session_manager, mock_streamlit_session):
        """Test session status for non-authenticated user."""
        # No session in state
        status = session_manager.get_session_status()
        
        # Verify status content
        assert status["authenticated"] is False
        assert status["user_id"] is None
        assert status["session_id"] is None
        assert status["created_at"] is None
        assert status["expires_at"] is None
        assert status["time_remaining"] is None
        assert status["is_expired"] is True


class TestErrorMessageDisplay:
    """Test error message display and UI feedback."""
    
    def test_render_login_page_empty_passcode_error(self):
        """Test login page shows error for empty passcode."""
        from src.components.authentication import render_login_page
        
        with patch('streamlit.form') as mock_form, \
             patch('streamlit.text_input', return_value=""), \
             patch('streamlit.form_submit_button', return_value=True), \
             patch('streamlit.error') as mock_error, \
             patch('streamlit.markdown'), \
             patch('streamlit.columns', return_value=[MagicMock(), MagicMock(), MagicMock()]):
            
            # Mock form context manager
            mock_form.return_value.__enter__ = Mock()
            mock_form.return_value.__exit__ = Mock()
            
            # Call render_login_page
            result = render_login_page()
            
            # Verify function returned False (authentication failed)
            assert result is False, "Should return False for empty passcode"
            
            # Verify error was displayed
            mock_error.assert_called()
            error_calls = mock_error.call_args_list
            
            # Check that at least one error call mentions passcode requirement
            error_messages = [str(call) for call in error_calls]
            assert any("Passcode Required" in msg or "passcode" in msg.lower() for msg in error_messages)
    
    def test_render_login_page_whitespace_passcode_error(self):
        """Test login page shows error for whitespace-only passcode."""
        from src.components.authentication import render_login_page
        
        whitespace_inputs = ["   ", "\t", "\n", " \t \n "]
        
        for whitespace_input in whitespace_inputs:
            with patch('streamlit.form') as mock_form, \
                 patch('streamlit.text_input', return_value=whitespace_input), \
                 patch('streamlit.form_submit_button', return_value=True), \
                 patch('streamlit.error') as mock_error, \
                 patch('streamlit.markdown'), \
                 patch('streamlit.columns', return_value=[MagicMock(), MagicMock(), MagicMock()]):
                
                # Mock form context manager
                mock_form.return_value.__enter__ = Mock()
                mock_form.return_value.__exit__ = Mock()
                
                # Call render_login_page
                result = render_login_page()
                
                # Verify function returned False
                assert result is False, f"Should return False for whitespace passcode: {repr(whitespace_input)}"
                
                # Verify error was displayed
                mock_error.assert_called()
    
    def test_render_login_page_authentication_failure_error(self):
        """Test login page shows error for authentication failure."""
        from src.components.authentication import render_login_page
        
        with patch('streamlit.form') as mock_form, \
             patch('streamlit.text_input', return_value="invalid_passcode"), \
             patch('streamlit.form_submit_button', return_value=True), \
             patch('streamlit.error') as mock_error, \
             patch('streamlit.spinner') as mock_spinner, \
             patch('streamlit.markdown'), \
             patch('streamlit.columns', return_value=[MagicMock(), MagicMock(), MagicMock()]), \
             patch('src.components.authentication.SessionManager') as mock_session_manager:
            
            # Mock form context manager
            mock_form.return_value.__enter__ = Mock()
            mock_form.return_value.__exit__ = Mock()
            
            # Mock spinner context manager
            mock_spinner.return_value.__enter__ = Mock()
            mock_spinner.return_value.__exit__ = Mock()
            
            # Mock authentication failure
            mock_manager_instance = Mock()
            mock_manager_instance.authenticate_user.return_value = False
            mock_session_manager.return_value = mock_manager_instance
            
            # Call render_login_page
            result = render_login_page()
            
            # Verify function returned False
            assert result is False, "Should return False for authentication failure"
            
            # Verify error was displayed
            mock_error.assert_called()
            error_calls = mock_error.call_args_list
            
            # Check that error message mentions authentication failure
            error_messages = [str(call) for call in error_calls]
            assert any("Authentication Failed" in msg or "incorrect" in msg.lower() for msg in error_messages)
    
    def test_render_login_page_system_error_handling(self):
        """Test login page handles system errors gracefully."""
        from src.components.authentication import render_login_page
        
        with patch('streamlit.form') as mock_form, \
             patch('streamlit.text_input', return_value="test_passcode"), \
             patch('streamlit.form_submit_button', return_value=True), \
             patch('streamlit.error') as mock_error, \
             patch('streamlit.spinner') as mock_spinner, \
             patch('streamlit.markdown'), \
             patch('streamlit.columns', return_value=[MagicMock(), MagicMock(), MagicMock()]), \
             patch('src.components.authentication.SessionManager') as mock_session_manager:
            
            # Mock form and spinner context managers
            mock_form.return_value.__enter__ = Mock()
            mock_form.return_value.__exit__ = Mock()
            mock_spinner.return_value.__enter__ = Mock()
            mock_spinner.return_value.__exit__ = Mock()
            
            # Mock system exception during authentication
            mock_manager_instance = Mock()
            mock_manager_instance.authenticate_user.side_effect = Exception("Database connection failed")
            mock_session_manager.return_value = mock_manager_instance
            
            # Call render_login_page
            result = render_login_page()
            
            # Verify function returned False
            assert result is False, "Should return False for system error"
            
            # Verify error was displayed
            mock_error.assert_called()
            error_calls = mock_error.call_args_list
            
            # Check that error message mentions system error
            error_messages = [str(call) for call in error_calls]
            assert any("System Error" in msg or "error occurred" in msg.lower() for msg in error_messages)
    
    def test_render_login_page_success_feedback(self):
        """Test login page shows success message on successful authentication."""
        from src.components.authentication import render_login_page
        
        with patch('streamlit.form') as mock_form, \
             patch('streamlit.text_input', return_value="valid_passcode"), \
             patch('streamlit.form_submit_button', return_value=True), \
             patch('streamlit.success') as mock_success, \
             patch('streamlit.spinner') as mock_spinner, \
             patch('streamlit.rerun') as mock_rerun, \
             patch('streamlit.markdown'), \
             patch('streamlit.columns', return_value=[MagicMock(), MagicMock(), MagicMock()]), \
             patch('src.components.authentication.SessionManager') as mock_session_manager, \
             patch('time.sleep'):  # Mock the sleep delay
            
            # Mock form and spinner context managers
            mock_form.return_value.__enter__ = Mock()
            mock_form.return_value.__exit__ = Mock()
            mock_spinner.return_value.__enter__ = Mock()
            mock_spinner.return_value.__exit__ = Mock()
            
            # Mock successful authentication
            mock_manager_instance = Mock()
            mock_manager_instance.authenticate_user.return_value = True
            mock_session_manager.return_value = mock_manager_instance
            
            # Call render_login_page
            result = render_login_page()
            
            # Verify success message was displayed
            mock_success.assert_called()
            success_calls = mock_success.call_args_list
            
            # Check that success message mentions successful authentication
            success_messages = [str(call) for call in success_calls]
            assert any("Authenticated" in msg or "Welcome" in msg for msg in success_messages)
            
            # Verify rerun was called to refresh the page
            mock_rerun.assert_called()
    
    def test_render_login_page_loading_feedback(self):
        """Test login page shows loading feedback during authentication."""
        from src.components.authentication import render_login_page
        
        with patch('streamlit.form') as mock_form, \
             patch('streamlit.text_input', return_value="test_passcode"), \
             patch('streamlit.form_submit_button', return_value=True), \
             patch('streamlit.spinner') as mock_spinner, \
             patch('streamlit.error'), \
             patch('streamlit.markdown'), \
             patch('streamlit.columns', return_value=[MagicMock(), MagicMock(), MagicMock()]), \
             patch('src.components.authentication.SessionManager') as mock_session_manager:
            
            # Mock form context manager
            mock_form.return_value.__enter__ = Mock()
            mock_form.return_value.__exit__ = Mock()
            
            # Mock spinner context manager
            mock_spinner.return_value.__enter__ = Mock()
            mock_spinner.return_value.__exit__ = Mock()
            
            # Mock authentication (doesn't matter if it succeeds or fails)
            mock_manager_instance = Mock()
            mock_manager_instance.authenticate_user.return_value = False
            mock_session_manager.return_value = mock_manager_instance
            
            # Call render_login_page
            render_login_page()
            
            # Verify spinner was called with loading message
            mock_spinner.assert_called()
            spinner_calls = mock_spinner.call_args_list
            
            # Check that spinner message indicates authentication in progress
            spinner_messages = [str(call) for call in spinner_calls]
            assert any("Authenticating" in msg or "Verifying" in msg for msg in spinner_messages)


class TestSecurityHelpers:
    """Test security helper functions used in authentication."""
    
    def test_hash_passcode_generates_different_hashes(self):
        """Test that hashing the same passcode twice generates different hashes."""
        passcode = "test_passcode_123"
        
        hash1 = hash_passcode(passcode)
        hash2 = hash_passcode(passcode)
        
        # Hashes should be different due to random salt
        assert hash1 != hash2, "BCrypt should generate different hashes with random salts"
        
        # Both hashes should verify against original passcode
        assert verify_passcode(passcode, hash1), "First hash should verify correctly"
        assert verify_passcode(passcode, hash2), "Second hash should verify correctly"
    
    def test_verify_passcode_correct_password(self):
        """Test passcode verification with correct password."""
        passcode = "correct_password_456"
        hashed = hash_passcode(passcode)
        
        result = verify_passcode(passcode, hashed)
        assert result is True, "Verification should succeed with correct passcode"
    
    def test_verify_passcode_incorrect_password(self):
        """Test passcode verification with incorrect password."""
        correct_passcode = "correct_password_789"
        wrong_passcode = "wrong_password_789"
        
        hashed = hash_passcode(correct_passcode)
        
        result = verify_passcode(wrong_passcode, hashed)
        assert result is False, "Verification should fail with incorrect passcode"
    
    def test_verify_passcode_empty_inputs(self):
        """Test passcode verification with empty inputs."""
        # Empty passcode
        result1 = verify_passcode("", "some_hash")
        assert result1 is False, "Verification should fail with empty passcode"
        
        # Empty hash
        result2 = verify_passcode("some_passcode", "")
        assert result2 is False, "Verification should fail with empty hash"
        
        # Both empty
        result3 = verify_passcode("", "")
        assert result3 is False, "Verification should fail with both empty"
    
    def test_verify_passcode_malformed_hash(self):
        """Test passcode verification with malformed hash."""
        passcode = "test_passcode"
        malformed_hashes = [
            "not_a_hash",
            "invalid_bcrypt_hash",
            "too_short",
            "$2b$12$invalid",
            None
        ]
        
        for malformed_hash in malformed_hashes:
            result = verify_passcode(passcode, malformed_hash)
            assert result is False, f"Verification should fail with malformed hash: {malformed_hash}"
    
    def test_hash_passcode_empty_input(self):
        """Test that hashing empty passcode raises ValueError."""
        empty_passcodes = ["", "   ", "\t", "\n", None]
        
        for empty_passcode in empty_passcodes:
            with pytest.raises(ValueError, match="Passcode cannot be empty"):
                hash_passcode(empty_passcode)


class TestUserCreationUtility:
    """Test user creation utility function."""
    
    @pytest.fixture
    def mock_db_session(self):
        """Mock database session for user creation tests."""
        session = Mock()
        session.query.return_value.filter.return_value.all.return_value = []
        session.add.return_value = None
        session.commit.return_value = None
        session.flush.return_value = None
        return session
    
    @pytest.fixture
    def mock_db_manager(self, mock_db_session):
        """Mock database manager for user creation tests."""
        db_manager = Mock()
        
        @contextmanager
        def get_session():
            yield mock_db_session
        
        db_manager.get_session = get_session
        return db_manager
    
    def test_create_user_with_passcode_success(self, mock_db_manager):
        """Test successful user creation with valid passcode."""
        test_passcode = "new_user_passcode_123"
        
        with patch('src.components.authentication.db_manager', mock_db_manager):
            result = create_user_with_passcode(test_passcode)
            
            # Verify user creation succeeded
            assert result is True, "User creation should succeed with valid passcode"
    
    def test_create_user_with_existing_passcode_fails(self, mock_db_manager, mock_db_session):
        """Test user creation fails when passcode already exists."""
        existing_passcode = "existing_passcode_456"
        
        # Create existing user with the same passcode
        existing_user = Mock(spec=User)
        existing_user.passcode = hash_passcode(existing_passcode)
        existing_user.is_active = True
        
        # Mock database to return existing user
        mock_db_session.query.return_value.filter.return_value.all.return_value = [existing_user]
        
        with patch('src.components.authentication.db_manager', mock_db_manager):
            result = create_user_with_passcode(existing_passcode)
            
            # Verify user creation failed
            assert result is False, "User creation should fail when passcode already exists"
    
    def test_create_user_database_error(self, mock_db_manager, mock_db_session):
        """Test user creation handles database errors gracefully."""
        test_passcode = "database_error_test"
        
        # Mock database error by raising exception during get_session
        def failing_get_session():
            raise Exception("Database connection failed")
        
        mock_db_manager.get_session = failing_get_session
        
        with patch('src.components.authentication.db_manager', mock_db_manager):
            result = create_user_with_passcode(test_passcode)
            
            # Verify user creation failed gracefully
            assert result is False, "User creation should fail gracefully on database error"


class TestSessionInfoClass:
    """Test SessionInfo data class properties and methods."""
    
    def test_session_info_creation(self):
        """Test SessionInfo object creation with valid data."""
        current_time = datetime.now(timezone.utc)
        
        session_info = SessionInfo(
            user_id=1,
            session_id="test_session_123",
            created_at=current_time,
            expires_at=current_time + timedelta(hours=24),
            is_active=True
        )
        
        assert session_info.user_id == 1
        assert session_info.session_id == "test_session_123"
        assert session_info.created_at == current_time
        assert session_info.expires_at == current_time + timedelta(hours=24)
        assert session_info.is_active is True
    
    def test_session_info_is_expired_property(self):
        """Test SessionInfo is_expired property."""
        current_time = datetime.now(timezone.utc)
        
        # Non-expired session
        valid_session = SessionInfo(
            user_id=1,
            session_id="valid_session",
            created_at=current_time - timedelta(hours=1),
            expires_at=current_time + timedelta(hours=23),
            is_active=True
        )
        assert valid_session.is_expired is False
        
        # Expired session
        expired_session = SessionInfo(
            user_id=2,
            session_id="expired_session",
            created_at=current_time - timedelta(hours=25),
            expires_at=current_time - timedelta(hours=1),
            is_active=True
        )
        assert expired_session.is_expired is True
    
    def test_session_info_time_remaining_property(self):
        """Test SessionInfo time_remaining property."""
        current_time = datetime.now(timezone.utc)
        
        # Session with time remaining
        active_session = SessionInfo(
            user_id=1,
            session_id="active_session",
            created_at=current_time - timedelta(hours=1),
            expires_at=current_time + timedelta(hours=5),
            is_active=True
        )
        
        time_remaining = active_session.time_remaining
        expected_remaining = timedelta(hours=5)
        tolerance = timedelta(seconds=1)  # Allow small tolerance for execution time
        
        assert abs(time_remaining - expected_remaining) < tolerance
        
        # Expired session should have zero time remaining
        expired_session = SessionInfo(
            user_id=2,
            session_id="expired_session",
            created_at=current_time - timedelta(hours=25),
            expires_at=current_time - timedelta(hours=1),
            is_active=True
        )
        
        assert expired_session.time_remaining == timedelta(0)


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v"])