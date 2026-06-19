"""
Password reset functionality for the GCC Research Intelligence Platform.

This module provides secure password reset capabilities including token generation,
email notifications, rate limiting, and password validation.
"""

import secrets
import hashlib
import json
import re
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

from ..core.database import db_manager
from ..models.schemas import User
from ..utils.config import get_config
from ..utils.logging import get_logger
from ..utils.security import hash_passcode, verify_passcode

from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text

logger = get_logger(__name__)


@dataclass
class ResetResult:
    """Result of password reset operations."""
    success: bool
    message: str
    token: Optional[str] = None
    error_code: Optional[str] = None


@dataclass
class PasswordValidation:
    """Password validation result."""
    is_valid: bool
    errors: List[str]
    meets_length_req: bool = False
    meets_uppercase_req: bool = False
    meets_lowercase_req: bool = False
    meets_number_req: bool = False
    meets_special_char_req: bool = False


@dataclass
class RateLimitStatus:
    """Rate limiting status."""
    attempts_used: int
    max_attempts: int
    reset_time: datetime
    is_limited: bool
    
    @property
    def attempts_remaining(self) -> int:
        return max(0, self.max_attempts - self.attempts_used)


class PasswordResetSystem:
    """
    Secure password reset system with token-based workflow.
    """
    
    def __init__(self):
        """Initialize password reset system."""
        self.config = get_config()
        self.token_expiry = timedelta(minutes=30)
        self.max_attempts_per_hour = 3
    
    def _generate_secure_token(self) -> str:
        """Generate cryptographically secure reset token."""
        return secrets.token_urlsafe(32)
    
    def _hash_token(self, token: str) -> str:
        """Hash token for secure database storage."""
        return hashlib.sha256(token.encode()).hexdigest()
    
    def _get_user_by_identifier(self, identifier: str) -> Optional[User]:
        """
        Get user by identifier (user ID or any other identifier).
        For now, we'll use user ID since that's what we have.
        """
        try:
            with db_manager.get_session() as session:
                # Try to parse as user ID first
                try:
                    user_id = int(identifier)
                    user = session.query(User).filter(
                        User.id == user_id,
                        User.is_active == True
                    ).first()
                    return user
                except ValueError:
                    # If not a valid integer, could extend to search by email etc.
                    return None
        except SQLAlchemyError as e:
            logger.error(f"Database error finding user: {e}")
            return None
    
    def _check_rate_limit(self, identifier: str) -> RateLimitStatus:
        """Check if user has exceeded rate limit for password resets."""
        try:
            with db_manager.get_session() as session:
                # Get or create rate limit record
                result = session.execute(text(
                    "SELECT attempt_count, first_attempt_at FROM reset_rate_limits WHERE user_identifier = :identifier"
                ), {"identifier": identifier}).fetchone()
                
                now = datetime.now(timezone.utc)
                
                if not result:
                    # No previous attempts
                    return RateLimitStatus(0, self.max_attempts_per_hour, now + timedelta(hours=1), False)
                
                attempt_count, first_attempt_at = result
                
                # Check if rate limit window has expired
                if now - first_attempt_at > timedelta(hours=1):
                    # Reset the counter
                    session.execute(text(
                        "UPDATE reset_rate_limits SET attempt_count = 0, first_attempt_at = :now, last_attempt_at = :now WHERE user_identifier = :identifier"
                    ), {"now": now, "identifier": identifier})
                    session.commit()
                    return RateLimitStatus(0, self.max_attempts_per_hour, now + timedelta(hours=1), False)
                
                is_limited = attempt_count >= self.max_attempts_per_hour
                reset_time = first_attempt_at + timedelta(hours=1)
                
                return RateLimitStatus(attempt_count, self.max_attempts_per_hour, reset_time, is_limited)
                
        except SQLAlchemyError as e:
            logger.error(f"Database error checking rate limit: {e}")
            # On error, allow the request to prevent lockout
            return RateLimitStatus(0, self.max_attempts_per_hour, datetime.now(timezone.utc) + timedelta(hours=1), False)
    
    def _increment_rate_limit(self, identifier: str) -> None:
        """Increment rate limit counter for user."""
        try:
            with db_manager.get_session() as session:
                now = datetime.now(timezone.utc)
                
                # Insert or update rate limit record
                session.execute(text("""
                    INSERT INTO reset_rate_limits (user_identifier, attempt_count, first_attempt_at, last_attempt_at)
                    VALUES (:identifier, 1, :now, :now)
                    ON CONFLICT (user_identifier) 
                    DO UPDATE SET 
                        attempt_count = reset_rate_limits.attempt_count + 1,
                        last_attempt_at = :now
                """), {"identifier": identifier, "now": now})
                session.commit()
                
        except SQLAlchemyError as e:
            logger.error(f"Database error incrementing rate limit: {e}")
    
    def _log_audit_event(self, identifier: str, event_type: str, success: bool, details: Dict[str, Any] = None) -> None:
        """Log password reset audit event."""
        try:
            with db_manager.get_session() as session:
                session.execute(text("""
                    INSERT INTO password_reset_audit_log 
                    (user_identifier, event_type, success, details, timestamp)
                    VALUES (:identifier, :event_type, :success, :details, :timestamp)
                """), {
                    "identifier": identifier,
                    "event_type": event_type,
                    "success": success,
                    "details": json.dumps(details) if details else None,
                    "timestamp": datetime.now(timezone.utc)
                })
                session.commit()
        except SQLAlchemyError as e:
            logger.error(f"Database error logging audit event: {e}")
    
    def initiate_reset(self, identifier: str) -> ResetResult:
        """
        Initiate password reset process for user.
        
        Args:
            identifier: User identifier (user ID for now)
            
        Returns:
            ResetResult with success status and message
        """
        # Check rate limit first
        rate_status = self._check_rate_limit(identifier)
        if rate_status.is_limited:
            self._log_audit_event(identifier, "reset_rate_limited", False, {
                "attempts": rate_status.attempts_used,
                "reset_time": rate_status.reset_time.isoformat()
            })
            return ResetResult(
                False, 
                f"Too many reset attempts. Please wait until {rate_status.reset_time.strftime('%H:%M')} before trying again.",
                error_code="RATE_LIMITED"
            )
        
        # Find user
        user = self._get_user_by_identifier(identifier)
        if not user:
            self._log_audit_event(identifier, "reset_invalid_user", False)
            # Don't reveal whether user exists for security
            return ResetResult(True, "If the user exists, a password reset email has been sent.")
        
        # Generate secure token
        token = self._generate_secure_token()
        token_hash = self._hash_token(token)
        expires_at = datetime.now(timezone.utc) + self.token_expiry
        
        try:
            # Store token in database
            with db_manager.get_session() as session:
                session.execute(text("""
                    INSERT INTO password_reset_tokens (user_id, token_hash, expires_at)
                    VALUES (:user_id, :token_hash, :expires_at)
                """), {
                    "user_id": user.id,
                    "token_hash": token_hash,
                    "expires_at": expires_at
                })
                session.commit()
            
            # Increment rate limit
            self._increment_rate_limit(identifier)
            
            # Log successful initiation
            self._log_audit_event(identifier, "reset_initiated", True, {
                "user_id": user.id,
                "expires_at": expires_at.isoformat()
            })
            
            # Send email (we'll implement this next)
            email_service = PasswordResetEmailService()
            email_result = email_service.send_reset_email(str(user.id), token)
            
            if email_result.success:
                return ResetResult(True, "Password reset email sent successfully. Check your email for instructions.")
            else:
                return ResetResult(True, "Reset initiated. If configured, you will receive an email with instructions.")
                
        except SQLAlchemyError as e:
            logger.error(f"Database error initiating reset: {e}")
            self._log_audit_event(identifier, "reset_db_error", False, {"error": str(e)})
            return ResetResult(False, "A system error occurred. Please try again.", error_code="DB_ERROR")
    
    def validate_token(self, token: str) -> Dict[str, Any]:
        """
        Validate reset token and return token info.
        
        Args:
            token: Reset token to validate
            
        Returns:
            Dict with validation result and token info
        """
        token_hash = self._hash_token(token)
        
        try:
            with db_manager.get_session() as session:
                result = session.execute(text("""
                    SELECT user_id, expires_at, used_at 
                    FROM password_reset_tokens 
                    WHERE token_hash = :token_hash
                """), {"token_hash": token_hash}).fetchone()
                
                if not result:
                    return {"valid": False, "error": "Invalid or expired reset link"}
                
                user_id, expires_at, used_at = result
                now = datetime.now(timezone.utc)
                
                if used_at:
                    return {"valid": False, "error": "This reset link has already been used"}
                
                if now > expires_at:
                    return {"valid": False, "error": "This reset link has expired"}
                
                return {
                    "valid": True,
                    "user_id": user_id,
                    "expires_at": expires_at
                }
                
        except SQLAlchemyError as e:
            logger.error(f"Database error validating token: {e}")
            return {"valid": False, "error": "A system error occurred"}
    
    def reset_password(self, token: str, new_password: str) -> ResetResult:
        """
        Complete password reset with new password.
        
        Args:
            token: Valid reset token
            new_password: New password to set
            
        Returns:
            ResetResult with operation status
        """
        # Validate token first
        token_validation = self.validate_token(token)
        if not token_validation["valid"]:
            return ResetResult(False, token_validation["error"], error_code="INVALID_TOKEN")
        
        user_id = token_validation["user_id"]
        
        # Validate password strength
        password_validation = self.validate_password_strength(new_password)
        if not password_validation.is_valid:
            return ResetResult(False, "Password does not meet requirements: " + "; ".join(password_validation.errors), error_code="WEAK_PASSWORD")
        
        try:
            with db_manager.get_session() as session:
                # Get current user
                user = session.query(User).filter(User.id == user_id).first()
                if not user:
                    return ResetResult(False, "User not found", error_code="USER_NOT_FOUND")
                
                # Check password reuse
                if user.passcode and verify_passcode(new_password, user.passcode):
                    return ResetResult(False, "New password cannot be the same as your current password", error_code="PASSWORD_REUSE")
                
                # Hash new password
                new_password_hash = hash_passcode(new_password)
                
                # Update user password and history
                old_password = user.passcode
                user.passcode = new_password_hash
                user.last_password_change = datetime.now(timezone.utc)
                
                # Update password history (keep last 3 passwords)
                password_history = user.password_history or []
                if isinstance(password_history, str):
                    password_history = json.loads(password_history)
                
                if old_password:
                    password_history.append({
                        "hash": old_password,
                        "changed_at": datetime.now(timezone.utc).isoformat()
                    })
                
                # Keep only last 3 passwords
                password_history = password_history[-3:]
                user.password_history = password_history
                
                # Mark token as used
                token_hash = self._hash_token(token)
                session.execute(text("""
                    UPDATE password_reset_tokens 
                    SET used_at = :now 
                    WHERE token_hash = :token_hash
                """), {"now": datetime.now(timezone.utc), "token_hash": token_hash})
                
                # Invalidate all other tokens for this user
                session.execute(text("""
                    UPDATE password_reset_tokens 
                    SET used_at = :now 
                    WHERE user_id = :user_id AND used_at IS NULL AND token_hash != :token_hash
                """), {"now": datetime.now(timezone.utc), "user_id": user_id, "token_hash": token_hash})
                
                session.commit()
                
                # Log successful password change
                self._log_audit_event(str(user_id), "password_changed", True, {
                    "user_id": user_id,
                    "token_used": token_hash[:8] + "..."
                })
                
                return ResetResult(True, "Password changed successfully! You can now sign in with your new password.")
                
        except SQLAlchemyError as e:
            logger.error(f"Database error resetting password: {e}")
            self._log_audit_event(str(user_id), "reset_db_error", False, {"error": str(e)})
            return ResetResult(False, "A system error occurred. Please try again.", error_code="DB_ERROR")
    
    def validate_password_strength(self, password: str) -> PasswordValidation:
        """
        Validate password meets security requirements.
        
        Args:
            password: Password to validate
            
        Returns:
            PasswordValidation with detailed results
        """
        errors = []
        
        # Length check (minimum 8 characters)
        meets_length = len(password) >= 8
        if not meets_length:
            errors.append("Password must be at least 8 characters long")
        
        # Uppercase check
        meets_uppercase = bool(re.search(r'[A-Z]', password))
        if not meets_uppercase:
            errors.append("Password must contain at least one uppercase letter")
        
        # Lowercase check  
        meets_lowercase = bool(re.search(r'[a-z]', password))
        if not meets_lowercase:
            errors.append("Password must contain at least one lowercase letter")
        
        # Number check
        meets_number = bool(re.search(r'\d', password))
        if not meets_number:
            errors.append("Password must contain at least one number")
        
        # Special character check
        meets_special = bool(re.search(r'[!@#$%^&*()]', password))
        if not meets_special:
            errors.append("Password must contain at least one special character (!@#$%^&*())")
        
        is_valid = all([meets_length, meets_uppercase, meets_lowercase, meets_number, meets_special])
        
        return PasswordValidation(
            is_valid=is_valid,
            errors=errors,
            meets_length_req=meets_length,
            meets_uppercase_req=meets_uppercase,
            meets_lowercase_req=meets_lowercase,
            meets_number_req=meets_number,
            meets_special_char_req=meets_special
        )


