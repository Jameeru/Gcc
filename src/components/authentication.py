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
from sqlalchemy import text

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
    # Role-based access control: 'user' (normal dashboard) or 'admin'
    # (redirected to the admin dashboard). Defaults to 'user' so older
    # sessions created before this field existed still behave correctly.
    role: str = "user"
    full_name: Optional[str] = None
    email: Optional[str] = None

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

    @property
    def is_admin(self) -> bool:
        """True if this session belongs to an admin-role user."""
        return self.role == "admin"


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
                # Use raw SQL to get all active users to avoid SQLAlchemy model issues
                results = session.execute(text("""
                    SELECT id, email, passcode, full_name, is_active, created_at, last_login,
                           password_history, last_password_change, role
                    FROM users
                    WHERE is_active = true
                """)).fetchall()

                for row in results:
                    if verify_passcode(passcode, row.passcode):
                        logger.info(f"User authenticated successfully: user_id={row.id}")

                        # Create User object manually from raw result
                        user = User()
                        user.id = row.id
                        user.email = row.email
                        user.passcode = row.passcode
                        user.full_name = row.full_name
                        user.is_active = row.is_active
                        user.created_at = row.created_at
                        user.last_login = row.last_login
                        user.password_history = row.password_history
                        user.last_password_change = row.last_password_change
                        user.role = row.role or "user"

                        return user

                return None

        except SQLAlchemyError as e:
            logger.error(f"Database error during authentication: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error during authentication: {e}")
            return None
    
    def _get_user_by_email_password(self, email: str, password: str) -> Optional[User]:
        """
        Retrieve user by email and password (new authentication method).

        Args:
            email: User email address
            password: User password

        Returns:
            User object if found and active, None otherwise.
        """
        try:
            with db_manager.get_session() as session:
                # Use raw SQL to get user by email to avoid SQLAlchemy model caching issues
                from sqlalchemy import text
                result = session.execute(text("""
                    SELECT id, email, passcode, full_name, is_active, created_at, last_login,
                           password_history, last_password_change, role
                    FROM users
                    WHERE email = :email AND is_active = true
                """), {"email": email.lower()}).fetchone()

                if result and result.passcode and verify_passcode(password, result.passcode):
                    logger.info(f"User authenticated via email: user_id={result.id}, email={email}")

                    # Create User object manually from raw result
                    user = User()
                    user.id = result.id
                    user.email = result.email
                    user.passcode = result.passcode
                    user.full_name = result.full_name
                    user.is_active = result.is_active
                    user.created_at = result.created_at
                    user.last_login = result.last_login
                    user.password_history = result.password_history
                    user.last_password_change = result.last_password_change
                    user.role = result.role or "user"

                    return user

                return None

        except SQLAlchemyError as e:
            logger.error(f"Database error during email authentication: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error during email authentication: {e}")
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
    
    def authenticate_user(self, identifier: str, password: str = None) -> bool:
        """
        Authenticate user with passcode or email/password.
        
        Args:
            identifier: User passcode or email address
            password: Password (required if identifier is email)
            
        Returns:
            True if authentication successful, False otherwise.
        """
        if not identifier or not identifier.strip():
            logger.warning("Empty identifier provided for authentication")
            return False
        
        # Clean identifier input
        identifier = identifier.strip()
        
        # Determine authentication method
        user = None
        
        if '@' in identifier and password:
            # Email/password authentication
            user = self._get_user_by_email_password(identifier, password)
        else:
            # Traditional passcode authentication (backward compatibility)
            user = self._get_user_by_passcode(identifier)
        
        if not user:
            logger.warning(f"Authentication failed for identifier: {identifier}")
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
            is_active=True,
            role=getattr(user, "role", "user") or "user",
            full_name=user.full_name,
            email=user.email,
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
    Render a compact, centered, enterprise-styled login page with forgot password functionality.

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
                <div class="gcc-login-subtitle">Sign in with your email and password to continue</div>
                """
            ),
            unsafe_allow_html=True,
        )

        # Check for password reset completion message
        if "reset_success" in st.query_params:
            st.success("✅ Password reset successfully! Please sign in with your new password.")
            # Clear the query parameter
            del st.query_params["reset_success"]

        result_holder = {"authenticated": False}

        with st.form("login_form", clear_on_submit=True):
            email = st.text_input(
                "Email Address",
                placeholder="Enter your email",
                help="Your registered email address",
                label_visibility="visible",
            )

            password = st.text_input(
                "Password",
                type="password",
                placeholder="Enter your password",
                help="Your account password",
                label_visibility="visible",
            )

            submit_button = st.form_submit_button(
                "Sign In", type="primary", width='stretch'
            )

            if submit_button:
                # Enhanced validation with required field checking
                if not email or not password:
                    st.error("🚫 Please enter both email and password.")
                elif not email.strip() or not password.strip():
                    st.error("🚫 Email and password cannot be empty.")
                else:
                    session_manager = SessionManager()
                    with st.spinner("Verifying credentials…"):
                        try:
                            if session_manager.authenticate_user(email, password):
                                st.success("✅ Authenticated — redirecting…")
                                time.sleep(0.4)
                                result_holder["authenticated"] = True
                            else:
                                st.error(
                                    "❌ Invalid email or password. Check your credentials "
                                    "or contact your administrator."
                                )
                        except Exception as e:
                            logger.error(f"Authentication error: {e}")
                            st.error(
                                "⚠️ A system error occurred. Please try again "
                                "in a moment."
                            )

        # Forgot password link
        st.markdown("<div style='text-align: center; margin-top: 15px;'>", unsafe_allow_html=True)
        if st.button("🔑 Forgot Password?", key="forgot_password_link", help="Reset your password via email"):
            st.session_state["show_reset_form"] = True
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

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
    # Handle password reset workflow first
    if "reset_token" in st.query_params:
        reset_token = st.query_params["reset_token"]
        if handle_password_reset_completion(reset_token):
            # If reset was successful, clear token and redirect to login
            del st.query_params["reset_token"]
            st.query_params["reset_success"] = "true"
            st.rerun()
        return None
    
    # Check if showing reset form
    if st.session_state.get("show_reset_form", False):
        if render_password_reset_form():
            # Reset completed, redirect to login
            st.session_state["show_reset_form"] = False
            st.rerun()
        return None
    
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


def render_password_reset_form() -> bool:
    """
    Render password reset request form.
    
    Returns:
        True if reset process completed successfully, False otherwise
    """
    from ..utils.theme import clean_html
    from .password_reset import PasswordResetSystem, EnhancedInputValidator

    st.markdown("<div class='gcc-login-wrap'>", unsafe_allow_html=True)
    
    _, col_mid, _ = st.columns([1, 1.1, 1])
    
    with col_mid:
        st.markdown(
            clean_html(
                """
                <div class="gcc-login-logo">🔑</div>
                <div class="gcc-login-title">Reset Your Password</div>
                <div class="gcc-login-subtitle">Enter your User ID to receive reset instructions</div>
                """
            ),
            unsafe_allow_html=True,
        )

        with st.form("reset_form", clear_on_submit=True):
            user_id = st.text_input(
                "User ID",
                placeholder="Enter your User ID (e.g., 1, 2, 3...)",
                help="Your numeric User ID shown in the sidebar when logged in",
                label_visibility="visible"
            )
            
            submit_button = st.form_submit_button(
                "Send Reset Email", type="primary", width='stretch'
            )
            
            if submit_button:
                # Validate input
                validation = EnhancedInputValidator.validate_reset_identifier(user_id)
                
                if not validation["valid"]:
                    st.error(f"🚫 {validation['error']}")
                else:
                    reset_system = PasswordResetSystem()
                    with st.spinner("Processing reset request..."):
                        result = reset_system.initiate_reset(user_id.strip())
                        
                        if result.success:
                            st.success(result.message)
                            if result.error_code != "RATE_LIMITED":
                                st.info("📧 If your User ID exists, you'll receive reset instructions. Check the console logs for the reset link (since email is not configured).")
                        else:
                            if result.error_code == "RATE_LIMITED":
                                st.warning(result.message)
                            else:
                                st.error(result.message)

        # Back to login button
        st.markdown("<div style='text-align: center; margin-top: 20px;'>", unsafe_allow_html=True)
        if st.button("← Back to Sign In", key="back_to_login"):
            st.session_state["show_reset_form"] = False
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
    
    st.markdown("</div>", unsafe_allow_html=True)
    
    return False


def handle_password_reset_completion(token: str) -> bool:
    """
    Handle password reset completion workflow.
    
    Args:
        token: Reset token from URL parameter
        
    Returns:
        True if password was successfully reset, False otherwise
    """
    from ..utils.theme import clean_html
    from .password_reset import PasswordResetSystem

    reset_system = PasswordResetSystem()
    
    # Validate token first
    token_validation = reset_system.validate_token(token)
    
    if not token_validation["valid"]:
        st.error(f"❌ {token_validation['error']}")
        st.markdown("<div style='text-align: center; margin-top: 20px;'>", unsafe_allow_html=True)
        if st.button("Request New Reset", key="request_new_reset"):
            st.session_state["show_reset_form"] = True
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
        return False
    
    # Show password reset form
    st.markdown("<div class='gcc-login-wrap'>", unsafe_allow_html=True)
    
    _, col_mid, _ = st.columns([1, 1.1, 1])
    
    with col_mid:
        st.markdown(
            clean_html(
                """
                <div class="gcc-login-logo">🔐</div>
                <div class="gcc-login-title">Set New Password</div>
                <div class="gcc-login-subtitle">Choose a strong password for your account</div>
                """
            ),
            unsafe_allow_html=True,
        )

        with st.form("new_password_form", clear_on_submit=True):
            new_password = st.text_input(
                "New Password",
                type="password",
                placeholder="Enter new password",
                help="Must be at least 8 characters with uppercase, lowercase, number, and special character",
                label_visibility="visible"
            )
            
            confirm_password = st.text_input(
                "Confirm Password",
                type="password",
                placeholder="Re-enter new password",
                label_visibility="visible"
            )
            
            submit_button = st.form_submit_button(
                "Update Password", type="primary", width='stretch'
            )
            
            if submit_button:
                if not new_password:
                    st.error("🚫 New password is required")
                elif not confirm_password:
                    st.error("🚫 Please confirm your new password")
                elif new_password != confirm_password:
                    st.error("🚫 Passwords do not match")
                else:
                    with st.spinner("Updating password..."):
                        result = reset_system.reset_password(token, new_password)
                        
                        if result.success:
                            st.success(result.message)
                            time.sleep(1)
                            return True
                        else:
                            st.error(result.message)

        # Show password requirements
        st.markdown(
            clean_html(
                """
                <div style='background-color: #f8f9fa; padding: 15px; border-radius: 8px; margin-top: 15px; font-size: 14px;'>
                    <strong>Password Requirements:</strong>
                    <ul style='margin: 8px 0; padding-left: 20px;'>
                        <li>At least 8 characters long</li>
                        <li>At least one uppercase letter (A-Z)</li>
                        <li>At least one lowercase letter (a-z)</li>
                        <li>At least one number (0-9)</li>
                        <li>At least one special character (!@#$%^&*())</li>
                        <li>Cannot be the same as your current password</li>
                    </ul>
                </div>
                """
            ),
            unsafe_allow_html=True,
        )
    
    st.markdown("</div>", unsafe_allow_html=True)
    
    return False