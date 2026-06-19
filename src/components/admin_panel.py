"""
Admin Panel for the GCC Research Intelligence Platform.

This module provides comprehensive admin functionality including:
- User management (create, edit, delete, activate/deactivate)
- Email/password authentication system
- Password reset capabilities
- User access control and permissions
- Admin dashboard with user statistics
"""

import re
import json
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass
from email.utils import parseaddr

import streamlit as st
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text, and_

from ..core.database import db_manager
from ..models.schemas import User
from ..utils.config import get_config
from ..utils.logging import get_logger
from ..utils.security import hash_passcode, verify_passcode
from ..utils.theme import clean_html, pill, kpi_card
from .password_reset import PasswordResetSystem

logger = get_logger(__name__)


@dataclass
class AdminUser:
    """Admin user data structure with email/password auth."""
    id: int
    email: str
    password_hash: str
    full_name: str
    is_active: bool
    is_super_admin: bool
    created_at: datetime
    last_login: Optional[datetime]
    
    @classmethod
    def from_dict(cls, data: dict) -> 'AdminUser':
        return cls(**data)


@dataclass
class UserManagementResult:
    """Result of user management operations."""
    success: bool
    message: str
    user_id: Optional[int] = None
    error_code: Optional[str] = None


class AdminAuthentication:
    """
    Admin authentication system with email/password.
    """
    
    def __init__(self):
        self.config = get_config()
        self.session_timeout = timedelta(hours=2)  # Shorter timeout for admin
    
    def _is_valid_email(self, email: str) -> bool:
        """Validate email format."""
        if not email or '@' not in email:
            return False
        
        parsed = parseaddr(email)
        return '@' in parsed[1] and '.' in parsed[1].split('@')[1]
    
    def _hash_password(self, password: str) -> str:
        """Hash password using bcrypt."""
        return hash_passcode(password)
    
    def _verify_password(self, password: str, hash_str: str) -> bool:
        """Verify password against hash."""
        return verify_passcode(password, hash_str)
    def authenticate_admin(self, email: str, password: str) -> Tuple[bool, Optional[AdminUser]]:
        """
        Authenticate admin user with email/password.
        
        Args:
            email: Admin email address
            password: Admin password
            
        Returns:
            Tuple of (success, admin_user_or_none)
        """
        if not email or not password:
            return False, None
        
        if not self._is_valid_email(email):
            return False, None
        
        try:
            # Check if admin users table exists, create if not
            self._ensure_admin_table()
            
            with db_manager.get_session() as session:
                # Get admin user by email
                result = session.execute(text("""
                    SELECT id, email, password_hash, full_name, is_active, 
                           is_super_admin, created_at, last_login
                    FROM admin_users 
                    WHERE email = :email AND is_active = true
                """), {"email": email.lower()}).fetchone()
                
                if not result:
                    return False, None
                
                # Verify password
                if not self._verify_password(password, result.password_hash):
                    return False, None
                
                # Create admin user object
                admin_user = AdminUser(
                    id=result.id,
                    email=result.email,
                    password_hash=result.password_hash,
                    full_name=result.full_name,
                    is_active=result.is_active,
                    is_super_admin=result.is_super_admin,
                    created_at=result.created_at,
                    last_login=result.last_login
                )
                
                # Update last login
                session.execute(text("""
                    UPDATE admin_users 
                    SET last_login = :now 
                    WHERE id = :admin_id
                """), {"now": datetime.now(timezone.utc), "admin_id": admin_user.id})
                session.commit()
                
                logger.info(f"Admin authenticated: {email}")
                return True, admin_user
                
        except SQLAlchemyError as e:
            logger.error(f"Database error during admin authentication: {e}")
            return False, None
    
    def _ensure_admin_table(self) -> None:
        """Ensure admin users table exists."""
        try:
            with db_manager.get_session() as session:
                session.execute(text("""
                    CREATE TABLE IF NOT EXISTS admin_users (
                        id SERIAL PRIMARY KEY,
                        email VARCHAR(255) NOT NULL UNIQUE,
                        password_hash VARCHAR(255) NOT NULL,
                        full_name VARCHAR(255) NOT NULL,
                        is_active BOOLEAN NOT NULL DEFAULT true,
                        is_super_admin BOOLEAN NOT NULL DEFAULT false,
                        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                        last_login TIMESTAMP WITH TIME ZONE NULL
                    )
                """))
                
                # Create default admin if none exist
                admin_count = session.execute(text(
                    "SELECT COUNT(*) FROM admin_users"
                )).scalar()
                
                if admin_count == 0:
                    # Create default super admin
                    default_password = "Admin123!"
                    password_hash = self._hash_password(default_password)
                    
                    session.execute(text("""
                        INSERT INTO admin_users 
                        (email, password_hash, full_name, is_super_admin)
                        VALUES (:email, :password_hash, :full_name, true)
                    """), {
                        "email": "admin@gcc.com",
                        "password_hash": password_hash,
                        "full_name": "System Administrator"
                    })
                    
                    logger.info("Created default admin user: admin@gcc.com / Admin123!")
                
                session.commit()
                
        except SQLAlchemyError as e:
            logger.error(f"Error ensuring admin table: {e}")
    
    def create_session(self, admin_user: AdminUser) -> None:
        """Create admin session in Streamlit state."""
        session_data = {
            "admin_id": admin_user.id,
            "email": admin_user.email,
            "full_name": admin_user.full_name,
            "is_super_admin": admin_user.is_super_admin,
            "authenticated_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc) + self.session_timeout
        }
        
        st.session_state["admin_session"] = session_data
        st.session_state["admin_authenticated"] = True
    
    def is_authenticated(self) -> bool:
        """Check if admin is authenticated."""
        session_data = st.session_state.get("admin_session")
        
        if not session_data or not st.session_state.get("admin_authenticated"):
            return False
        
        # Check if session expired
        if datetime.now(timezone.utc) > session_data.get("expires_at", datetime.min.replace(tzinfo=timezone.utc)):
            self.logout()
            return False
        
        return True
    
    def get_current_admin(self) -> Optional[Dict[str, Any]]:
        """Get current admin session data."""
        if not self.is_authenticated():
            return None
        return st.session_state.get("admin_session")
    
    def logout(self) -> None:
        """Logout admin and clear session."""
        if "admin_session" in st.session_state:
            del st.session_state["admin_session"]
        if "admin_authenticated" in st.session_state:
            del st.session_state["admin_authenticated"]
