"""
Database migration utilities for the GCC Research Intelligence Platform.

This module provides functions to initialize the database schema and 
handle database migrations safely.
"""

import logging
from typing import Dict, Any
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text

from .database import db_manager
from ..models.schemas import Base, User, ResearchResult, ProcessingSession

logger = logging.getLogger(__name__)


def create_all_tables() -> bool:
    """
    Create all database tables with proper error handling.
    
    Returns:
        True if tables created successfully, False otherwise.
    """
    try:
        # Create all tables defined in the models
        Base.metadata.create_all(bind=db_manager.engine)
        logger.info("Successfully created all database tables")
        return True
    except SQLAlchemyError as e:
        logger.error(f"Failed to create database tables: {e}")
        return False


def drop_all_tables() -> bool:
    """
    Drop all database tables. Use with extreme caution!
    
    Returns:
        True if tables dropped successfully, False otherwise.
    """
    try:
        Base.metadata.drop_all(bind=db_manager.engine)
        logger.warning("Successfully dropped all database tables")
        return True
    except SQLAlchemyError as e:
        logger.error(f"Failed to drop database tables: {e}")
        return False


def check_table_exists(table_name: str) -> bool:
    """
    Check if a specific table exists in the database.
    
    Args:
        table_name: Name of the table to check.
        
    Returns:
        True if table exists, False otherwise.
    """
    try:
        with db_manager.get_session() as session:
            result = session.execute(
                text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = 'public' 
                        AND table_name = :table_name
                    );
                """),
                {"table_name": table_name}
            )
            return result.scalar()
    except SQLAlchemyError as e:
        logger.error(f"Failed to check if table {table_name} exists: {e}")
        return False


def get_database_schema_info() -> Dict[str, Any]:
    """
    Get information about the current database schema.
    
    Returns:
        Dictionary with schema information.
    """
    schema_info = {
        "tables_exist": {},
        "indexes_exist": {},
        "constraints_exist": {}
    }
    
    try:
        # Check if required tables exist
        required_tables = ['users', 'research_results', 'processing_sessions']
        for table in required_tables:
            schema_info["tables_exist"][table] = check_table_exists(table)
        
        # Check for important indexes
        with db_manager.get_session() as session:
            # Check indexes
            index_query = text("""
                SELECT indexname, tablename 
                FROM pg_indexes 
                WHERE schemaname = 'public' 
                AND tablename IN ('users', 'research_results', 'processing_sessions')
            """)
            indexes = session.execute(index_query).fetchall()
            schema_info["indexes_exist"] = {f"{row.tablename}.{row.indexname}": True for row in indexes}
            
            # Check constraints
            constraint_query = text("""
                SELECT conname, conrelid::regclass AS table_name, contype
                FROM pg_constraint 
                WHERE connamespace = 'public'::regnamespace
                AND conrelid::regclass::text IN ('users', 'research_results', 'processing_sessions')
            """)
            constraints = session.execute(constraint_query).fetchall()
            schema_info["constraints_exist"] = {
                f"{row.table_name}.{row.conname}": row.contype for row in constraints
            }
            
    except SQLAlchemyError as e:
        logger.error(f"Failed to get database schema info: {e}")
        schema_info["error"] = str(e)
    
    return schema_info


def initialize_database() -> Dict[str, Any]:
    """
    Initialize the database with all required tables and constraints.
    
    This function should be called during application startup to ensure
    the database is properly configured.
    
    Returns:
        Dictionary with initialization results and status.
    """
    result = {
        "success": False,
        "tables_created": [],
        "errors": [],
        "schema_info": {}
    }
    
    try:
        # Test database connection first
        if not db_manager.test_connection():
            result["errors"].append("Database connection test failed")
            return result
        
        # Get current schema state
        result["schema_info"] = get_database_schema_info()
        
        # Create tables if they don't exist
        if create_all_tables():
            result["tables_created"] = ['users', 'research_results', 'processing_sessions']
            result["success"] = True
            logger.info("Database initialization completed successfully")
        else:
            result["errors"].append("Failed to create database tables")
            
    except Exception as e:
        error_msg = f"Database initialization failed: {e}"
        result["errors"].append(error_msg)
        logger.error(error_msg)
    
    return result


def create_sample_data() -> bool:
    """
    Create sample data for testing and development.
    
    This function creates sample users and research results for testing purposes.
    Should only be used in development environments.
    
    Returns:
        True if sample data created successfully, False otherwise.
    """
    try:
        from ..models.repositories import UserRepository, ResearchResultRepository
        
        with db_manager.get_session() as session:
            user_repo = UserRepository(session)
            research_repo = ResearchResultRepository(session)
            
            # Create sample users (in production, passcodes should be properly hashed)
            sample_users = [
                "dev_user_123",
                "test_user_456",
                "demo_user_789"
            ]
            
            for passcode in sample_users:
                try:
                    existing_user = user_repo.get_user_by_passcode(passcode)
                    if not existing_user:
                        user_repo.create_user(passcode)
                        logger.info(f"Created sample user with passcode: {passcode}")
                except Exception as e:
                    logger.warning(f"Failed to create sample user {passcode}: {e}")
            
            # Create sample research results
            sample_research = [
                {
                    "normalized_key": "techcorp_techcorp.com",
                    "company_name": "TechCorp",
                    "company_domain": "techcorp.com",
                    "gcc_presence": True,
                    "gcc_location": "Bangalore, India",
                    "suitability_score": 8,
                    "business_pain_points": "High development costs in US market",
                    "expansion_indicators": "Recent $50M funding round, expanding engineering team",
                    "hiring_signals": "200+ open engineering positions",
                    "research_summary": "Strong candidate for GCC services with existing India presence"
                },
                {
                    "normalized_key": "innovateinc_innovate.io",
                    "company_name": "Innovate Inc",
                    "company_domain": "innovate.io",
                    "gcc_presence": False,
                    "gcc_location": None,
                    "suitability_score": 6,
                    "business_pain_points": "Scaling challenges, talent shortage",
                    "expansion_indicators": "IPO planning, international expansion",
                    "hiring_signals": "Active recruitment in multiple locations",
                    "research_summary": "Moderate GCC potential, no current India presence"
                }
            ]
            
            for research_data in sample_research:
                try:
                    existing_research = research_repo.get_by_normalized_key(research_data["normalized_key"])
                    if not existing_research:
                        research_repo.create_research_result(**research_data)
                        logger.info(f"Created sample research for: {research_data['company_name']}")
                except Exception as e:
                    logger.warning(f"Failed to create sample research for {research_data['company_name']}: {e}")
            
            session.commit()
            logger.info("Sample data creation completed successfully")
            return True
            
    except Exception as e:
        logger.error(f"Failed to create sample data: {e}")
        return False


if __name__ == "__main__":
    # Script can be run directly for database initialization
    logging.basicConfig(level=logging.INFO)
    
    print("Initializing GCC Research Intelligence Platform database...")
    result = initialize_database()
    
    if result["success"]:
        print("✅ Database initialization completed successfully!")
        print(f"Tables created: {', '.join(result['tables_created'])}")
        
        # Optionally create sample data
        create_sample = input("Create sample data for testing? (y/N): ").lower().strip()
        if create_sample == 'y':
            if create_sample_data():
                print("✅ Sample data created successfully!")
            else:
                print("❌ Failed to create sample data")
    else:
        print("❌ Database initialization failed!")
        for error in result["errors"]:
            print(f"  - {error}")
    
    # Display schema information
    print("\nDatabase Schema Information:")
    schema_info = result["schema_info"]
    for table, exists in schema_info.get("tables_exist", {}).items():
        status = "✅" if exists else "❌"
        print(f"  {status} Table: {table}")