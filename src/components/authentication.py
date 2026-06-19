"""
Authentication and session management for the GCC Research Intelligence Platform.

This module provides secure passcode-based authentication, session management,
and automatic session expiry handling for Streamlit applications.
"""

import secrets
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

import streamlit as st
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from ..core.database import db_manager
from ..models.schemas import User
from ..utils.config import get_config
from ..utils.logging import get_logger
from ..utils.security import hash_passcode, verify_passcode

logger = get_logger(__name__)


@dataclass
class SessionInfo:
    """Session information data class."""
    user_id: int
    session_id: str
    created_at: datetime
    expires_at: datetime
    is_active: bool = True

    @property
    def is_expired(self) -> bool:
        """Check if session is expired."""
        return datetime.now(timezone.utc) > self.expires_at

    @property
    def time_remaining(self) -> timedelta:
        """Get remaining session time."""
        if self.is_expired:
            return timedelta(0)
        return self.expires_at - datetime.now(timezone.utc)


class SessionManager:
    """
    Session manager for handling authentication and session state.
    
    Provides secure passcode-based authentication with Streamlit session state
    integration and automatic session expiry handling.
    """

    # Session state keys
    SESSION_KEY = "gcc_session"
    USER_KEY = "gcc_user_id"
    AUTHENTICATED_KEY = "gcc_authenticated"
    
    def __init__(self):
        """Initialize session manager with configuration."""
        self.config = get_config()
        self.session_timeout = timedelta(hours=self.config.app.session_timeout_hours)
    
    def _generate_session_id(self) -> str:
        """
        Generate secure session ID.
        
        Returns:
            Random session ID string.
        """
        return secrets.token_urlsafe(32)
    
    def _get_user_by_passcode(self, passcode: str) -> Optional[User]:
        """
        Retrieve user by passcode from database.

        Passcodes are stored as bcrypt hashes (see ``utils.security``), which
        are salted with a fresh random salt on every hash. That means the
        same plaintext passcode never produces the same hash twice, so we
        cannot look a user up with a direct ``passcode == hash(input)``
        equality filter (the original implementation hashed with a
        passcode-derived salt specifically to make that query work, which
        defeated the point of salting and left passcodes vulnerable to
        offline brute force if the database were ever exposed).

        Instead we fetch all active users and verify the plaintext passcode
        against each stored bcrypt hash with ``verify_passcode``, returning
        the first match. This is the correct way to use bcrypt for lookup
        and is fine at this scale (an internal tool with a handful of
        sales/research users, not a public-facing login with thousands of
        accounts).

        Args:
            passcode: User passcode to lookup.

        Returns:
            User object if found and active, None otherwise.
        """
        try:
            with db_manager.get_session() as session:
                active_users: List[User] = session.query(User).filter(
                    User.is_active == True
                ).all()

                for user in active_users:
                    if verify_passcode(passcode, user.passcode):
                        logger.info(f"User authenticated successfully: user_id={user.id}")
                        return user

                return None

        except SQLAlchemyError as e:
            logger.error(f"Database error during authentication: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error during authentication: {e}")
            return None
    
    def _update_last_login(self, user_id: int) -> None:
        """
        Update user's last login timestamp.
        
        Args:
            user_id: ID of user to update.
        """
        try:
            with db_manager.get_session() as session:
                user = session.query(User).filter(User.id == user_id).first()
                if user:
                    user.last_login = datetime.now(timezone.utc)
                    session.commit()
                    logger.info(f"Updated last login for user_id={user_id}")
        except SQLAlchemyError as e:
            logger.error(f"Failed to update last login for user_id={user_id}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error updating last login: {e}")
    
    def authenticate_user(self, passcode: str) -> bool:
        """
        Authenticate user with passcode and create session.
        
        Args:
            passcode: User passcode for authentication.
            
        Returns:
            True if authentication successful, False otherwise.
        """
        if not passcode or not passcode.strip():
            logger.warning("Empty passcode provided for authentication")
            return False
        
        # Clean passcode input
        passcode = passcode.strip()
        
        # Authenticate with database
        user = self._get_user_by_passcode(passcode)
        if not user:
            logger.warning(f"Authentication failed for passcode")
            return False
        
        # Create session
        session_id = self._generate_session_id()
        created_at = datetime.now(timezone.utc)
        expires_at = created_at + self.session_timeout
        
        session_info = SessionInfo(
            user_id=user.id,
            session_id=session_id,
            created_at=created_at,
            expires_at=expires_at,
            is_active=True
        )
        
        # Store in Streamlit session state
        st.session_state[self.SESSION_KEY] = session_info
        st.session_state[self.USER_KEY] = user.id
        st.session_state[self.AUTHENTICATED_KEY] = True
        
        # Update user's last login
        self._update_last_login(user.id)
        
        logger.info(f"Session created successfully: user_id={user.id}, session_id={session_id}")
        return True
    
    def is_authenticated(self) -> bool:
        """
        Check if user is currently authenticated.
        
        Returns:
            True if user has valid active session, False otherwise.
        """
        # Check if authentication flag exists
        if not st.session_state.get(self.AUTHENTICATED_KEY, False):
            return False
        
        # Check if session info exists
        session_info = st.session_state.get(self.SESSION_KEY)
        if not session_info or not isinstance(session_info, SessionInfo):
            self._clear_session()
            return False
        
        # Check if session is expired
        if session_info.is_expired:
            logger.info(f"Session expired for user_id={session_info.user_id}")
            self._clear_session()
            return False
        
        # Check if session is active
        if not session_info.is_active:
            logger.info(f"Session inactive for user_id={session_info.user_id}")
            self._clear_session()
            return False
        
        return True
    
    def get_session_info(self) -> Optional[SessionInfo]:
        """
        Get current session information.
        
        Returns:
            SessionInfo object if authenticated, None otherwise.
        """
        if not self.is_authenticated():
            return None
        
        return st.session_state.get(self.SESSION_KEY)
    
    def get_current_user_id(self) -> Optional[int]:
        """
        Get current authenticated user ID.
        
        Returns:
            User ID if authenticated, None otherwise.
        """
        if not self.is_authenticated():
            return None
        
        return st.session_state.get(self.USER_KEY)
    
    def logout(self) -> None:
        """Log out current user and clear session."""
        session_info = st.session_state.get(self.SESSION_KEY)
        if session_info:
            logger.info(f"User logged out: user_id={session_info.user_id}")
        
        self._clear_session()
    
    def _clear_session(self) -> None:
        """Clear all session data from Streamlit state."""
        keys_to_clear = [self.SESSION_KEY, self.USER_KEY, self.AUTHENTICATED_KEY]
        for key in keys_to_clear:
            if key in st.session_state:
                del st.session_state[key]
    
    def extend_session(self) -> bool:
        """
        Extend current session expiry time.
        
        Returns:
            True if session extended successfully, False otherwise.
        """
        session_info = st.session_state.get(self.SESSION_KEY)
        if not session_info or not isinstance(session_info, SessionInfo):
            return False
        
        # Extend expiry time
        new_expires_at = datetime.now(timezone.utc) + self.session_timeout
        session_info.expires_at = new_expires_at
        
        # Update session state
        st.session_state[self.SESSION_KEY] = session_info
        
        logger.info(f"Session extended for user_id={session_info.user_id}")
        return True
    
    def get_session_status(self) -> Dict[str, Any]:
        """
        Get detailed session status information.
        
        Returns:
            Dictionary with session status details.
        """
        if not self.is_authenticated():
            return {
                "authenticated": False,
                "user_id": None,
                "session_id": None,
                "created_at": None,
                "expires_at": None,
                "time_remaining": None,
                "is_expired": True
            }
        
        session_info = st.session_state.get(self.SESSION_KEY)
        return {
            "authenticated": True,
            "user_id": session_info.user_id,
            "session_id": session_info.session_id,
            "created_at": session_info.created_at.isoformat(),
            "expires_at": session_info.expires_at.isoformat(),
            "time_remaining": str(session_info.time_remaining),
            "is_expired": session_info.is_expired
        }