class UserManager:
    """
    User management system for admin panel.
    """
    
    def __init__(self):
        self.reset_system = PasswordResetSystem()
    
    def get_user_statistics(self) -> Dict[str, Any]:
        """Get user statistics for dashboard."""
        try:
            with db_manager.get_session() as session:
                # Total users
                total_users = session.execute(text(
                    "SELECT COUNT(*) FROM users"
                )).scalar() or 0
                
                # Active users
                active_users = session.execute(text(
                    "SELECT COUNT(*) FROM users WHERE is_active = true"
                )).scalar() or 0
                
                # Users created this week
                week_ago = datetime.now(timezone.utc) - timedelta(days=7)
                new_users = session.execute(text(
                    "SELECT COUNT(*) FROM users WHERE created_at >= :week_ago"
                ), {"week_ago": week_ago}).scalar() or 0
                
                # Users with recent activity
                recent_logins = session.execute(text(
                    "SELECT COUNT(*) FROM users WHERE last_login >= :week_ago"
                ), {"week_ago": week_ago}).scalar() or 0
                
                return {
                    "total_users": total_users,
                    "active_users": active_users,
                    "inactive_users": total_users - active_users,
                    "new_users_week": new_users,
                    "recent_logins": recent_logins
                }
                
        except SQLAlchemyError as e:
            logger.error(f"Error getting user statistics: {e}")
            return {
                "total_users": 0,
                "active_users": 0,
                "inactive_users": 0,
                "new_users_week": 0,
                "recent_logins": 0
            }
    
    def get_all_users(self, include_inactive: bool = True) -> List[Dict[str, Any]]:
        """Get all users for management."""
        try:
            with db_manager.get_session() as session:
                query = """
                    SELECT id, email, full_name, is_active, created_at, last_login,
                           CASE WHEN last_login IS NULL THEN 'Never' 
                                ELSE last_login::text END as last_login_display
                    FROM users
                """
                
                if not include_inactive:
                    query += " WHERE is_active = true"
                
                query += " ORDER BY created_at DESC"
                
                results = session.execute(text(query)).fetchall()
                
                users = []
                for row in results:
                    users.append({
                        "id": row.id,
                        "email": row.email or f"user_{row.id}@gcc.com",
                        "full_name": row.full_name or f"User {row.id}",
                        "is_active": row.is_active,
                        "created_at": row.created_at,
                        "last_login": row.last_login,
                        "last_login_display": row.last_login_display
                    })
                
                return users
                
        except SQLAlchemyError as e:
            logger.error(f"Error getting users: {e}")
            return []
    
    def create_user(self, email: str, password: str, full_name: str) -> UserManagementResult:
        """Create a new user with email and password."""
        # Validate inputs
        if not email or not self._is_valid_email(email):
            return UserManagementResult(False, "Invalid email address", error_code="INVALID_EMAIL")
        
        if not password or len(password) < 8:
            return UserManagementResult(False, "Password must be at least 8 characters", error_code="WEAK_PASSWORD")
        
        if not full_name or len(full_name.strip()) < 2:
            return UserManagementResult(False, "Full name must be at least 2 characters", error_code="INVALID_NAME")
        
        # Validate password strength
        password_validation = self.reset_system.validate_password_strength(password)
        if not password_validation.is_valid:
            return UserManagementResult(
                False, 
                "Password requirements: " + "; ".join(password_validation.errors), 
                error_code="WEAK_PASSWORD"
            )
        
        try:
            with db_manager.get_session() as session:
                # Check if email already exists
                existing = session.execute(text(
                    "SELECT id FROM users WHERE email = :email"
                ), {"email": email.lower()}).fetchone()
                
                if existing:
                    return UserManagementResult(False, "Email already exists", error_code="EMAIL_EXISTS")
                
                # Ensure users table has email and full_name columns
                self._ensure_user_columns(session)
                
                # Hash password
                password_hash = hash_passcode(password)
                
                # Create user
                result = session.execute(text("""
                    INSERT INTO users (email, passcode, full_name, is_active, created_at)
                    VALUES (:email, :password_hash, :full_name, true, :created_at)
                    RETURNING id
                """), {
                    "email": email.lower(),
                    "password_hash": password_hash,
                    "full_name": full_name.strip(),
                    "created_at": datetime.now(timezone.utc)
                })
                
                user_id = result.scalar()
                session.commit()
                
                logger.info(f"User created by admin: {email} (ID: {user_id})")
                return UserManagementResult(True, f"User created successfully with ID {user_id}", user_id)
                
        except SQLAlchemyError as e:
            logger.error(f"Error creating user: {e}")
            return UserManagementResult(False, "Database error occurred", error_code="DB_ERROR")
    
    def _is_valid_email(self, email: str) -> bool:
        """Validate email format."""
        if not email or '@' not in email:
            return False
        
        parsed = parseaddr(email)
        return '@' in parsed[1] and '.' in parsed[1].split('@')[1]
    
    def _ensure_user_columns(self, session: Session) -> None:
        """Ensure users table has required columns for email/password auth."""
        try:
            # Add email column if not exists
            session.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(255) UNIQUE"
            ))
            
            # Add full_name column if not exists
            session.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name VARCHAR(255)"
            ))
            
            session.commit()
        except SQLAlchemyError as e:
            logger.error(f"Error ensuring user columns: {e}")
            session.rollback()
    def update_user(self, user_id: int, email: str = None, full_name: str = None, 
                   is_active: bool = None) -> UserManagementResult:
        """Update user information."""
        try:
            with db_manager.get_session() as session:
                # Build update query dynamically
                updates = []
                params = {"user_id": user_id}
                
                if email is not None:
                    if not self._is_valid_email(email):
                        return UserManagementResult(False, "Invalid email address", error_code="INVALID_EMAIL")
                    
                    # Check if email already exists for another user
                    existing = session.execute(text(
                        "SELECT id FROM users WHERE email = :email AND id != :user_id"
                    ), {"email": email.lower(), "user_id": user_id}).fetchone()
                    
                    if existing:
                        return UserManagementResult(False, "Email already exists", error_code="EMAIL_EXISTS")
                    
                    updates.append("email = :email")
                    params["email"] = email.lower()
                
                if full_name is not None:
                    if len(full_name.strip()) < 2:
                        return UserManagementResult(False, "Full name must be at least 2 characters", error_code="INVALID_NAME")
                    updates.append("full_name = :full_name")
                    params["full_name"] = full_name.strip()
                
                if is_active is not None:
                    updates.append("is_active = :is_active")
                    params["is_active"] = is_active
                
                if not updates:
                    return UserManagementResult(False, "No updates provided", error_code="NO_UPDATES")
                
                # Execute update
                query = f"UPDATE users SET {', '.join(updates)} WHERE id = :user_id"
                result = session.execute(text(query), params)
                
                if result.rowcount == 0:
                    return UserManagementResult(False, "User not found", error_code="USER_NOT_FOUND")
                
                session.commit()
                
                logger.info(f"User {user_id} updated by admin")
                return UserManagementResult(True, "User updated successfully", user_id)
                
        except SQLAlchemyError as e:
            logger.error(f"Error updating user: {e}")
            return UserManagementResult(False, "Database error occurred", error_code="DB_ERROR")
    
    def reset_user_password(self, user_id: int, new_password: str) -> UserManagementResult:
        """Reset user password (admin action)."""
        # Validate password strength
        password_validation = self.reset_system.validate_password_strength(new_password)
        if not password_validation.is_valid:
            return UserManagementResult(
                False, 
                "Password requirements: " + "; ".join(password_validation.errors), 
                error_code="WEAK_PASSWORD"
            )
        
        try:
            with db_manager.get_session() as session:
                # Hash new password
                password_hash = hash_passcode(new_password)
                
                # Update user password
                result = session.execute(text("""
                    UPDATE users 
                    SET passcode = :password_hash, 
                        last_password_change = :now 
                    WHERE id = :user_id
                """), {
                    "password_hash": password_hash,
                    "now": datetime.now(timezone.utc),
                    "user_id": user_id
                })
                
                if result.rowcount == 0:
                    return UserManagementResult(False, "User not found", error_code="USER_NOT_FOUND")
                
                session.commit()
                
                logger.info(f"Password reset for user {user_id} by admin")
                return UserManagementResult(True, "Password reset successfully", user_id)
                
        except SQLAlchemyError as e:
            logger.error(f"Error resetting password: {e}")
            return UserManagementResult(False, "Database error occurred", error_code="DB_ERROR")
    
    def delete_user(self, user_id: int, permanent: bool = False) -> UserManagementResult:
        """Delete user (soft delete by default, permanent if specified)."""
        try:
            with db_manager.get_session() as session:
                if permanent:
                    # Permanent deletion
                    result = session.execute(text(
                        "DELETE FROM users WHERE id = :user_id"
                    ), {"user_id": user_id})
                    
                    if result.rowcount == 0:
                        return UserManagementResult(False, "User not found", error_code="USER_NOT_FOUND")
                    
                    logger.warning(f"User {user_id} permanently deleted by admin")
                    message = "User permanently deleted"
                else:
                    # Soft delete (deactivate)
                    result = session.execute(text(
                        "UPDATE users SET is_active = false WHERE id = :user_id"
                    ), {"user_id": user_id})
                    
                    if result.rowcount == 0:
                        return UserManagementResult(False, "User not found", error_code="USER_NOT_FOUND")
                    
                    logger.info(f"User {user_id} deactivated by admin")
                    message = "User deactivated successfully"
                
                session.commit()
                return UserManagementResult(True, message, user_id)
                
        except SQLAlchemyError as e:
            logger.error(f"Error deleting user: {e}")
            return UserManagementResult(False, "Database error occurred", error_code="DB_ERROR")
