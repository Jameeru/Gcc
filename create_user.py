#!/usr/bin/env python3
"""
User Creation Utility for GCC Research Intelligence Platform

Creates regular users for the main application (not admin users).
Admin users are created through the admin panel.

Usage:
    python3 create_user.py <email> <password> <full_name>

Example:
    python3 create_user.py john@company.com MyPassword123! "John Doe"
"""

import sys
import os

def create_regular_user(email: str, password: str, full_name: str):
    """Create a regular user for the main application."""
    
    # Ensure environment is set up
    if not os.environ.get('DATABASE_URL') and not os.environ.get('SUPABASE_URL'):
        print("❌ Error: Database environment variables not set.")
        print("Make sure SUPABASE_URL and DATABASE_URL are configured in your .env file.")
        return False
    
    # Import after environment setup
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    
    try:
        from src.components.admin_panel import UserManager
        
        user_manager = UserManager()
        result = user_manager.create_user(email, password, full_name)
        
        if result.success:
            print(f"✅ User created successfully!")
            print(f"   Email: {email}")
            print(f"   Name: {full_name}")
            print(f"   User ID: {result.user_id}")
            print()
            print("🎯 The user can now login to the main application:")
            print("   1. Run: streamlit run main.py")
            print("   2. Choose 'Email & Password' authentication")
            print(f"   3. Login with: {email} / {password}")
            return True
        else:
            print(f"❌ Failed to create user: {result.message}")
            return False
            
    except Exception as e:
        print(f"❌ Error creating user: {e}")
        return False


def main():
    """Main entry point."""
    if len(sys.argv) != 4:
        print("Usage: python3 create_user.py <email> <password> <full_name>")
        print()
        print("Example:")
        print('  python3 create_user.py john@company.com MyPassword123! "John Doe"')
        print()
        print("Password Requirements:")
        print("  - At least 8 characters long")
        print("  - At least one uppercase letter (A-Z)")
        print("  - At least one lowercase letter (a-z)")
        print("  - At least one number (0-9)")
        print("  - At least one special character (!@#$%^&*())")
        sys.exit(1)
    
    email = sys.argv[1]
    password = sys.argv[2]
    full_name = sys.argv[3]
    
    print("👤 Creating Regular User for Main Application")
    print("=" * 50)
    print(f"Email: {email}")
    print(f"Name: {full_name}")
    print("=" * 50)
    
    success = create_regular_user(email, password, full_name)
    
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()