def render_login_page() -> bool:
    """
    Render enhanced Streamlit login page interface with professional styling.
    
    This function creates a polished login interface with:
    - Professional styling and layout
    - Clear error messaging for invalid credentials  
    - User feedback and loading states
    - Helpful information about the platform
    
    **Validates: Requirements 1.2, 1.3, 14.7**
    
    Returns:
        True if authentication successful, False otherwise.
    """
    # Custom CSS for enhanced styling
    st.markdown("""
    <style>
        .login-container {
            max-width: 500px;
            margin: 2rem auto;
            padding: 2rem;
            background: linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%);
            border-radius: 12px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.07), 0 1px 3px rgba(0, 0, 0, 0.1);
            border: 1px solid #e2e8f0;
        }
        
        .login-header {
            text-align: center;
            margin-bottom: 2rem;
        }
        
        .login-title {
            color: #1e293b;
            font-size: 2rem;
            font-weight: 600;
            margin-bottom: 0.5rem;
        }
        
        .login-subtitle {
            color: #64748b;
            font-size: 1.1rem;
            font-weight: 400;
        }
        
        .platform-info {
            background: white;
            padding: 1.5rem;
            border-radius: 8px;
            border-left: 4px solid #2563eb;
            margin-top: 1.5rem;
        }
        
        .feature-list {
            margin: 1rem 0;
        }
        
        .feature-item {
            display: flex;
            align-items: center;
            margin: 0.5rem 0;
            color: #475569;
        }
        
        .help-text {
            background: #fef3c7;
            color: #92400e;
            padding: 1rem;
            border-radius: 8px;
            border-left: 4px solid #f59e0b;
            margin-top: 1rem;
        }
        
        .security-note {
            font-size: 0.875rem;
            color: #6b7280;
            text-align: center;
            margin-top: 1rem;
        }
    </style>
    """, unsafe_allow_html=True)
    
    # Main container
    st.markdown('<div class="login-container">', unsafe_allow_html=True)
    
    # Header section
    st.markdown("""
    <div class="login-header">
        <div class="login-title">🏢 GCC Research Intelligence Platform</div>
        <div class="login-subtitle">🔐 Secure Authentication Required</div>
    </div>
    """, unsafe_allow_html=True)
    
    # Login form with enhanced styling
    with st.form("login_form", clear_on_submit=True):
        st.markdown("**Enter your authorized passcode to access the platform:**")
        
        # Passcode input with enhanced validation feedback
        passcode = st.text_input(
            "Passcode",
            type="password",
            placeholder="Enter your passcode...",
            help="🔒 Passcodes are case-sensitive and provided by your system administrator",
            label_visibility="collapsed"
        )
        
        # Enhanced submit button
        submit_button = st.form_submit_button(
            "🚀 Authenticate & Enter Platform", 
            type="primary",
            width='stretch'
        )
        
        if submit_button:
            # Input validation with specific error messages
            if not passcode:
                st.error("🚫 **Passcode Required**: Please enter your passcode to continue.")
                return False
            
            if len(passcode.strip()) == 0:
                st.error("🚫 **Invalid Input**: Passcode cannot be empty or contain only spaces.")
                return False
            
            # Initialize session manager and attempt authentication
            session_manager = SessionManager()
            
            # Enhanced loading state with progress indicator
            with st.spinner("🔍 **Authenticating...** Verifying your credentials"):
                try:
                    if session_manager.authenticate_user(passcode):
                        # Success feedback with professional messaging
                        st.success("✅ **Authentication Successful!** Welcome to the platform. Redirecting...")
                        
                        # Small delay to show success message
                        import time
                        time.sleep(0.5)
                        
                        st.rerun()
                        return True
                    else:
                        # Enhanced error messaging for authentication failure
                        st.error("""
                        ❌ **Authentication Failed**
                        
                        The passcode you entered is incorrect. Please:
                        - Check your passcode for typos
                        - Ensure caps lock is not enabled
                        - Contact your administrator if you continue to have issues
                        """)
                        return False
                        
                except Exception as e:
                    logger.error(f"Authentication error: {e}")
                    st.error("""
                    ⚠️ **System Error**
                    
                    An unexpected error occurred during authentication. 
                    Please try again in a moment or contact your system administrator.
                    """)
                    return False
    
    st.markdown('</div>', unsafe_allow_html=True)
    
    # Enhanced platform information section
    st.markdown("---")
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.markdown("""
        <div class="platform-info">
            <h3>📋 Platform Capabilities</h3>
            <div class="feature-list">
                <div class="feature-item">📊 Upload CSV files with company data</div>
                <div class="feature-item">🤖 AI-powered GCC presence research</div>
                <div class="feature-item">📈 Suitability scoring and business insights</div>
                <div class="feature-item">💾 Intelligent research caching</div>
                <div class="feature-item">📤 Export results in multiple formats</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown("""
        <div class="help-text">
            <h4>🆘 Need Access?</h4>
            <p>If you don't have a passcode or are experiencing authentication issues:</p>
            <ul>
                <li>Contact your system administrator</li>
                <li>Ensure you're using the correct passcode</li>
                <li>Verify your access permissions</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)
    
    # Security and privacy note
    st.markdown("""
    <div class="security-note">
        🔒 This platform uses secure authentication. Your credentials are encrypted and protected.
        <br>For security purposes, sessions expire after 24 hours of inactivity.
    </div>
    """, unsafe_allow_html=True)
    
    return False