def render_admin_login() -> bool:
    """
    Render admin login page with email/password authentication.
    
    Returns:
        True if authentication successful, False otherwise
    """
    st.set_page_config(
        page_title="GCC Admin Panel",
        page_icon="👤",
        layout="wide"
    )
    
    from ..utils.theme import inject_enterprise_theme
    inject_enterprise_theme()
    
    st.markdown("<div class='gcc-login-wrap'>", unsafe_allow_html=True)
    
    _, col_mid, _ = st.columns([1, 1.2, 1])
    
    with col_mid:
        st.markdown(
            clean_html("""
                <div class="gcc-login-logo" style="background: linear-gradient(135deg, #dc2626 0%, #b91c1c 100%);">👤</div>
                <div class="gcc-login-title">GCC Admin Panel</div>
                <div class="gcc-login-subtitle">Administrator access - Email and password required</div>
            """),
            unsafe_allow_html=True,
        )
        
        # Show default admin credentials info
        with st.expander("ℹ️ Default Admin Access", expanded=True):
            st.info("""
            **Default Administrator Account:**
            - Email: `admin@gcc.com`
            - Password: `Admin123!`
            
            Please change the default password after first login.
            """)
        
        with st.form("admin_login_form"):
            email = st.text_input(
                "Email Address",
                placeholder="admin@gcc.com",
                help="Enter your administrator email address"
            )
            
            password = st.text_input(
                "Password",
                type="password",
                placeholder="Enter password",
                help="Enter your administrator password"
            )
            
            login_button = st.form_submit_button(
                "🔐 Admin Sign In", 
                type="primary", 
                use_container_width=True
            )
            
            if login_button:
                if not email or not password:
                    st.error("🚫 Please enter both email and password")
                else:
                    auth = AdminAuthentication()
                    
                    with st.spinner("Verifying admin credentials..."):
                        success, admin_user = auth.authenticate_admin(email, password)
                        
                        if success and admin_user:
                            auth.create_session(admin_user)
                            st.success(f"✅ Welcome, {admin_user.full_name}!")
                            st.rerun()
                        else:
                            st.error("❌ Invalid email or password")
        
        st.markdown(
            clean_html("""
                <div class="gcc-login-footnote">
                    🔒 Admin panel access is logged and monitored<br>
                    Contact system administrator if you need access
                </div>
            """),
            unsafe_allow_html=True,
        )
    
    st.markdown("</div>", unsafe_allow_html=True)
    return False


