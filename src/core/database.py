"""
Database configuration and connection management for the GCC Research Intelligence Platform.

This module provides SQLAlchemy database setup, connection pooling, and 
session management for Supabase PostgreSQL integration.
"""

import os
from contextlib import contextmanager
from typing import Generator, Optional
from urllib.parse import urlparse, quote_plus

from sqlalchemy import create_engine, text, Engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool

from ..models.schemas import Base


class DatabaseConfig:
    """Database configuration management."""
    
    def __init__(self):
        """Initialize database configuration from environment variables."""
        # Prioritize DATABASE_URL if available
        self.database_url = os.getenv('DATABASE_URL')
        
        if not self.database_url:
            # Fallback to building from SUPABASE_URL and SUPABASE_KEY
            self.supabase_url = os.getenv('SUPABASE_URL')
            self.supabase_key = os.getenv('SUPABASE_KEY')

            if not self.supabase_url:
                raise ValueError("DATABASE_URL or SUPABASE_URL environment variable is required")
            if not self.supabase_key:
                raise ValueError("DATABASE_URL or SUPABASE_KEY environment variable is required")

            # NOTE: SUPABASE_KEY is the Supabase *service-role API key* (a JWT),
            # which is a different secret from the Postgres database password
            # and can never be used as one. Building a raw Postgres connection
            # from SUPABASE_URL/SUPABASE_KEY alone is therefore not possible --
            # the actual DB password must come from SUPABASE_DB_PASSWORD.
            self.supabase_db_password = os.getenv('SUPABASE_DB_PASSWORD')
            if not self.supabase_db_password:
                raise ValueError(
                    "SUPABASE_DB_PASSWORD environment variable is required when falling back to "
                    "SUPABASE_URL/SUPABASE_KEY. SUPABASE_KEY is a service-role API key, not a "
                    "Postgres password, so it cannot be used to connect to the database. "
                    "Strongly preferred: set DATABASE_URL instead, using the connection string "
                    "from your Supabase project's Settings > Database > Connection Pooling page "
                    "(the 'Session pooler' or 'Transaction pooler' URI). The pooler host is "
                    "IPv4-compatible; the direct 'db.<ref>.supabase.co' host is IPv6-only on most "
                    "projects and will fail to resolve on platforms like Streamlit Community Cloud."
                )

            # Build database URL from components
            self.database_url = self._build_database_url()

        # Pool settings
        self.pool_size = int(os.getenv("DB_POOL_SIZE", "5"))
        self.pool_recycle = int(os.getenv("DB_POOL_RECYCLE", "3600"))
        self.echo_sql = os.getenv("DB_ECHO_SQL", "false").lower() == "true"
    
    def _build_database_url(self) -> str:
        """
        Build a PostgreSQL connection URL from Supabase configuration.

        WARNING: this constructs the *direct* connection hostname
        (db.<project_ref>.supabase.co), which Supabase resolves to an
        IPv6-only address for most projects. Hosting platforms without IPv6
        egress (e.g. Streamlit Community Cloud) cannot reach it and will fail
        with "could not translate host name ... to address: No address
        associated with hostname". Prefer setting DATABASE_URL directly with
        a Supabase connection-pooler URI (IPv4-compatible) instead of relying
        on this fallback in production.
        """
        parsed = urlparse(self.supabase_url)

        # Extract database connection details - ensure we use the correct DB hostname
        hostname = parsed.hostname
        # For Supabase, the database hostname should be db.{project_ref}.supabase.co
        if hostname and not hostname.startswith('db.'):
            # If hostname is like nkkmdzphiwmowwzzqqwx.supabase.co, convert to db.nkkmdzphiwmowwzzqqwx.supabase.co
            if '.supabase.co' in hostname:
                project_ref = hostname.replace('.supabase.co', '')
                hostname = f'db.{project_ref}.supabase.co'

        port = parsed.port or 5432

        # Use the postgres user with the real DB password (a distinct secret
        # from SUPABASE_KEY -- see SUPABASE_DB_PASSWORD validation above).
        username = 'postgres'
        password = self.supabase_db_password
        database = 'postgres'  # Default Supabase database name

        # URL encode the password to handle special characters
        encoded_password = quote_plus(password)

        return f"postgresql://{username}:{encoded_password}@{hostname}:{port}/{database}"


