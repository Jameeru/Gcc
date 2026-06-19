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
    Render a compact, centered, enterprise-styled login page.

    Earlier versions tried to constrain the form's width with a hand-rolled
    ``<div class="login-container" style="max-width:500px">`` wrapper opened
    via ``st.markdown(...)``. That never actually worked: a raw HTML element
    injected by one ``st.markdown`` call cannot visually contain widgets
    rendered by a *later, separate* Streamlit call (``st.form``,
    ``st.text_input``, ``st.form_submit_button``) -- each becomes an
    independent full-width sibling in the real DOM regardless of the markup
    around it. That's why the password field and submit button always
    stretched the full page width no matter what CSS was added.

    The fix is to use ``st.columns([...])`` instead, which IS a real layout
    primitive: widgets rendered inside a column slot are genuinely nested
    inside it, so a narrow center column actually constrains everything
    placed in it -- logo, title, the form, and the footnote below.

    **Validates: Requirements 1.2, 1.3, 14.7**

    Returns:
        True if authentication successful, False otherwise.
    """
    from ..utils.theme import clean_html

    st.markdown("<div class='gcc-login-wrap'>", unsafe_allow_html=True)

    # A real layout primitive: only content placed inside col_mid is
    # actually narrowed to roughly 38% of the page width on desktop.
    _, col_mid, _ = st.columns([1, 1.1, 1])

    with col_mid:
        st.markdown(
            clean_html(
                """
                <div class="gcc-login-logo">🏢</div>
                <div class="gcc-login-title">GCC Research Intelligence</div>
                <div class="gcc-login-subtitle">Sign in with your passcode to continue</div>
                """
            ),
            unsafe_allow_html=True,
        )

        result_holder = {"authenticated": False}

        with st.form("login_form", clear_on_submit=True):
            passcode = st.text_input(
                "Passcode",
                type="password",
                placeholder="Enter passcode",
                help="Case-sensitive. Provided by your system administrator.",
                label_visibility="collapsed",
            )

            submit_button = st.form_submit_button(
                "Sign In", type="primary", width='stretch'
            )

            if submit_button:
                if not passcode or not passcode.strip():
                    st.error("🚫 Please enter your passcode.")
                else:
                    session_manager = SessionManager()
                    with st.spinner("Verifying credentials…"):
                        try:
                            if session_manager.authenticate_user(passcode):
                                st.success("✅ Authenticated — redirecting…")
                                time.sleep(0.4)
                                result_holder["authenticated"] = True
                            else:
                                st.error(
                                    "❌ Incorrect passcode. Check for typos or "
                                    "caps lock, or contact your administrator."
                                )
                        except Exception as e:
                            logger.error(f"Authentication error: {e}")
                            st.error(
                                "⚠️ A system error occurred. Please try again "
                                "in a moment."
                            )

        st.markdown(
            clean_html(
                """
                <div class="gcc-login-chip-row">
                    <span class="gcc-login-chip">📊 CSV Upload</span>
                    <span class="gcc-login-chip">🤖 AI-Powered Research</span>
                    <span class="gcc-login-chip">📈 Suitability Scoring</span>
                    <span class="gcc-login-chip">📤 Export</span>
                </div>
                <div class="gcc-login-footnote">
                    🔒 Credentials are encrypted. Sessions expire after 24h of inactivity.
                    <br>Need access? Contact your system administrator.
                </div>
                """
            ),
            unsafe_allow_html=True,
        )

    st.markdown("</div>", unsafe_allow_html=True)

    if result_holder["authenticated"]:
        st.rerun()
        return True

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
    """Render the user/session panel in the sidebar (enterprise-styled)."""
    session_manager = SessionManager()

    if not session_manager.is_authenticated():
        return

    session_info = session_manager.get_session_info()

    time_remaining = session_info.time_remaining
    hours, remainder = divmod(time_remaining.total_seconds(), 3600)
    minutes, _ = divmod(remainder, 60)
    low_time = time_remaining.total_seconds() < 3600

    st.sidebar.markdown(
        f"""
        <div class="gcc-sidebar-user">
            <div class="gcc-avatar">U{session_info.user_id}</div>
            <div>
                <div class="gcc-sidebar-user-name">User #{session_info.user_id}</div>
                <div class="gcc-sidebar-user-meta">Session {session_info.session_id[:8]}…</div>
            </div>
        </div>
        <div class="gcc-sidebar-user-meta" style="margin: 0.1rem 0 0.6rem 0.2rem;">
            ⏱️ {int(hours)}h {int(minutes)}m remaining
        </div>
        """,
        unsafe_allow_html=True,
    )

    if low_time:
        col_logout, col_extend = st.sidebar.columns(2)
        with col_logout:
            if st.button("🚪 Logout", width='stretch', key="gcc_sidebar_logout"):
                session_manager.logout()
                st.rerun()
        with col_extend:
            if st.button("⏰ Extend", width='stretch', key="gcc_sidebar_extend"):
                if session_manager.extend_session():
                    st.sidebar.success("Session extended!")
                    st.rerun()
                else:
                    st.sidebar.error("Failed to extend session")
    else:
        if st.sidebar.button("🚪 Logout", width='stretch', key="gcc_sidebar_logout"):
            session_manager.logout()
            st.rerun()


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