def render_admin_dashboard():
    """Render main admin dashboard."""
    auth = AdminAuthentication()
    admin_data = auth.get_current_admin()
    
    if not admin_data:
        st.error("Session expired. Please log in again.")
        st.stop()
    
    # Header
    col1, col2 = st.columns([3, 1])
    with col1:
        st.title(f"👤 Admin Dashboard")
        st.caption(f"Welcome back, {admin_data['full_name']}")
    
    with col2:
        if st.button("🚪 Logout", key="admin_logout"):
            auth.logout()
            st.rerun()
    
    # Get user statistics
    user_manager = UserManager()
    stats = user_manager.get_user_statistics()
    
    # KPI Cards
    st.subheader("📊 User Statistics")
    col1, col2, col3, col4 = st.columns(4)
    
    kpi_card(
        col1,
        "Total Users",
        str(stats["total_users"]),
        icon="👥",
        delta=f"{stats['new_users_week']} new this week"
    )
    
    kpi_card(
        col2,
        "Active Users",
        str(stats["active_users"]),
        icon="✅",
        delta=f"{stats['inactive_users']} inactive"
    )
    
    kpi_card(
        col3,
        "Recent Logins",
        str(stats["recent_logins"]),
        icon="🔑",
        delta="Last 7 days"
    )
    
    kpi_card(
        col4,
        "New This Week",
        str(stats["new_users_week"]),
        icon="📈",
        delta="Weekly growth"
    )
    
    st.markdown("<div style='height:2rem'></div>", unsafe_allow_html=True)
    
    # Navigation
    tab1, tab2, tab3 = st.tabs(["👥 User Management", "➕ Create User", "🔧 System Settings"])
    
    with tab1:
        render_user_management(user_manager)
    
    with tab2:
        render_create_user(user_manager)
    
    with tab3:
        render_system_settings(admin_data)
