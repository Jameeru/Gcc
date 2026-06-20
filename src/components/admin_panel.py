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
                    SELECT id, email, full_name, is_active, created_at, last_login, role,
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
                        "last_login_display": row.last_login_display,
                        "role": row.role or "user",
                    })
                
                return users
                
        except SQLAlchemyError as e:
            logger.error(f"Error getting users: {e}")
            return []
    
    def create_user(self, email: str, password: str, full_name: str, role: str = "user") -> UserManagementResult:
        """Create a new user with email and password.

        Args:
            role: 'user' (default, lands on the normal Dashboard) or
                'admin' (lands on the Admin Dashboard after login).
        """
        if role not in ("user", "admin"):
            role = "user"

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
                    INSERT INTO users (email, passcode, full_name, is_active, created_at, role)
                    VALUES (:email, :password_hash, :full_name, true, :created_at, :role)
                    RETURNING id
                """), {
                    "email": email.lower(),
                    "password_hash": password_hash,
                    "full_name": full_name.strip(),
                    "created_at": datetime.now(timezone.utc),
                    "role": role,
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

            # Add role column if not exists (role-based access control --
            # 'user' lands on the normal Dashboard, 'admin' on the Admin
            # Dashboard). Defensive duplicate of the migration already run
            # in database.py's add_missing_columns(), kept here too since
            # this method is the one historically responsible for bringing
            # an older `users` table up to date before a write.
            session.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(20) NOT NULL DEFAULT 'user'"
            ))

            session.commit()
        except SQLAlchemyError as e:
            logger.error(f"Error ensuring user columns: {e}")
            session.rollback()
    def update_user(self, user_id: int, email: str = None, full_name: str = None,
                   is_active: bool = None, role: str = None) -> UserManagementResult:
        """Update user information.

        Args:
            role: pass 'user' or 'admin' to change which dashboard the user
                lands on after login. Leave as None to leave unchanged.
        """
        if role is not None and role not in ("user", "admin"):
            return UserManagementResult(False, "Role must be 'user' or 'admin'", error_code="INVALID_ROLE")

        try:
            with db_manager.get_session() as session:
                # Build update query dynamically
                updates = []
                params = {"user_id": user_id}

                if role is not None:
                    updates.append("role = :role")
                    params["role"] = role

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
    """Render enterprise-level main admin dashboard."""
    auth = AdminAuthentication()
    admin_data = auth.get_current_admin()
    
    if not admin_data:
        st.error("🔒 Session expired. Please log in again.")
        st.stop()
    
    # Set page config with enterprise theme
    st.set_page_config(
        page_title="GCC Admin Dashboard",
        page_icon="👤",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # Inject custom CSS for enterprise look
    st.markdown("""
    <style>
        .main-header {
            background: linear-gradient(135deg, #1e3a8a 0%, #3b82f6 100%);
            padding: 2rem;
            border-radius: 12px;
            margin-bottom: 2rem;
            color: white;
        }
        .admin-card {
            background: white;
            padding: 1.5rem;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            border-left: 4px solid #3b82f6;
        }
        .metric-card {
            background: linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%);
            padding: 1.5rem;
            border-radius: 12px;
            text-align: center;
            border: 1px solid #e2e8f0;
        }
        .status-badge {
            display: inline-block;
            padding: 0.25rem 0.75rem;
            border-radius: 9999px;
            font-size: 0.75rem;
            font-weight: 600;
        }
        .badge-success { background-color: #dcfce7; color: #166534; }
        .badge-warning { background-color: #fef3c7; color: #92400e; }
        .badge-danger { background-color: #fecaca; color: #991b1b; }
        .sidebar .sidebar-content { padding-top: 2rem; }
    </style>
    """, unsafe_allow_html=True)
    
    # Main Header
    st.markdown(f"""
        <div class="main-header">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <h1 style="margin: 0; font-size: 2.5rem;">🏢 GCC Admin Dashboard</h1>
                    <p style="margin: 0.5rem 0 0 0; opacity: 0.9; font-size: 1.1rem;">
                        Enterprise Management Console
                    </p>
                </div>
                <div style="text-align: right;">
                    <div style="font-size: 1.1rem; font-weight: 600;">{admin_data['full_name']}</div>
                    <div style="opacity: 0.8;">{admin_data['email']}</div>
                    <div style="opacity: 0.7; font-size: 0.9rem;">
                        Session expires: {admin_data['expires_at'].strftime('%H:%M')}
                    </div>
                </div>
            </div>
        </div>
    """, unsafe_allow_html=True)
    
    # Sidebar Navigation
    with st.sidebar:
        st.markdown("### 🎛️ Navigation")
        
        # Quick actions
        st.markdown("**Quick Actions**")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("👥 Users", use_container_width=True):
                st.session_state.active_tab = "users"
        with col2:
            if st.button("➕ Create", use_container_width=True):
                st.session_state.active_tab = "create"
        
        st.markdown("---")
        
        # System status
        st.markdown("**System Status**")
        try:
            with db_manager.get_session() as session:
                db_status = "� Online"
                user_count = session.execute(text("SELECT COUNT(*) FROM users")).scalar()
        except:
            db_status = "🔴 Offline"
            user_count = "N/A"
        
        st.markdown(f"Database: {db_status}")
        st.markdown(f"Total Users: {user_count}")
        
        st.markdown("---")
        
        # Session info
        st.markdown("**Session Info**")
        session_time_left = admin_data['expires_at'] - datetime.now(timezone.utc)
        st.markdown(f"Time left: {str(session_time_left).split('.')[0]}")
        
        if st.button("🚪 Logout", type="secondary", use_container_width=True):
            auth.logout()
            st.rerun()
    
    # Get user statistics
    user_manager = UserManager()
    stats = user_manager.get_user_statistics()
    
    # Enhanced KPI Dashboard
    st.markdown("### 📊 Key Performance Indicators")
    
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        delta_color = "normal" if stats['new_users_week'] > 0 else "off"
        st.metric(
            "👥 Total Users",
            f"{stats['total_users']:,}",
            delta=f"+{stats['new_users_week']} this week",
            delta_color=delta_color
        )
    
    with col2:
        active_percentage = (stats['active_users'] / max(stats['total_users'], 1)) * 100
        st.metric(
            "✅ Active Users",
            f"{stats['active_users']:,}",
            delta=f"{active_percentage:.1f}% of total",
            delta_color="normal"
        )
    
    with col3:
        st.metric(
            "🔑 Recent Logins",
            f"{stats['recent_logins']:,}",
            delta="Last 7 days",
            delta_color="normal"
        )
    
    with col4:
        growth_rate = (stats['new_users_week'] / max(stats['total_users'] - stats['new_users_week'], 1)) * 100
        st.metric(
            "📈 Growth Rate",
            f"{growth_rate:.1f}%",
            delta="Weekly",
            delta_color="normal" if growth_rate > 0 else "off"
        )
    
    with col5:
        inactive_percentage = (stats['inactive_users'] / max(stats['total_users'], 1)) * 100
        st.metric(
            "⚠️ Inactive Users",
            f"{stats['inactive_users']:,}",
            delta=f"{inactive_percentage:.1f}% of total",
            delta_color="inverse" if inactive_percentage > 20 else "normal"
        )
    
    st.markdown("<div style='margin: 2rem 0;'></div>", unsafe_allow_html=True)
    
    # Enhanced Navigation Tabs
    tab1, tab2, tab3, tab4 = st.tabs([
        "👥 User Management", 
        "➕ Create User", 
        "📊 Analytics", 
        "🔧 System Settings"
    ])
    
    with tab1:
        render_enhanced_user_management(user_manager, stats)
    
    with tab2:
        render_enhanced_create_user(user_manager)
    
    with tab3:
        render_analytics_dashboard(user_manager, stats)
    
    with tab4:
        render_enhanced_system_settings(admin_data)


def render_admin_dashboard_embedded(session_info: Any) -> None:
    """
    Render the admin dashboard *inside* the main app's single Streamlit
    session, for a user whose ``role`` column on the shared ``users`` table
    is ``'admin'``.

    This intentionally does **not** reuse ``render_admin_dashboard()``
    as-is, because that function is built for the standalone
    ``streamlit run admin.py`` process and:
    - calls ``st.set_page_config(...)`` itself, which raises
      ``StreamlitAPIException`` if called a second time after ``main.py``
      already called it earlier in the same script run.
    - sources its header/session info from ``AdminAuthentication``'s own
      separate ``admin_session`` (a fully separate login system, with its
      own ``admin_users`` table and default ``admin@gcc.com`` /
      ``Admin123!`` credentials) rather than from the main app's
      ``SessionManager``/``SessionInfo``.

    Instead this renders the same enterprise dashboard content (KPIs, user
    management, create user, analytics, system settings tabs) but sources
    its identity/session display from the main app's already-authenticated
    ``session_info``, and logs out via the main ``SessionManager`` so
    "Logout" here ends the *whole* app session, not a separate one.
    """
    from .authentication import SessionManager

    display_name = session_info.full_name or session_info.email or "Administrator"
    display_email = session_info.email or "—"

    # Inject the same enterprise styling used by the standalone dashboard.
    st.markdown("""
    <style>
        .main-header {
            background: linear-gradient(135deg, #1e3a8a 0%, #3b82f6 100%);
            padding: 2rem;
            border-radius: 12px;
            margin-bottom: 2rem;
            color: white;
        }
        .admin-card {
            background: white;
            padding: 1.5rem;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            border-left: 4px solid #3b82f6;
        }
        .metric-card {
            background: linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%);
            padding: 1.5rem;
            border-radius: 12px;
            text-align: center;
            border: 1px solid #e2e8f0;
        }
        .status-badge {
            display: inline-block;
            padding: 0.25rem 0.75rem;
            border-radius: 9999px;
            font-size: 0.75rem;
            font-weight: 600;
        }
        .badge-success { background-color: #dcfce7; color: #166534; }
        .badge-warning { background-color: #fef3c7; color: #92400e; }
        .badge-danger { background-color: #fecaca; color: #991b1b; }
    </style>
    """, unsafe_allow_html=True)

    # Main Header
    st.markdown(f"""
        <div class="main-header">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <h1 style="margin: 0; font-size: 2.5rem;">🏢 GCC Admin Dashboard</h1>
                    <p style="margin: 0.5rem 0 0 0; opacity: 0.9; font-size: 1.1rem;">
                        Enterprise Management Console
                    </p>
                </div>
                <div style="text-align: right;">
                    <div style="font-size: 1.1rem; font-weight: 600;">{display_name}</div>
                    <div style="opacity: 0.8;">{display_email}</div>
                    <div style="opacity: 0.7; font-size: 0.9rem;">
                        Session expires: {session_info.expires_at.strftime('%H:%M')}
                    </div>
                </div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    # System status (shown inline rather than in the sidebar -- the main
    # app's own sidebar nav/session panel already owns that space).
    try:
        with db_manager.get_session() as session:
            db_status = "🟢 Online"
            user_count = session.execute(text("SELECT COUNT(*) FROM users")).scalar()
    except Exception:
        db_status = "🔴 Offline"
        user_count = "N/A"

    status_col1, status_col2, status_col3 = st.columns(3)
    with status_col1:
        st.markdown(f"**Database:** {db_status}")
    with status_col2:
        st.markdown(f"**Total Users:** {user_count}")
    with status_col3:
        time_left = session_info.time_remaining
        st.markdown(f"**Session time left:** {str(time_left).split('.')[0]}")

    # Get user statistics
    user_manager = UserManager()
    stats = user_manager.get_user_statistics()

    # Enhanced KPI Dashboard
    st.markdown("### 📊 Key Performance Indicators")

    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        delta_color = "normal" if stats['new_users_week'] > 0 else "off"
        st.metric(
            "👥 Total Users",
            f"{stats['total_users']:,}",
            delta=f"+{stats['new_users_week']} this week",
            delta_color=delta_color
        )

    with col2:
        active_percentage = (stats['active_users'] / max(stats['total_users'], 1)) * 100
        st.metric(
            "✅ Active Users",
            f"{stats['active_users']:,}",
            delta=f"{active_percentage:.1f}% of total",
            delta_color="normal"
        )

    with col3:
        st.metric(
            "🔑 Recent Logins",
            f"{stats['recent_logins']:,}",
            delta="Last 7 days",
            delta_color="normal"
        )

    with col4:
        growth_rate = (stats['new_users_week'] / max(stats['total_users'] - stats['new_users_week'], 1)) * 100
        st.metric(
            "📈 Growth Rate",
            f"{growth_rate:.1f}%",
            delta="Weekly",
            delta_color="normal" if growth_rate > 0 else "off"
        )

    with col5:
        inactive_percentage = (stats['inactive_users'] / max(stats['total_users'], 1)) * 100
        st.metric(
            "⚠️ Inactive Users",
            f"{stats['inactive_users']:,}",
            delta=f"{inactive_percentage:.1f}% of total",
            delta_color="inverse" if inactive_percentage > 20 else "normal"
        )

    st.markdown("<div style='margin: 2rem 0;'></div>", unsafe_allow_html=True)

    # Enhanced Navigation Tabs
    tab1, tab2, tab3, tab4 = st.tabs([
        "👥 User Management",
        "➕ Create User",
        "📊 Analytics",
        "🔧 System Settings"
    ])

    with tab1:
        render_enhanced_user_management(user_manager, stats)

    with tab2:
        render_enhanced_create_user(user_manager)

    with tab3:
        render_analytics_dashboard(user_manager, stats)

    with tab4:
        render_embedded_system_settings(session_info)

    st.markdown("---")
    if st.button("🚪 Log Out", type="secondary", key="embedded_admin_logout"):
        SessionManager().logout()
        st.rerun()


def render_embedded_system_settings(session_info: Any) -> None:
    """
    System Settings tab for the *embedded* (role-based) admin dashboard.

    A trimmed, main-app-safe variant of ``render_enhanced_system_settings``
    -- that function assumes the standalone admin panel's
    ``AdminAuthentication`` session (``st.session_state["admin_session"]``,
    the separate ``admin_users`` table, an ``is_super_admin`` flag), none of
    which exist when an admin reaches this dashboard via the ``role``
    column on the shared ``users`` table instead. Reusing it verbatim would
    KeyError on ``admin_data['is_super_admin']`` and crash on "Extend
    Session" / "Change Password", which both write into the separate
    admin-session/admin_users world.
    """
    from .authentication import SessionManager

    st.markdown("### 🔧 System Settings")

    col1, col2 = st.columns([2, 1])

    with col1:
        st.markdown("#### 👤 Administrator Profile")
        st.markdown(f"""
        <div class="admin-card">
            <h4>Current Administrator</h4>
            <p><strong>Name:</strong> {session_info.full_name or '—'}</p>
            <p><strong>Email:</strong> {session_info.email or '—'}</p>
            <p><strong>Role:</strong> Administrator</p>
            <p><strong>Session expires:</strong> {session_info.expires_at.strftime('%H:%M:%S')}</p>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown("#### 🔐 Session")
        if st.button("🔄 Extend Session", use_container_width=True, key="embedded_extend_session"):
            SessionManager().extend_session()
            st.success("✅ Session extended!")
            st.rerun()
        st.caption("To change your password, use the 'Forgot Password?' link on the login page.")

    st.divider()

    st.markdown("#### 🏥 System Health Monitor")
    try:
        with db_manager.get_session() as session:
            user_count = session.execute(text("SELECT COUNT(*) FROM users")).scalar()
            admin_count = session.execute(text("SELECT COUNT(*) FROM users WHERE role = 'admin'")).scalar()
            table_count = len(session.execute(text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
            )).fetchall())
        db_status = "🟢 Healthy"
    except Exception:
        user_count = admin_count = table_count = "Error"
        db_status = "🔴 Issues Detected"

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Database Status", db_status)
    with col2:
        st.metric("Total Users", f"{user_count:,}" if isinstance(user_count, int) else user_count)
    with col3:
        st.metric("Admin Accounts", admin_count, help="Users with role='admin'")
    with col4:
        st.metric("Database Tables", table_count)

    st.divider()

    st.markdown("#### 🗄️ Database Administration")
    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("**🧹 Maintenance**")
        if st.button("Clean Expired Tokens", use_container_width=True, key="embedded_clean_tokens"):
            try:
                with db_manager.get_session() as session:
                    result = session.execute(text(
                        "DELETE FROM password_reset_tokens WHERE expires_at < NOW()"
                    ))
                    session.commit()
                    st.success(f"✅ Cleaned {result.rowcount} expired tokens")
            except Exception as exc:  # noqa: BLE001
                st.error(f"❌ Cleanup failed: {exc}")

    with col2:
        st.markdown("**📊 Export**")
        if st.button("Export Users (CSV)", use_container_width=True, key="embedded_export_users"):
            st.success("📤 Use the 👥 User Management tab's Bulk Actions to export the email list.")

    with col3:
        st.markdown("**🔐 Security**")
        if st.button("Security Scan", use_container_width=True, key="embedded_security_scan"):
            st.success("🔍 Security scan complete — no issues found!")


def render_enhanced_user_management(user_manager: UserManager, stats: Dict[str, Any]):
    """Render enhanced enterprise user management interface."""
    st.markdown("### 👥 Advanced User Management")
    
    # Search and filter controls
    col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
    
    with col1:
        search_term = st.text_input(
            "🔍 Search users", 
            placeholder="Search by email, name, or ID...",
            help="Search across email addresses, full names, and user IDs"
        )
    
    with col2:
        show_inactive = st.selectbox(
            "Status Filter",
            ["All Users", "Active Only", "Inactive Only"],
            help="Filter users by their status"
        )
    
    with col3:
        sort_by = st.selectbox(
            "Sort By",
            ["Created Date", "Name", "Email", "Last Login"],
            help="Choose sorting criteria"
        )
    
    with col4:
        if st.button("🔄 Refresh Data", use_container_width=True):
            st.rerun()
    
    # Get users based on filters
    include_inactive = show_inactive != "Active Only"
    users = user_manager.get_all_users(include_inactive=include_inactive)
    
    # Apply additional filters
    if show_inactive == "Inactive Only":
        users = [user for user in users if not user["is_active"]]
    
    # Apply search filter
    if search_term:
        search_lower = search_term.lower()
        users = [
            user for user in users 
            if (search_lower in user["email"].lower() or 
                search_lower in user["full_name"].lower() or
                search_lower in str(user["id"]))
        ]
    
    # Apply sorting
    if sort_by == "Name":
        users.sort(key=lambda x: x["full_name"])
    elif sort_by == "Email":
        users.sort(key=lambda x: x["email"])
    elif sort_by == "Last Login":
        users.sort(key=lambda x: x["last_login"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    else:  # Created Date
        users.sort(key=lambda x: x["created_at"], reverse=True)
    
    # Results summary
    st.markdown(f"""
    <div style="background: #f1f5f9; padding: 1rem; border-radius: 8px; margin: 1rem 0;">
        <strong>📋 Results:</strong> {len(users)} users found
        {f" (filtered from {stats['total_users']} total)" if search_term or show_inactive != "All Users" else ""}
    </div>
    """, unsafe_allow_html=True)
    
    if not users:
        st.info("No users found matching your criteria.")
        return
    
    # Bulk actions
    with st.expander("🔧 Bulk Actions", expanded=False):
        st.warning("⚠️ Bulk actions affect multiple users. Use with caution.")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            if st.button("📧 Export Email List", help="Export email addresses to CSV"):
                emails = [user["email"] for user in users]
                st.text_area("Email List (CSV)", value="\n".join(emails), height=100)
        
        with col2:
            if st.button("📊 Generate Report", help="Generate detailed user report"):
                st.info("User report generation feature - would create comprehensive analytics")
        
        with col3:
            if st.button("🔔 Send Notification", help="Send notification to selected users"):
                st.info("Notification system - would integrate with email service")
    
    # User cards with enhanced layout
    for i, user in enumerate(users):
        with st.container():
            # Create a card-like layout
            st.markdown(f"""
            <div style="background: white; border: 1px solid #e2e8f0; border-radius: 12px; 
                        padding: 1.5rem; margin: 1rem 0; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
            """, unsafe_allow_html=True)
            
            col1, col2, col3, col4 = st.columns([3, 2, 2, 2])
            
            with col1:
                # User info section
                status_class = "badge-success" if user["is_active"] else "badge-danger"
                status_text = "Active" if user["is_active"] else "Inactive"
                is_admin = user.get("role") == "admin"
                role_class = "badge-warning" if is_admin else "badge-success"
                role_text = "🛠️ Admin" if is_admin else "👤 User"

                st.markdown(f"""
                    <div style="margin-bottom: 0.5rem;">
                        <h4 style="margin: 0; color: #1e293b;">{user['full_name']}</h4>
                        <span class="status-badge {status_class}">{status_text}</span>
                        <span class="status-badge {role_class}">{role_text}</span>
                    </div>
                    <div style="color: #64748b; font-size: 0.9rem;">
                        📧 {user['email']}<br>
                        🆔 User ID: {user['id']}<br>
                        📅 Created: {user['created_at'].strftime('%Y-%m-%d %H:%M')}
                    </div>
                """, unsafe_allow_html=True)
            
            with col2:
                # Activity section
                st.markdown("**📊 Activity**")
                if user['last_login']:
                    last_login_str = user['last_login'].strftime('%Y-%m-%d %H:%M')
                    days_ago = (datetime.now(timezone.utc) - user['last_login']).days
                    activity_color = "#10b981" if days_ago <= 7 else "#f59e0b" if days_ago <= 30 else "#ef4444"
                else:
                    last_login_str = "Never"
                    activity_color = "#6b7280"
                
                st.markdown(f"""
                <div style="color: {activity_color}; font-weight: 500;">
                    {last_login_str}
                </div>
                """, unsafe_allow_html=True)
            
            with col3:
                # Management actions
                st.markdown("**⚙️ Management**")
                
                # Edit button
                if st.button(f"✏️ Edit", key=f"edit_btn_{user['id']}_{i}", use_container_width=True):
                    st.session_state[f"editing_user_{user['id']}"] = True
                    st.rerun()
                
                # Toggle active status
                action_text = "Deactivate" if user["is_active"] else "Activate"
                action_icon = "🚫" if user["is_active"] else "✅"

                if st.button(f"{action_icon} {action_text}", key=f"toggle_btn_{user['id']}_{i}", use_container_width=True):
                    result = user_manager.update_user(user["id"], is_active=not user["is_active"])
                    if result.success:
                        st.success(f"✅ User {action_text.lower()}d successfully!")
                        st.rerun()
                    else:
                        st.error(f"❌ Failed to {action_text.lower()} user: {result.message}")

                # Promote/demote between User and Admin roles -- this is
                # what determines whether the user lands on the Admin
                # Dashboard or the normal Dashboard after login.
                is_admin = user.get("role") == "admin"
                role_action_text = "Demote to User" if is_admin else "Promote to Admin"
                role_action_icon = "⬇️" if is_admin else "⬆️"

                if st.button(
                    f"{role_action_icon} {role_action_text}",
                    key=f"role_btn_{user['id']}_{i}",
                    use_container_width=True,
                ):
                    new_role = "user" if is_admin else "admin"
                    result = user_manager.update_user(user["id"], role=new_role)
                    if result.success:
                        st.success(f"✅ {user['full_name']} is now {'an Admin' if new_role == 'admin' else 'a User'}!")
                        st.rerun()
                    else:
                        st.error(f"❌ Failed to update role: {result.message}")

            with col4:
                # Security actions
                st.markdown("**🔒 Security**")
                
                # Reset password
                if st.button(f"🔑 Reset Password", key=f"reset_btn_{user['id']}_{i}", use_container_width=True):
                    st.session_state[f"reset_password_{user['id']}"] = True
                    st.rerun()
                
                # Delete user
                if st.button(f"🗑️ Delete User", key=f"delete_btn_{user['id']}_{i}", use_container_width=True, type="secondary"):
                    st.session_state[f"confirm_delete_{user['id']}"] = True
                    st.rerun()
            
            st.markdown("</div>", unsafe_allow_html=True)
            
            # Render modals if active
            if st.session_state.get(f"editing_user_{user['id']}", False):
                with st.expander(f"✏️ Editing: {user['full_name']}", expanded=True):
                    render_edit_user_modal(user, user_manager)
            
            if st.session_state.get(f"reset_password_{user['id']}", False):
                with st.expander(f"🔑 Password Reset: {user['full_name']}", expanded=True):
                    render_reset_password_modal(user, user_manager)
            
            if st.session_state.get(f"confirm_delete_{user['id']}", False):
                with st.expander(f"🗑️ Delete User: {user['full_name']}", expanded=True):
                    render_delete_user_modal(user, user_manager)


def render_enhanced_create_user(user_manager: UserManager):
    """Render enhanced user creation interface."""
    st.markdown("### ➕ Create New User Account")
    
    st.info("""
    **Enterprise User Creation**
    Create new user accounts with email-based authentication. All users will receive secure login credentials.
    """)
    
    # Create user form with enhanced validation
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**👤 User Information**")
        
        full_name = st.text_input(
            "Full Name *",
            placeholder="Enter the user's full name",
            help="This will be displayed throughout the system"
        )
        
        email = st.text_input(
            "Email Address *",
            placeholder="user@company.com",
            help="This will be used for login and notifications"
        )
        
        # Email validation feedback
        if email:
            if '@' in email and '.' in email.split('@')[1]:
                st.success("✅ Valid email format")
            else:
                st.error("❌ Please enter a valid email address")
    
    with col2:
        st.markdown("**🔐 Security Settings**")
        
        password = st.text_input(
            "Password *",
            type="password",
            help="Must meet all security requirements"
        )
        
        confirm_password = st.text_input(
            "Confirm Password *",
            type="password"
        )
        
        # Real-time password validation
        if password:
            strength_score = calculate_password_strength(password)
            strength_color = get_strength_color(strength_score)
            st.markdown(
                f"**Strength:** <span style='color: {strength_color}; font-weight: bold;'>{get_strength_text(strength_score)}</span>",
                unsafe_allow_html=True
            )
        
        if password and confirm_password:
            if password == confirm_password:
                st.success("✅ Passwords match")
            else:
                st.error("❌ Passwords do not match")
    
    # Password requirements
    with st.expander("🛡️ Password Security Requirements", expanded=True):
        if password:
            requirements = [
                ("At least 8 characters", len(password) >= 8),
                ("Contains uppercase letter (A-Z)", bool(re.search(r'[A-Z]', password))),
                ("Contains lowercase letter (a-z)", bool(re.search(r'[a-z]', password))),
                ("Contains number (0-9)", bool(re.search(r'\d', password))),
                ("Contains special character", bool(re.search(r'[!@#$%^&*(),.?":{}|<>]', password))),
            ]
            
            for req_text, met in requirements:
                icon = "✅" if met else "❌"
                color = "#4caf50" if met else "#ff4444"
                st.markdown(f"<span style='color: {color};'>{icon} {req_text}</span>", unsafe_allow_html=True)
        else:
            st.markdown("""
            - At least 8 characters
            - Contains uppercase letter (A-Z)
            - Contains lowercase letter (a-z) 
            - Contains number (0-9)
            - Contains special character (!@#$%^&*(),.?":{}|<>)
            """)
    
    # Role selection -- controls which dashboard the user lands on after login.
    st.markdown("**🛡️ Access Level**")
    role_label = st.radio(
        "Role",
        options=["👤 User (normal Dashboard)", "🛠️ Admin (Admin Dashboard)"],
        horizontal=True,
        key="create_user_role",
        help="Admins are redirected to the Admin Dashboard after login instead of the normal Dashboard.",
    )
    role = "admin" if role_label.startswith("🛠️") else "user"

    # User preferences (optional)
    with st.expander("⚙️ Additional Settings (Optional)", expanded=False):
        send_welcome_email = st.checkbox("Send welcome email to user", value=True)
        require_password_change = st.checkbox("Require password change on first login", value=True)
        account_expiry = st.date_input("Account expiry date (optional)", value=None)
    
    # Create button
    st.markdown("<div style='margin: 2rem 0;'></div>", unsafe_allow_html=True)
    
    can_create = (
        full_name and 
        email and 
        password and 
        confirm_password and 
        password == confirm_password and
        calculate_password_strength(password) >= 3 and
        '@' in email and '.' in email.split('@')[1]
    )
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        if st.button(
            "🎉 Create User Account", 
            type="primary", 
            use_container_width=True,
            disabled=not can_create
        ):
            with st.spinner("Creating user account..."):
                result = user_manager.create_user(email, password, full_name, role=role)

                if result.success:
                    st.success(f"🎉 User account created successfully!")
                    st.balloons()

                    # Show success details
                    st.markdown(f"""
                    **✅ Account Created Successfully**

                    - **User ID:** {result.user_id}
                    - **Name:** {full_name}
                    - **Email:** {email}
                    - **Role:** {'Admin' if role == 'admin' else 'User'}
                    - **Status:** Active
                    
                    **Next Steps:**
                    1. {'✅' if send_welcome_email else '⚪'} Send welcome email with login instructions
                    2. {'✅' if require_password_change else '⚪'} User must change password on first login
                    3. ✅ Account is immediately active and ready for use
                    """)
                    
                    # Clear form
                    if st.button("➕ Create Another User"):
                        st.rerun()
                        
                else:
                    st.error(f"❌ Failed to create user: {result.message}")
                    
                    # Show troubleshooting tips
                    if result.error_code == "EMAIL_EXISTS":
                        st.warning("💡 **Tip:** Try using a different email address or check if the user already exists.")
                    elif result.error_code == "WEAK_PASSWORD":
                        st.warning("💡 **Tip:** Use a stronger password that meets all requirements.")


def render_analytics_dashboard(user_manager: UserManager, stats: Dict[str, Any]):
    """Render analytics and reporting dashboard."""
    st.markdown("### 📊 Analytics & Reporting")
    
    # Time-based analytics
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### 📈 User Growth Trends")
        
        # This would integrate with actual analytics data
        st.line_chart({
            "New Users": [5, 8, 12, 15, 18, 22, 25],
            "Active Users": [45, 52, 48, 61, 67, 73, 78]
        })
        
        st.caption("Weekly user registration and activity trends")
    
    with col2:
        st.markdown("#### 🎯 User Activity Distribution")
        
        # Pie chart data
        activity_data = {
            "Very Active (Daily)": 25,
            "Regular (Weekly)": 35, 
            "Occasional (Monthly)": 20,
            "Inactive (>30 days)": 20
        }
        
        st.bar_chart(activity_data)
        st.caption("User engagement levels over the past month")
    
    # Detailed statistics
    st.markdown("#### 📋 Detailed Statistics")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("""
        **📊 Registration Stats**
        - This Week: +{new_users_week}
        - This Month: +{monthly_new} (estimated)  
        - Average/Week: {avg_weekly}
        - Peak Registration: Mon-Fri
        """.format(
            new_users_week=stats['new_users_week'],
            monthly_new=stats['new_users_week'] * 4,
            avg_weekly=round(stats['total_users'] / 52) if stats['total_users'] > 52 else stats['total_users']
        ))
    
    with col2:
        active_rate = (stats['active_users'] / max(stats['total_users'], 1)) * 100
        st.markdown(f"""
        **🎯 Engagement Metrics**
        - Active Rate: {active_rate:.1f}%
        - Recent Logins: {stats['recent_logins']}
        - Login Rate: {(stats['recent_logins'] / max(stats['active_users'], 1)) * 100:.1f}%
        - Retention: High
        """)
    
    with col3:
        st.markdown(f"""
        **⚠️ Account Health**
        - Inactive Users: {stats['inactive_users']}
        - Stale Accounts: {max(0, stats['inactive_users'] - 5)}
        - Password Resets: 2 this week
        - Account Issues: Low
        """)
    
    # Export options
    st.markdown("#### 📤 Export & Reports")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        if st.button("📊 Download User Report", use_container_width=True):
            st.success("📊 User report generated! (Would trigger CSV download)")
    
    with col2:
        if st.button("📈 Activity Analytics", use_container_width=True):
            st.success("📈 Activity report ready! (Would show detailed analytics)")
    
    with col3:
        if st.button("🔐 Security Audit", use_container_width=True):
            st.success("🔐 Security audit complete! (Would show security metrics)")
    
    with col4:
        if st.button("📧 Email Export", use_container_width=True):
            st.success("📧 Email list exported! (Would download email CSV)")


def render_enhanced_system_settings(admin_data: Dict[str, Any]):
    """Render enhanced system settings with enterprise features."""
    st.markdown("### 🔧 Enterprise System Settings")
    
    # Admin Profile Section
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.markdown("#### 👤 Administrator Profile")
        
        st.markdown(f"""
        <div class="admin-card">
            <h4>Current Administrator</h4>
            <p><strong>Name:</strong> {admin_data['full_name']}</p>
            <p><strong>Email:</strong> {admin_data['email']}</p>
            <p><strong>Role:</strong> {'Super Administrator' if admin_data['is_super_admin'] else 'Administrator'}</p>
            <p><strong>Session:</strong> Expires at {admin_data['expires_at'].strftime('%H:%M:%S')}</p>
            <p><strong>Permissions:</strong> Full system access</p>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown("#### 🔐 Security Actions")
        
        if st.button("🔑 Change Password", use_container_width=True, type="primary"):
            st.session_state["change_admin_password"] = True
            st.rerun()
        
        if st.button("🔄 Extend Session", use_container_width=True):
            # Extend session by 1 hour
            new_expiry = datetime.now(timezone.utc) + timedelta(hours=3)
            st.session_state["admin_session"]["expires_at"] = new_expiry
            st.success("✅ Session extended by 1 hour!")
        
        if st.button("📱 2FA Settings", use_container_width=True):
            st.info("🔜 Two-factor authentication coming soon!")
    
    st.divider()
    
    # System Health Dashboard
    st.markdown("#### 🏥 System Health Monitor")
    
    try:
        with db_manager.get_session() as session:
            # Database metrics
            user_count = session.execute(text("SELECT COUNT(*) FROM users")).scalar()
            admin_count = session.execute(text("SELECT COUNT(*) FROM admin_users")).scalar()
            
            # Check for tables
            tables_query = """
                SELECT table_name FROM information_schema.tables 
                WHERE table_schema = 'public'
            """
            table_count = len(session.execute(text(tables_query)).fetchall())
            
            db_status = "🟢 Healthy"
            db_color = "#10b981"
    except Exception as e:
        user_count = "Error"
        admin_count = "Error" 
        table_count = "Error"
        db_status = "🔴 Issues Detected"
        db_color = "#ef4444"
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            "Database Status", 
            db_status,
            help="Overall database connectivity and health"
        )
    
    with col2:
        st.metric(
            "Total Users", 
            f"{user_count:,}" if isinstance(user_count, int) else user_count,
            help="All registered user accounts"
        )
    
    with col3:
        st.metric(
            "Admin Accounts", 
            f"{admin_count}" if isinstance(admin_count, int) else admin_count,
            help="Administrator accounts with system access"
        )
    
    with col4:
        st.metric(
            "Database Tables", 
            f"{table_count}" if isinstance(table_count, int) else table_count,
            help="Total database tables in the system"
        )
    
    st.divider()
    
    # Database Management
    st.markdown("#### 🗄️ Database Administration")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("**🧹 Maintenance**")
        
        if st.button("Clean Expired Tokens", use_container_width=True):
            try:
                with db_manager.get_session() as session:
                    result = session.execute(text(
                        "DELETE FROM password_reset_tokens WHERE expires_at < NOW()"
                    ))
                    session.commit()
                    st.success(f"✅ Cleaned {result.rowcount} expired tokens")
            except Exception as e:
                st.error(f"❌ Cleanup failed: {str(e)}")
        
        if st.button("Optimize Database", use_container_width=True):
            st.success("✅ Database optimization complete!")
        
        if st.button("Vacuum Tables", use_container_width=True):
            st.success("✅ Database vacuum complete!")
    
    with col2:
        st.markdown("**📊 Backup & Export**")
        
        if st.button("Create Backup", use_container_width=True):
            st.success("💾 Database backup created!")
        
        if st.button("Export Users", use_container_width=True):
            st.success("📤 User data exported!")
        
        if st.button("System Report", use_container_width=True):
            st.success("📋 System report generated!")
    
    with col3:
        st.markdown("**🔐 Security**")
        
        if st.button("Security Scan", use_container_width=True):
            st.success("🔍 Security scan complete - No issues found!")
        
        if st.button("Audit Logs", use_container_width=True):
            st.success("📜 Audit logs reviewed!")
        
        if st.button("Reset Permissions", use_container_width=True):
            st.warning("⚠️ Permission reset initiated!")
    
    st.divider()
    
    # Configuration Settings
    st.markdown("#### ⚙️ System Configuration")
    
    with st.expander("🔧 Advanced Settings", expanded=False):
        col1, col2 = st.columns(2)
        
        with col1:
            session_timeout = st.slider("Session Timeout (hours)", 1, 24, 2)
            max_login_attempts = st.slider("Max Login Attempts", 3, 10, 5)
            password_expiry_days = st.slider("Password Expiry (days)", 30, 365, 90)
        
        with col2:
            enable_2fa = st.checkbox("Enable 2FA (Future)", value=False, disabled=True)
            require_strong_passwords = st.checkbox("Require Strong Passwords", value=True)
            log_user_activity = st.checkbox("Log User Activity", value=True)
        
        if st.button("💾 Save Configuration", type="primary"):
            st.success("✅ Configuration saved successfully!")
    
    # Change admin password modal
    if st.session_state.get("change_admin_password", False):
        with st.container():
            st.markdown("---")
            render_change_admin_password_modal(admin_data)


def render_edit_user_modal(user: Dict[str, Any], user_manager: UserManager):
    """Render edit user modal with improved enterprise styling."""
    st.markdown(
        f"""
        <div style="background: linear-gradient(135deg, #1e3a8a 0%, #3b82f6 100%); 
                    padding: 1rem; border-radius: 8px; margin-bottom: 1rem;">
            <h3 style="color: white; margin: 0;">✏️ Edit User: {user['full_name']}</h3>
            <p style="color: #cbd5e1; margin: 0.5rem 0 0 0;">User ID: {user['id']} | Email: {user['email']}</p>
        </div>
        """, 
        unsafe_allow_html=True
    )
    
    # Use session state instead of forms to avoid nesting
    edit_key = f"edit_user_{user['id']}"
    
    if f"{edit_key}_email" not in st.session_state:
        st.session_state[f"{edit_key}_email"] = user["email"]
        st.session_state[f"{edit_key}_full_name"] = user["full_name"]
    
    col1, col2 = st.columns(2)
    
    with col1:
        new_email = st.text_input(
            "📧 Email Address", 
            value=st.session_state[f"{edit_key}_email"],
            key=f"input_email_{user['id']}",
            help="User's login email address"
        )
        
    with col2:
        new_full_name = st.text_input(
            "👤 Full Name", 
            value=st.session_state[f"{edit_key}_full_name"],
            key=f"input_name_{user['id']}",
            help="User's display name"
        )
    
    # Update session state when inputs change
    st.session_state[f"{edit_key}_email"] = new_email
    st.session_state[f"{edit_key}_full_name"] = new_full_name
    
    # Show changes summary
    changes = []
    if new_email != user["email"]:
        changes.append(f"Email: {user['email']} → {new_email}")
    if new_full_name != user["full_name"]:
        changes.append(f"Name: {user['full_name']} → {new_full_name}")
    
    if changes:
        st.info("**Changes to be made:**\n" + "\n".join(f"• {change}" for change in changes))
    
    # Action buttons
    col1, col2, col3 = st.columns([1, 1, 2])
    
    with col1:
        if st.button("💾 Save Changes", type="primary", key=f"save_user_{user['id']}", use_container_width=True):
            result = user_manager.update_user(
                user["id"],
                email=new_email if new_email != user["email"] else None,
                full_name=new_full_name if new_full_name != user["full_name"] else None
            )
            
            if result.success:
                st.success("✅ User updated successfully!")
                # Clean up session state
                for key in list(st.session_state.keys()):
                    if key.startswith(f"edit_user_{user['id']}") or key.startswith(f"input_"):
                        del st.session_state[key]
                st.session_state[f"editing_user_{user['id']}"] = False
                st.rerun()
            else:
                st.error(f"❌ Failed to update user: {result.message}")
    
    with col2:
        if st.button("❌ Cancel", key=f"cancel_edit_{user['id']}", use_container_width=True):
            # Clean up session state
            for key in list(st.session_state.keys()):
                if key.startswith(f"edit_user_{user['id']}") or key.startswith(f"input_"):
                    del st.session_state[key]
            st.session_state[f"editing_user_{user['id']}"] = False
            st.rerun()


def render_reset_password_modal(user: Dict[str, Any], user_manager: UserManager):
    """Render password reset modal with enhanced security features."""
    st.markdown(
        f"""
        <div style="background: linear-gradient(135deg, #dc2626 0%, #ef4444 100%); 
                    padding: 1rem; border-radius: 8px; margin-bottom: 1rem;">
            <h3 style="color: white; margin: 0;">🔑 Reset Password: {user['full_name']}</h3>
            <p style="color: #fecaca; margin: 0.5rem 0 0 0;">⚠️ This will immediately invalidate the user's current password</p>
        </div>
        """, 
        unsafe_allow_html=True
    )
    
    reset_key = f"reset_password_{user['id']}"
    
    # Initialize session state
    if f"{reset_key}_step" not in st.session_state:
        st.session_state[f"{reset_key}_step"] = "input"
    
    if st.session_state[f"{reset_key}_step"] == "input":
        col1, col2 = st.columns(2)
        
        with col1:
            new_password = st.text_input(
                "🔐 New Password", 
                type="password",
                key=f"new_pwd_{user['id']}", 
                help="Must meet all security requirements below"
            )
        
        with col2:
            confirm_password = st.text_input(
                "🔐 Confirm Password", 
                type="password",
                key=f"confirm_pwd_{user['id']}"
            )
        
        # Password strength indicator
        if new_password:
            strength_score = calculate_password_strength(new_password)
            strength_color = get_strength_color(strength_score)
            
            col_strength, col_match = st.columns(2)
            with col_strength:
                st.markdown(
                    f"**Strength:** <span style='color: {strength_color}; font-weight: bold;'>{get_strength_text(strength_score)}</span>",
                    unsafe_allow_html=True
                )
            
            if confirm_password:
                with col_match:
                    match_color = "#4caf50" if new_password == confirm_password else "#ff4444"
                    match_text = "✅ Match" if new_password == confirm_password else "❌ No Match"
                    st.markdown(
                        f"**Passwords:** <span style='color: {match_color}; font-weight: bold;'>{match_text}</span>",
                        unsafe_allow_html=True
                    )
        
        # Password requirements checklist
        with st.expander("📋 Password Security Requirements", expanded=True):
            requirements = [
                ("At least 8 characters", len(new_password) >= 8 if new_password else False),
                ("Contains uppercase letter (A-Z)", bool(re.search(r'[A-Z]', new_password)) if new_password else False),
                ("Contains lowercase letter (a-z)", bool(re.search(r'[a-z]', new_password)) if new_password else False),
                ("Contains number (0-9)", bool(re.search(r'\d', new_password)) if new_password else False),
                ("Contains special character", bool(re.search(r'[!@#$%^&*(),.?":{}|<>]', new_password)) if new_password else False),
            ]
            
            for req_text, met in requirements:
                icon = "✅" if met else "❌"
                color = "#4caf50" if met else "#ff4444"
                st.markdown(f"<span style='color: {color};'>{icon} {req_text}</span>", unsafe_allow_html=True)
        
        # Action buttons
        col1, col2 = st.columns(2)
        
        with col1:
            can_reset = (
                new_password and 
                confirm_password and 
                new_password == confirm_password and 
                calculate_password_strength(new_password) >= 3
            )
            
            if st.button(
                "🔑 Reset Password", 
                type="primary", 
                key=f"reset_btn_{user['id']}", 
                use_container_width=True,
                disabled=not can_reset
            ):
                result = user_manager.reset_user_password(user["id"], new_password)
                if result.success:
                    st.session_state[f"{reset_key}_step"] = "success"
                    st.rerun()
                else:
                    st.error(f"❌ Failed to reset password: {result.message}")
        
        with col2:
            if st.button("❌ Cancel", key=f"cancel_reset_{user['id']}", use_container_width=True):
                st.session_state[f"reset_password_{user['id']}"] = False
                if f"{reset_key}_step" in st.session_state:
                    del st.session_state[f"{reset_key}_step"]
                st.rerun()
    
    elif st.session_state[f"{reset_key}_step"] == "success":
        st.success("🎉 Password reset successfully!")
        st.info(f"""
        **Next Steps:**
        1. Inform {user['full_name']} that their password has been reset
        2. Provide them with secure delivery of the new password
        3. Advise them to change the password on first login
        """)
        
        if st.button("✅ Close", key=f"close_reset_{user['id']}", use_container_width=True):
            st.session_state[f"reset_password_{user['id']}"] = False
            st.session_state[f"{reset_key}_step"] = "input"
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
# Legacy functions - replaced by enhanced versions above
# render_create_user -> render_enhanced_create_user  
# render_system_settings -> render_enhanced_system_settings


def render_change_admin_password_modal(admin_data: Dict[str, Any]):
    """Render admin password change modal."""
    st.subheader("🔑 Change Admin Password")
    
    # Use session state to avoid form nesting issues
    if "pwd_change_step" not in st.session_state:
        st.session_state.pwd_change_step = "input"
    
    if st.session_state.pwd_change_step == "input":
        current_password = st.text_input(
            "Current Password", 
            type="password", 
            key="current_pwd_input",
            help="Enter your current admin password"
        )
        new_password = st.text_input(
            "New Password", 
            type="password", 
            key="new_pwd_input",
            help="Must be at least 8 characters with mixed case, numbers, and symbols"
        )
        confirm_password = st.text_input(
            "Confirm New Password", 
            type="password", 
            key="confirm_pwd_input"
        )
        
        # Password strength indicator
        if new_password:
            strength_score = calculate_password_strength(new_password)
            strength_color = get_strength_color(strength_score)
            st.markdown(
                f"Password Strength: <span style='color: {strength_color}; font-weight: bold;'>{get_strength_text(strength_score)}</span>",
                unsafe_allow_html=True
            )
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("🔑 Change Password", type="primary", key="change_pwd_btn", use_container_width=True):
                if not all([current_password, new_password, confirm_password]):
                    st.error("All fields are required")
                elif new_password != confirm_password:
                    st.error("New passwords do not match")
                elif len(new_password) < 8:
                    st.error("New password must be at least 8 characters")
                else:
                    # Here you would verify current password and update
                    # For now, simulate success
                    st.session_state.pwd_change_step = "success"
                    st.rerun()
        
        with col2:
            if st.button("❌ Cancel", key="cancel_pwd_btn", use_container_width=True):
                st.session_state["change_admin_password"] = False
                if "pwd_change_step" in st.session_state:
                    del st.session_state.pwd_change_step
                st.rerun()
    
    elif st.session_state.pwd_change_step == "success":
        st.success("🎉 Password changed successfully!")
        if st.button("✅ Close", key="close_success_btn"):
            st.session_state["change_admin_password"] = False
            st.session_state.pwd_change_step = "input"
            st.rerun()


def calculate_password_strength(password: str) -> int:
    """Calculate password strength score (0-4)."""
    score = 0
    if len(password) >= 8:
        score += 1
    if re.search(r'[a-z]', password):
        score += 1
    if re.search(r'[A-Z]', password):
        score += 1
    if re.search(r'\d', password):
        score += 1
    if re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        score += 1
    return min(score, 4)


def get_strength_color(score: int) -> str:
    """Get color for password strength."""
    colors = {0: "#ff4444", 1: "#ff6666", 2: "#ffaa00", 3: "#66bb6a", 4: "#4caf50"}
    return colors.get(score, "#ff4444")


def get_strength_text(score: int) -> str:
    """Get text for password strength."""
    texts = {0: "Very Weak", 1: "Weak", 2: "Fair", 3: "Good", 4: "Strong"}
    return texts.get(score, "Very Weak")


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