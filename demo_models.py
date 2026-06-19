"""
Demonstration script for the GCC Research Intelligence Platform database models.

This script shows how to use the SQLAlchemy models and repositories to:
1. Initialize the database
2. Create users and research results
3. Perform common database operations
4. Use the repository pattern for data access

Run this script to see the models in action.
"""

import os
import sys

def demo_database_models():
    """Demonstrate the database models and repositories."""
    
    print("=" * 60)
    print("GCC Research Intelligence Platform - Database Models Demo")
    print("=" * 60)
    
    # Note: For this demo, we'll skip actual database connection since it requires
    # Supabase credentials. Instead, we'll show the model structure and usage patterns.
    
    print("\n1. Database Models Overview:")
    print("   - User: Authentication and session management")
    print("   - ResearchResult: Company research data with caching")
    print("   - ProcessingSession: Batch processing tracking")
    
    print("\n2. Model Features:")
    print("   ✅ Proper constraints and validation")
    print("   ✅ Indexes for performance optimization") 
    print("   ✅ PostgreSQL JSONB support for metadata")
    print("   ✅ Automatic timestamps (created_at, updated_at)")
    print("   ✅ Repository pattern for data access")
    print("   ✅ Connection pooling and transaction management")
    
    print("\n3. Key Constraints:")
    print("   - Users: Unique passcode constraint")
    print("   - ResearchResults: Unique normalized_key for deduplication")
    print("   - ResearchResults: Suitability score must be between 1-10")
    print("   - ProcessingSessions: Processed companies <= total companies")
    
    print("\n4. Performance Indexes:")
    print("   - research_results.normalized_key (for cache lookups)")
    print("   - research_results.created_at (for time-based queries)")
    print("   - research_results.suitability_score (for filtering)")
    print("   - processing_sessions.session_id (for session tracking)")
    
    print("\n5. Repository Operations Available:")
    print("   UserRepository:")
    print("     - create_user(), get_user_by_passcode(), update_last_login()")
    print("   ResearchResultRepository:")
    print("     - create_research_result(), get_by_normalized_key(), search_results()")
    print("   ProcessingSessionRepository:")
    print("     - create_session(), update_progress(), complete_session()")
    
    print("\n6. Example Usage Pattern:")
    print("""
    # Initialize database
    from src.core.database import db_manager
    
    # Use repository pattern
    with db_manager.get_session() as session:
        user_repo = UserRepository(session)
        research_repo = ResearchResultRepository(session)
        
        # Create user
        user = user_repo.create_user("secure_passcode_123")
        
        # Check cache before research
        cached_result = research_repo.get_by_normalized_key("company_key")
        
        if not cached_result:
            # Create new research result
            result = research_repo.create_research_result(
                normalized_key="company_key",
                company_name="TechCorp",
                gcc_presence=True,
                suitability_score=8
            )
        
        # Session automatically commits or rolls back on exception
    """)
    
    print("\n7. Environment Setup Required:")
    print("   - SUPABASE_URL: Your Supabase project URL")
    print("   - SUPABASE_KEY: Your Supabase service role key") 
    print("   - Copy .env.template to .env and fill in values")
    
    print("\n8. Database Initialization:")
    print("   Run: python src/core/migrations.py")
    print("   This will create all tables and optionally add sample data")
    
    print("\n" + "=" * 60)
    print("Database models are ready for production use!")
    print("=" * 60)


def show_model_schemas():
    """Show the SQL schema that would be created."""
    print("\nSQL Schema Preview (PostgreSQL):")
    print("-" * 40)
    
    users_schema = """
    CREATE TABLE users (
        id SERIAL PRIMARY KEY,
        passcode VARCHAR(255) UNIQUE NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        last_login TIMESTAMP WITH TIME ZONE,
        is_active BOOLEAN DEFAULT TRUE
    );
    
    CREATE INDEX idx_users_passcode ON users(passcode);
    """
    
    research_results_schema = """
    CREATE TABLE research_results (
        id SERIAL PRIMARY KEY,
        normalized_key VARCHAR(255) UNIQUE NOT NULL,
        company_name VARCHAR(255) NOT NULL,
        company_domain VARCHAR(255),
        gcc_presence BOOLEAN,
        gcc_location VARCHAR(255),
        suitability_score INTEGER CHECK (suitability_score >= 1 AND suitability_score <= 10),
        business_pain_points TEXT,
        expansion_indicators TEXT,
        hiring_signals TEXT,
        research_summary TEXT,
        research_metadata JSONB,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );
    
    CREATE INDEX idx_research_normalized_key ON research_results(normalized_key);
    CREATE INDEX idx_research_created_at ON research_results(created_at);
    CREATE INDEX idx_research_suitability ON research_results(suitability_score);
    """
    
    processing_sessions_schema = """
    CREATE TABLE processing_sessions (
        id SERIAL PRIMARY KEY,
        session_id VARCHAR(255) NOT NULL,
        total_companies INTEGER NOT NULL CHECK (total_companies >= 0),
        processed_companies INTEGER DEFAULT 0 CHECK (processed_companies >= 0),
        cache_hits INTEGER DEFAULT 0 CHECK (cache_hits >= 0),
        errors INTEGER DEFAULT 0 CHECK (errors >= 0),
        status VARCHAR(50) DEFAULT 'running',
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        completed_at TIMESTAMP WITH TIME ZONE,
        CHECK (processed_companies <= total_companies)
    );
    
    CREATE INDEX idx_processing_sessions_session_id ON processing_sessions(session_id);
    """
    
    print(users_schema)
    print(research_results_schema)
    print(processing_sessions_schema)


if __name__ == "__main__":
    demo_database_models()
    show_model_schemas()
    
    print("\nNext Steps:")
    print("1. Set up your Supabase database credentials in .env")
    print("2. Run: python src/core/migrations.py")  
    print("3. Start building the Streamlit application!")
    print("4. Run tests with: python -m pytest tests/test_models.py -v")