def require_authentication():
    """
    Decorator/function to require authentication for Streamlit pages.
    
    This function should be called at the beginning of protected pages
    to ensure users are authenticated before accessing functionality.
    """
    session_manager = SessionManager()
    
    if not session_manager.is_authenticated():
        # Show login page if not authenticated
        if render_login_page():
            st.rerun()
        else:
            st.stop()
    
    return session_manager


def render_session_info():
    """Render session information in sidebar."""
    session_manager = SessionManager()
    
    if session_manager.is_authenticated():
        session_info = session_manager.get_session_info()
        
        st.sidebar.markdown("---")
        st.sidebar.markdown("### 👤 Session Information")
        
        # Display session details
        st.sidebar.write(f"**User ID:** {session_info.user_id}")
        st.sidebar.write(f"**Session ID:** {session_info.session_id[:8]}...")
        
        # Display time remaining
        time_remaining = session_info.time_remaining
        hours, remainder = divmod(time_remaining.total_seconds(), 3600)
        minutes, _ = divmod(remainder, 60)
        st.sidebar.write(f"**Time Remaining:** {int(hours)}h {int(minutes)}m")
        
        # Add logout button
        if st.sidebar.button("🚪 Logout", width='stretch'):
            session_manager.logout()
            st.rerun()
        
        # Add extend session button if less than 1 hour remaining
        if time_remaining.total_seconds() < 3600:  # Less than 1 hour
            if st.sidebar.button("⏰ Extend Session", width='stretch'):
                if session_manager.extend_session():
                    st.sidebar.success("Session extended!")
                    st.rerun()
                else:
                    st.sidebar.error("Failed to extend session")


