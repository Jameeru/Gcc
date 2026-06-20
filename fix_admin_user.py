#!/usr/bin/env python3
"""
Fix admin user script to ensure admin@gcc.com exists with Admin123! password.
"""

import sys
import os
from datetime import datetime, timezone
from dotenv import load_dotenv
from sqlalchemy import text

# Load environment variables from .env file
load_dotenv()

# Add the project root to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.core.database import db_manager
from src.models.schemas import User
from src.utils.security import hash_passcode, verify_passcode
from src.utils.logging import get_logger

logger = get_logger(__name__)


def fix_admin_user():
    """Ensure admin@gcc.com exists with the correct password."""
    try:
        # Initialize database
        db_manager.create_tables()
        db_manager.add_missing_columns()
        
        with db_manager.get_session() as session:
            # Check if admin@gcc.com exists
            admin_user = session.query(User).filter(
                User.email == "admin@gcc.com"
            ).first()
            
            if admin_user:
                print(f"📧 Admin user already exists: admin@gcc.com")
                
                # Check if password matches Admin123!
                if verify_passcode("Admin123!", admin_user.passcode):
                    print("✅ Password already correct!")
                    return True
                else:
                    print("🔄 Updating password to Admin123!")
                    admin_user.passcode = hash_passcode("Admin123!")
                    admin_user.role = "admin"  # Ensure admin role
                    session.commit()
                    print("✅ Password updated successfully!")
                    return True
            else:
                # Create new admin user
                print("👤 Creating new admin user...")
                hashed_password = hash_passcode("Admin123!")
                
                new_admin = User(
                    email="admin@gcc.com",
                    passcode=hashed_password,
                    full_name="Administrator",
                    role="admin",
                    is_active=True,
                    created_at=datetime.now(timezone.utc)
                )
                
                session.add(new_admin)
                session.commit()
                print("✅ Admin user created successfully!")
                return True
                
    except Exception as e:
        logger.error(f"Error fixing admin user: {e}")
        print(f"❌ Error: {e}")
        return False


def check_all_users():
    """Show all existing users."""
    try:
        with db_manager.get_session() as session:
            users = session.execute(text("""
                SELECT id, email, full_name, role, is_active, created_at 
                FROM users 
                ORDER BY id
            """)).fetchall()
            
            print("\n📋 Current Users:")
            print("-" * 60)
            for user in users:
                status = "✅ Active" if user.is_active else "❌ Inactive"
                print(f"ID: {user.id} | {user.email} | {user.full_name} | {user.role} | {status}")
            print("-" * 60)
            
    except Exception as e:
        print(f"❌ Error listing users: {e}")


def main():
    print("🔧 Admin User Fix Script")
    print("=" * 40)
    
    # Show current users
    check_all_users()
    
    # Fix admin user
    if fix_admin_user():
        print("\n✅ Admin user is now ready!")
        print("   Email: admin@gcc.com")
        print("   Password: Admin123!")
        print("   Role: admin")
    else:
        print("\n❌ Failed to fix admin user")
    
    # Show users after fix
    check_all_users()


if __name__ == "__main__":
    main()