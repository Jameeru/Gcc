#!/usr/bin/env python3
"""
Simple script to create a user for the GCC Research Intelligence Platform.

This script can be run locally or in the cloud to create user accounts.
It uses the same environment variables as the main application.
"""

import os
import sys
from pathlib import Path

# Add src to Python path
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

def create_user():
    """Create a user with a custom passcode."""
    
    print("🏢 GCC Research Intelligence Platform - Create User")
    print("=" * 50)
    
    # Check if we have a passcode argument
    if len(sys.argv) < 2:
        print("Usage: python create_user.py <your-passcode>")
        print("Example: python create_user.py mypasscode123")
        return
    
    passcode = sys.argv[1]
    
    if len(passcode) < 6:
        print("❌ Passcode must be at least 6 characters long")
        return
    
    try:
        from src.core.database import init_database
        from src.components.authentication import create_user_with_passcode
        
        print("🔗 Connecting to database...")
        init_database()
        
        print(f"👤 Creating user with passcode: {passcode}")
        if create_user_with_passcode(passcode):
            print("✅ User created successfully!")
            print(f"   You can now log into the app with passcode: {passcode}")
        else:
            print("❌ Failed to create user (passcode might already exist)")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        print("\nMake sure your environment variables are set correctly:")
        print("- SUPABASE_URL")
        print("- SUPABASE_KEY")

if __name__ == "__main__":
    create_user()