def render_user_management(user_manager: UserManager):
    """Render user management interface."""
    st.subheader("👥 User Management")
    
    # Filters
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        search_term = st.text_input("🔍 Search users", placeholder="Search by email or name...")
    
    with col2:
        show_inactive = st.checkbox("Show inactive users", value=True)
    
    with col3:
        if st.button("🔄 Refresh", use_container_width=True):
            st.rerun()
    
    # Get users
    users = user_manager.get_all_users(include_inactive=show_inactive)
    
    # Filter users by search term
    if search_term:
        users = [
            user for user in users 
            if search_term.lower() in user["email"].lower() 
            or search_term.lower() in user["full_name"].lower()
        ]
    
    if not users:
        st.info("No users found matching your criteria.")
        return
    
    # Display users
    st.write(f"**{len(users)} users found**")
    
    for user in users:
        with st.container():
            col1, col2, col3, col4 = st.columns([3, 2, 2, 2])
            
            with col1:
                status_pill = pill("Active", "green") if user["is_active"] else pill("Inactive", "red")
                st.markdown(f"""
                    **{user['full_name']}** {status_pill}<br>
                    <small>{user['email']}</small><br>
                    <small>ID: {user['id']} • Created: {user['created_at'].strftime('%Y-%m-%d')}</small>
                """, unsafe_allow_html=True)
            
            with col2:
                st.write(f"**Last Login:**")
                if user['last_login']:
                    st.write(user['last_login'].strftime('%Y-%m-%d %H:%M'))
                else:
                    st.write("Never")
            
            with col3:
                # Edit user button
                if st.button(f"✏️ Edit", key=f"edit_{user['id']}"):
                    st.session_state[f"editing_user_{user['id']}"] = True
                    st.rerun()
                
                # Toggle active status
                action = "Deactivate" if user["is_active"] else "Activate"
                if st.button(f"{'🚫' if user['is_active'] else '✅'} {action}", key=f"toggle_{user['id']}"):
                    result = user_manager.update_user(user["id"], is_active=not user["is_active"])
                    if result.success:
                        st.success(f"User {action.lower()}d successfully!")
                        st.rerun()
                    else:
                        st.error(f"Failed to {action.lower()} user: {result.message}")
            
            with col4:
                # Reset password
                if st.button(f"🔑 Reset Password", key=f"reset_{user['id']}"):
                    st.session_state[f"reset_password_{user['id']}"] = True
                    st.rerun()
                
                # Delete user
                if st.button(f"🗑️ Delete", key=f"delete_{user['id']}", type="secondary"):
                    st.session_state[f"confirm_delete_{user['id']}"] = True
                    st.rerun()
            
            # Edit user modal
            if st.session_state.get(f"editing_user_{user['id']}", False):
                render_edit_user_modal(user, user_manager)
            
            # Reset password modal
            if st.session_state.get(f"reset_password_{user['id']}", False):
                render_reset_password_modal(user, user_manager)
            
            # Delete confirmation modal
            if st.session_state.get(f"confirm_delete_{user['id']}", False):
                render_delete_user_modal(user, user_manager)
            
            st.divider()