class DatabaseManager:
    """Database connection and session management."""
    
    def __init__(self, config: Optional[DatabaseConfig] = None):
        """
        Initialize database manager with configuration.
        
        Args:
            config: Database configuration. If None, creates from environment.
        """
        self.config = config or DatabaseConfig()
        self._engine: Optional[Engine] = None
        self._session_factory: Optional[sessionmaker] = None
    
    @property
    def engine(self) -> Engine:
        """Get or create database engine with connection pooling."""
        if self._engine is None:
            self._engine = create_engine(
                self.config.database_url,
                poolclass=QueuePool,
                pool_size=self.config.pool_size,
                pool_recycle=self.config.pool_recycle,
                pool_pre_ping=True,  # Verify connections before use
                echo=self.config.echo_sql,
            )
        return self._engine
    
    @property
    def session_factory(self) -> sessionmaker:
        """Get or create session factory."""
        if self._session_factory is None:
            self._session_factory = sessionmaker(
                bind=self.engine,
                autocommit=False,
                autoflush=False,
                # `get_session()` commits and closes a fresh session on every
                # call (see below). With the SQLAlchemy default of
                # expire_on_commit=True, that commit marks every attribute
                # on every loaded ORM object as expired, so the *next*
                # attribute access tries to refresh from the DB -- but the
                # session is already closed by then, raising
                # "Instance ... is not bound to a Session". This bit
                # virtually every call site that returns/uses an ORM object
                # after its `with db_manager.get_session():` block exits
                # (e.g. SessionManager.authenticate_user reading user.id
                # right after _get_user_by_passcode's session closed).
                # Since each get_session() call is a brand-new, short-lived
                # Session with no cross-call caching concerns, disabling
                # commit-expiry is safe here and lets callers keep using the
                # values they already loaded.
                expire_on_commit=False,
            )
        return self._session_factory
    
    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        """
        Context manager for database sessions with automatic cleanup.
        
        Yields:
            SQLAlchemy session with automatic commit/rollback handling.
        """
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    
    def create_tables(self) -> None:
        """Create all database tables if they don't exist."""
        Base.metadata.create_all(bind=self.engine)
    
    def drop_tables(self) -> None:
        """Drop all database tables. Use with caution!"""
        Base.metadata.drop_all(bind=self.engine)
    
    def test_connection(self) -> bool:
        """
        Test database connection.

        Returns:
            True if connection successful, False otherwise.
        """
        try:
            with self.get_session() as session:
                session.execute(text("SELECT 1"))
            return True
        except Exception:
            return False


class _LazyDatabaseManager:
    """
    Lazily-instantiated proxy around DatabaseManager.

    The original module-level `db_manager = DatabaseManager()` eagerly read
    SUPABASE_URL/SUPABASE_KEY at *import time*, which meant simply importing
    this module (e.g. from a test, a script, or another component) would
    crash the whole process if those environment variables weren't set yet.
    This proxy defers construction until the manager is actually used, so
    importing stays safe and configuration errors surface only when the
    database is genuinely needed.
    """

    def __init__(self) -> None:
        self._instance: Optional["DatabaseManager"] = None

    def _get(self) -> "DatabaseManager":
        if self._instance is None:
            self._instance = DatabaseManager()
        return self._instance

    def __getattr__(self, name: str):
        # Introspection-style lookups (mock.patch internally probes things
        # like '__func__' and '_is_coroutine' via hasattr/iscoroutinefunction
        # when patching this proxy -- whether via a string target like
        # '...module.db_manager' or patch.object on the proxy itself) must
        # not force real construction. Checking the *class* first (no
        # instance needed, so no SUPABASE_URL/SUPABASE_KEY required) lets
        # genuine DatabaseManager attributes (get_session, engine, ...)
        # still delegate normally, while anything DatabaseManager doesn't
        # actually define raises AttributeError immediately, exactly as a
        # real DatabaseManager instance would.
        if not hasattr(DatabaseManager, name):
            raise AttributeError(name)
        return getattr(self._get(), name)


# Global database manager instance (lazily constructed on first use).
db_manager = _LazyDatabaseManager()


def get_db_session() -> Generator[Session, None, None]:
    """
    Dependency function for getting database sessions.
    
    This function can be used with dependency injection frameworks
    or called directly for database operations.
    
    Yields:
        SQLAlchemy session with automatic cleanup.
    """
    with db_manager.get_session() as session:
        yield session


def init_database() -> None:
    """
    Initialize database by creating all tables.
    
    This function should be called during application startup
    to ensure all required tables exist.
    """
    db_manager.create_tables()


def check_database_health() -> dict:
    """
    Check database connection health and return status information.
    
    Returns:
        Dictionary with database health status and connection info.
    """
    try:
        is_connected = db_manager.test_connection()
        engine = db_manager.engine
        
        return {
            "status": "healthy" if is_connected else "unhealthy",
            "connected": is_connected,
            "pool_size": engine.pool.size() if hasattr(engine.pool, 'size') else None,
            "checked_in": engine.pool.checkedin() if hasattr(engine.pool, 'checkedin') else None,
            "checked_out": engine.pool.checkedout() if hasattr(engine.pool, 'checkedout') else None,
            "database_url_host": urlparse(db_manager.config.database_url).hostname
        }
    except Exception as e:
        return {
            "status": "error",
            "connected": False,
            "error": str(e)
        }