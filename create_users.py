#!/usr/bin/env python3
"""
User creation script for GCC Research Intelligence Platform.

Creates admin and regular users with email/password authentication.
Run this script to set up initial users for the system.
"""

import sys
import os
from datetime import datetime, timezone
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Add the project root to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.core.database import db_manager
from src.models.schemas import User
from src.utils.security import hash_passcode
from src.utils.logging import get_logger

logger = get_logger(__name__)


def create_user(email: str, password: str, full_name: str, role: str = 'user') -> bool:
    """
    Create a new user with email/password authentication.
    
    Args:
        email: User email address
        password: User password (will be hashed)
        full_name: User's full name
        role: User role ('user' or 'admin')
        
    Returns:
        True if user created successfully, False otherwise.
    """
    try:
        # Initialize database to ensure tables exist
        db_manager.create_tables()
        db_manager.add_missing_columns()
        
        with db_manager.get_session() as session:
            # Check if user with this email already exists
            existing_user = session.query(User).filter(
                User.email == email.lower()
            ).first()
            
            if existing_user:
                logger.warning(f"User with email {email} already exists")
                return False
            
            # Hash the password
            hashed_password = hash_passcode(password)
            
            # Create new user
            new_user = User(
                email=email.lower(),
                passcode=hashed_password,  # Store password in passcode field
                full_name=full_name,
                role=role,
                is_active=True,
                created_at=datetime.now(timezone.utc)
            )
            
            session.add(new_user)
            session.commit()
            
            logger.info(f"User created successfully: {email} (role: {role})")
            return True
            
    except Exception as e:
        logger.error(f"Error creating user {email}: {e}")
        return False


def main():
    """Create admin and regular users."""
    print("🏢 GCC Research Intelligence Platform - User Creation")
    print("=" * 55)
    
    # Create admin user
    print("\n👤 Creating Admin User...")
    admin_created = create_user(
        email="Administrator@gcc.com",
        password="Admin1234!",
        full_name="Administrator",
        role="admin"
    )
    
    if admin_created:
        print("✅ Admin user created successfully!")
        print("   Email: Administrator@gcc.com")
        print("   Password: Admin1234!")
        print("   Role: admin")
    else:
        print("❌ Failed to create admin user (may already exist)")
    
    # Create regular user
    print("\n👤 Creating Regular User...")
    user_created = create_user(
        email="user@gcc.com", 
        password="User123!",
        full_name="Regular User",
        role="user"
    )
    
    if user_created:
        print("✅ Regular user created successfully!")
        print("   Email: user@gcc.com")
        print("   Password: User123!")
        print("   Role: user")
    else:
        print("❌ Failed to create regular user (may already exist)")
    
    print("\n" + "=" * 55)
    
    if admin_created or user_created:
        print("🎉 User creation completed!")
        print("\nYou can now login with:")
        if admin_created:
            print("   Admin:Administrator@gcc.com / Admin1234!")
        if user_created:
            print("   User:  user@gcc.com / User123!")
    else:
        print("⚠️  No new users were created. Users may already exist.")
    
    # Test database connection
    print("\n🔍 Testing database connection...")
    try:
        if db_manager.test_connection():
            print("✅ Database connection successful!")
        else:
            print("❌ Database connection failed!")
    except Exception as e:
        print(f"❌ Database connection error: {e}")


if __name__ == "__main__":
    main()