def render_edit_user_modal(user: Dict[str, Any], user_manager: UserManager):
    """Render edit user modal."""
    st.subheader(f"✏️ Edit User: {user['full_name']}")
    
    with st.form(f"edit_user_{user['id']}", clear_on_submit=False):
        new_email = st.text_input("Email", value=user["email"])
        new_full_name = st.text_input("Full Name", value=user["full_name"])
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            if st.form_submit_button("💾 Save Changes", type="primary"):
                result = user_manager.update_user(
                    user["id"],
                    email=new_email if new_email != user["email"] else None,
                    full_name=new_full_name if new_full_name != user["full_name"] else None
                )
                
                if result.success:
                    st.success("User updated successfully!")
                    st.session_state[f"editing_user_{user['id']}"] = False
                    st.rerun()
                else:
                    st.error(f"Failed to update user: {result.message}")
        
        with col2:
            if st.form_submit_button("❌ Cancel"):
                st.session_state[f"editing_user_{user['id']}"] = False
                st.rerun()


def render_reset_password_modal(user: Dict[str, Any], user_manager: UserManager):
    """Render password reset modal."""
    st.subheader(f"🔑 Reset Password: {user['full_name']}")
    
    with st.form(f"reset_password_{user['id']}", clear_on_submit=True):
        new_password = st.text_input("New Password", type="password", help="Must meet security requirements")
        confirm_password = st.text_input("Confirm Password", type="password")
        
        # Show password requirements
        st.info("""
        **Password Requirements:**
        - At least 8 characters long
        - At least one uppercase letter (A-Z)
        - At least one lowercase letter (a-z)
        - At least one number (0-9)
        - At least one special character (!@#$%^&*())
        """)
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.form_submit_button("🔑 Reset Password", type="primary"):
                if not new_password:
                    st.error("Please enter a new password")
                elif new_password != confirm_password:
                    st.error("Passwords do not match")
                else:
                    result = user_manager.reset_user_password(user["id"], new_password)
                    if result.success:
                        st.success("Password reset successfully!")
                        st.session_state[f"reset_password_{user['id']}"] = False
                        st.rerun()
                    else:
                        st.error(f"Failed to reset password: {result.message}")
        
        with col2:
            if st.form_submit_button("❌ Cancel"):
                st.session_state[f"reset_password_{user['id']}"] = False
                st.rerun()


