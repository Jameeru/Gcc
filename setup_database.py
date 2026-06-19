"""
Database setup script for the GCC Research Intelligence Platform.

This script initializes the database, creates tables, and sets up initial users.
Run this script after configuring your environment variables.
"""

import argparse
import secrets
import sys
import os
from pathlib import Path

# Add src to Python path
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

from src.core.database import init_database, check_database_health
from src.components.authentication import create_user_with_passcode
from src.utils.config import get_config, validate_environment
from src.utils.logging import get_logger

logger = get_logger(__name__)


def setup_database():
    """Initialize database and create tables."""
    
    print("🏢 GCC Research Intelligence Platform - Database Setup")
    print("=" * 60)
    
    # Validate configuration
    print("📋 Validating configuration...")
    if not validate_environment():
        print("❌ Configuration validation failed! Please check your .env file.")
        return False
    
    config = get_config()
    config_summary = config.get_config_summary()
    
    print("✅ Configuration validated successfully!")
    print(f"   - Database: {'✅' if config_summary['database']['has_supabase_url'] else '❌'}")
    print(f"   - OpenAI: {'✅' if config_summary['openai']['has_api_key'] else '❌'}")
    
    # Test database connection
    print("\n🔗 Testing database connection...")
    db_health = check_database_health()
    
    if db_health["status"] != "healthy":
        print(f"❌ Database connection failed: {db_health.get('error', 'Unknown error')}")
        return False
    
    print("✅ Database connection successful!")
    print(f"   - Host: {db_health.get('database_url_host', 'N/A')}")
    
    # Initialize database (create tables)
    print("\n🗄️ Creating database tables...")
    try:
        init_database()
        print("✅ Database tables created successfully!")
    except Exception as e:
        print(f"❌ Failed to create database tables: {e}")
        return False
    
    return True


def create_demo_users(count: int = 3):
    """
    Create demo users with freshly generated random passcodes.

    Passcodes are generated at run time with `secrets.token_urlsafe` rather
    than hardcoded, so no guessable credential ever lives in source control.
    Each generated passcode is printed exactly once -- if you lose it, just
    re-run with --with-demo-users to create another user.
    """
    print("\n👥 Creating demo users...")

    created_passcodes = []
    for _ in range(count):
        passcode = secrets.token_urlsafe(9)  # short, URL-safe, ~12 chars
        try:
            if create_user_with_passcode(passcode):
                print(f"   ✅ Created user with passcode: {passcode}")
                created_passcodes.append(passcode)
            else:
                print(f"   ⚠️  Failed to create a demo user (passcode collision); skipping")
        except Exception as e:
            print(f"   ❌ Failed to create demo user: {e}")

    print(f"\n📊 Summary: {len(created_passcodes)} demo users created successfully!")
    if created_passcodes:
        print("⚠️  Save these passcodes now -- they are not stored anywhere else and will not be shown again.")
    return created_passcodes


def main():
    """Main setup function."""

    parser = argparse.ArgumentParser(description="Set up the GCC Research Intelligence Platform database.")
    parser.add_argument(
        "--with-demo-users",
        type=int,
        nargs="?",
        const=3,
        default=0,
        metavar="N",
        help="Also create N demo users with randomly generated passcodes (default 3 if flag given with no number). "
             "Omit this flag in production deployments.",
    )
    args = parser.parse_args()

    # Check if .env file exists
    env_file = Path(".env")
    if not env_file.exists():
        print("❌ .env file not found!")
        print("   Please copy .env.template to .env and fill in your configuration.")
        return 1

    # Setup database
    if not setup_database():
        print("\n❌ Database setup failed!")
        return 1

    # Demo users are opt-in only -- skip entirely for a production deployment.
    created_passcodes = []
    if args.with_demo_users:
        created_passcodes = create_demo_users(count=args.with_demo_users)
        if not created_passcodes:
            print("\n❌ Failed to create any demo users!")
            return 1
    else:
        print("\nℹ️  Skipped demo user creation (pass --with-demo-users to create test accounts).")

    print("\n🎉 Database setup completed successfully!")
    print("\n📱 Next Steps:")
    print("   1. Run: streamlit run main.py")
    print("   2. Open your browser to the provided URL")
    if created_passcodes:
        print("   3. Login with one of the demo passcodes printed above.")
    else:
        print("   3. Create a real user passcode via create_user_with_passcode(), then log in.")

    return 0


if __name__ == "__main__":
    sys.exit(main())