def create_user_with_passcode(passcode: str) -> bool:
    """
    Create a new user with the given passcode.
    
    This is a utility function for setting up initial users.
    In production, this should be done through an admin interface.
    
    Args:
        passcode: Plain text passcode for the new user.
        
    Returns:
        True if user created successfully, False otherwise.
    """
    try:
        with db_manager.get_session() as session:
            # Check if a user with this exact plaintext passcode already
            # exists. Since bcrypt hashes are randomly salted we can't do
            # this with a DB-side equality filter, so verify against the
            # existing active users instead.
            existing_users: List[User] = session.query(User).filter(
                User.is_active == True
            ).all()
            for existing_user in existing_users:
                if verify_passcode(passcode, existing_user.passcode):
                    logger.warning("User with this passcode already exists")
                    return False

            hashed_passcode = hash_passcode(passcode)

            # Create new user
            new_user = User(
                passcode=hashed_passcode,
                created_at=datetime.now(timezone.utc),
                is_active=True
            )
            
            session.add(new_user)
            session.commit()
            
            logger.info(f"New user created successfully: user_id={new_user.id}")
            return True
            
    except SQLAlchemyError as e:
        logger.error(f"Database error creating user: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error creating user: {e}")
        return False


if __name__ == "__main__":
    # Example usage for testing
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "create_user" and len(sys.argv) > 2:
            passcode = sys.argv[2]
            if create_user_with_passcode(passcode):
                print(f"✅ User created successfully with passcode: {passcode}")
            else:
                print("❌ Failed to create user")
        else:
            print("Usage: python authentication.py create_user <passcode>")