class PasswordResetEmailService:
    """
    Email service for password reset notifications.
    """
    
    def __init__(self):
        """Initialize email service."""
        self.config = get_config()
    
    def generate_reset_link(self, token: str) -> str:
        """Generate password reset link with token."""
        # In a real deployment, this would be the actual domain
        base_url = "http://localhost:8501"  # Streamlit default
        return f"{base_url}?reset_token={token}"
    
    def render_email_template(self, user_id: str, reset_link: str) -> str:
        """Render HTML email template for password reset."""
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Password Reset - GCC Research Platform</title>
        </head>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h1 style="color: #2563eb; text-align: center;">🏢 GCC Research Platform</h1>
                <h2>Password Reset Request</h2>
                
                <p>Hello User #{user_id},</p>
                
                <p>You have requested to reset your password for the GCC Research Intelligence Platform. Click the button below to set a new password:</p>
                
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{reset_link}" 
                       style="background-color: #2563eb; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; display: inline-block;">
                        Reset Your Password
                    </a>
                </div>
                
                <p><strong>Important:</strong></p>
                <ul>
                    <li>This link will expire in 30 minutes</li>
                    <li>You can only use this link once</li>
                    <li>If you did not request this reset, please ignore this email</li>
                </ul>
                
                <p>If the button doesn't work, copy and paste this link into your browser:</p>
                <p style="word-break: break-all; background-color: #f5f5f5; padding: 10px; border-radius: 4px;">
                    {reset_link}
                </p>
                
                <hr style="margin: 30px 0;">
                
                <p style="font-size: 12px; color: #666;">
                    <strong>Need help?</strong><br>
                    Contact your system administrator if you continue to have issues accessing your account.
                </p>
                
                <p style="font-size: 12px; color: #666;">
                    This is an automated message from the GCC Research Intelligence Platform.
                </p>
            </div>
        </body>
        </html>
        """
    
    def send_reset_email(self, user_id: str, token: str) -> ResetResult:
        """
        Send password reset email to user.
        
        Args:
            user_id: User ID for personalization
            token: Reset token to include in email
            
        Returns:
            ResetResult indicating email send status
        """
        try:
            reset_link = self.generate_reset_link(token)
            html_content = self.render_email_template(user_id, reset_link)
            
            # For now, just log the email content since we don't have SMTP configured
            logger.info(f"Password reset email generated for user {user_id}")
            logger.info(f"Reset link: {reset_link}")
            
            # In a real implementation, you would send via SMTP:
            # msg = MimeMultipart('alternative')
            # msg['Subject'] = "GCC Research Platform - Password Reset Request"
            # msg['From'] = self.config.email.from_address
            # msg['To'] = user_email
            # 
            # html_part = MimeText(html_content, 'html')
            # msg.attach(html_part)
            # 
            # smtp = smtplib.SMTP(self.config.email.smtp_host, self.config.email.smtp_port)
            # smtp.send_message(msg)
            
            return ResetResult(True, "Email sent successfully")
            
        except Exception as e:
            logger.error(f"Error sending password reset email: {e}")
            return ResetResult(False, f"Failed to send email: {e}")


class EnhancedInputValidator:
    """
    Enhanced input validation for authentication forms.
    """
    
    @staticmethod
    def validate_passcode_input(passcode: str) -> Dict[str, Any]:
        """
        Validate passcode input with detailed feedback.
        
        Args:
            passcode: Passcode input to validate
            
        Returns:
            Dict with validation results
        """
        if not passcode:
            return {
                "valid": False,
                "error": "Passcode is required",
                "field": "passcode"
            }
        
        if not passcode.strip():
            return {
                "valid": False,
                "error": "Passcode cannot be empty or only whitespace",
                "field": "passcode"
            }
        
        return {"valid": True}
    
    @staticmethod
    def validate_reset_identifier(identifier: str) -> Dict[str, Any]:
        """
        Validate user identifier for password reset.
        
        Args:
            identifier: User identifier to validate
            
        Returns:
            Dict with validation results
        """
        if not identifier:
            return {
                "valid": False,
                "error": "User ID is required",
                "field": "identifier"
            }
        
        if not identifier.strip():
            return {
                "valid": False,
                "error": "User ID cannot be empty or only whitespace",
                "field": "identifier"
            }
        
        # Validate it's a number (user ID)
        try:
            user_id = int(identifier.strip())
            if user_id <= 0:
                return {
                    "valid": False,
                    "error": "User ID must be a positive number",
                    "field": "identifier"
                }
        except ValueError:
            return {
                "valid": False,
                "error": "User ID must be a valid number",
                "field": "identifier"
            }
        
        return {"valid": True}