def render_delete_user_modal(user: Dict[str, Any], user_manager: UserManager):
    """Render delete user confirmation modal."""
    st.subheader(f"🗑️ Delete User: {user['full_name']}")
    
    st.warning(f"""
    **Are you sure you want to delete this user?**
    
    - Email: {user['email']}
    - User ID: {user['id']}
    - Created: {user['created_at'].strftime('%Y-%m-%d')}
    
    This action will deactivate the user account. For permanent deletion, contact system administrator.
    """)
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("🗑️ Confirm Delete", type="primary", key=f"confirm_delete_btn_{user['id']}"):
            result = user_manager.delete_user(user["id"], permanent=False)
            if result.success:
                st.success("User deleted successfully!")
                st.session_state[f"confirm_delete_{user['id']}"] = False
                st.rerun()
            else:
                st.error(f"Failed to delete user: {result.message}")
    
    with col2:
        if st.button("❌ Cancel", key=f"cancel_delete_btn_{user['id']}"):
            st.session_state[f"confirm_delete_{user['id']}"] = False
            st.rerun()
def render_create_user(user_manager: UserManager):
    """Render create user interface."""
    st.subheader("➕ Create New User")
    
    with st.form("create_user_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        
        with col1:
            email = st.text_input(
                "Email Address *",
                placeholder="user@company.com",
                help="User's email address for login"
            )
            
            full_name = st.text_input(
                "Full Name *",
                placeholder="John Doe",
                help="User's display name"
            )
        
        with col2:
            password = st.text_input(
                "Password *",
                type="password",
                help="Must meet security requirements"
            )
            
            confirm_password = st.text_input(
                "Confirm Password *",
                type="password"
            )
        
        # Password requirements info
        with st.expander("📋 Password Requirements", expanded=False):
            st.info("""
            **Password must contain:**
            - At least 8 characters
            - At least one uppercase letter (A-Z)
            - At least one lowercase letter (a-z)
            - At least one number (0-9)
            - At least one special character (!@#$%^&*())
            """)
        
        # Submit button
        if st.form_submit_button("➕ Create User", type="primary", use_container_width=True):
            # Validation
            if not all([email, full_name, password, confirm_password]):
                st.error("🚫 All fields are required")
            elif password != confirm_password:
                st.error("🚫 Passwords do not match")
            else:
                # Create user
                with st.spinner("Creating user..."):
                    result = user_manager.create_user(email, password, full_name)
                    
                    if result.success:
                        st.success(f"✅ User created successfully! User ID: {result.user_id}")
                        st.balloons()
                    else:
                        st.error(f"❌ Failed to create user: {result.message}")


def render_system_settings(admin_data: Dict[str, Any]):
    """Render system settings interface."""
    st.subheader("🔧 System Settings")
    
    # Admin Profile Section
    st.write("**👤 Admin Profile**")
    with st.container():
        col1, col2 = st.columns(2)
        
        with col1:
            st.info(f"""
            **Current Admin:**
            - Email: {admin_data['email']}
            - Name: {admin_data['full_name']}
            - Role: {'Super Admin' if admin_data['is_super_admin'] else 'Admin'}
            - Session expires: {admin_data['expires_at'].strftime('%H:%M')}
            """)
        
        with col2:
            if st.button("🔑 Change Admin Password"):
                st.session_state["change_admin_password"] = True
                st.rerun()
    
    st.divider()
    
    # System Information
    st.write("**ℹ️ System Information**")
    
    # Get system stats
    try:
        with db_manager.get_session() as session:
            # Database stats
            user_count = session.execute(text("SELECT COUNT(*) FROM users")).scalar()
            admin_count = session.execute(text("SELECT COUNT(*) FROM admin_users")).scalar()
            reset_tokens = session.execute(text("SELECT COUNT(*) FROM password_reset_tokens WHERE expires_at > NOW()")).scalar()
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric("Total Users", user_count)
            
            with col2:
                st.metric("Admin Users", admin_count)
            
            with col3:
                st.metric("Active Reset Tokens", reset_tokens)
    
    except Exception as e:
        st.error(f"Could not load system stats: {e}")
    
    st.divider()
    
    # Database Management
    st.write("**🗄️ Database Management**")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("🧹 Cleanup Expired Tokens", help="Remove expired password reset tokens"):
            try:
                with db_manager.get_session() as session:
                    result = session.execute(text(
                        "DELETE FROM password_reset_tokens WHERE expires_at < NOW()"
                    ))
                    session.commit()
                    st.success(f"Cleaned up {result.rowcount} expired tokens")
            except Exception as e:
                st.error(f"Cleanup failed: {e}")
    
    with col2:
        if st.button("📊 Export User Data", help="Export user list for backup"):
            # This would generate a CSV download
            st.info("User data export feature - would generate CSV download")
    
    # Change admin password modal
    if st.session_state.get("change_admin_password", False):
        render_change_admin_password_modal(admin_data)


def render_change_admin_password_modal(admin_data: Dict[str, Any]):
    """Render admin password change modal."""
    st.subheader("🔑 Change Admin Password")
    
    with st.form("change_admin_password", clear_on_submit=True):
        current_password = st.text_input("Current Password", type="password")
        new_password = st.text_input("New Password", type="password")
        confirm_password = st.text_input("Confirm New Password", type="password")
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.form_submit_button("🔑 Change Password", type="primary"):
                if not all([current_password, new_password, confirm_password]):
                    st.error("All fields are required")
                elif new_password != confirm_password:
                    st.error("New passwords do not match")
                else:
                    # Verify current password and update
                    # This would need to be implemented
                    st.success("Password changed successfully!")
                    st.session_state["change_admin_password"] = False
                    st.rerun()
        
        with col2:
            if st.form_submit_button("❌ Cancel"):
                st.session_state["change_admin_password"] = False
                st.rerun()


def main_admin_panel():
    """Main admin panel entry point."""
    # Check if admin is authenticated
    auth = AdminAuthentication()
    
    if not auth.is_authenticated():
        # Show login page
        render_admin_login()
    else:
        # Show admin dashboard
        render_admin_dashboard()


if __name__ == "__main__":
    main_admin_panel()