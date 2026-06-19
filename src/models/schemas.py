"""
SQLAlchemy database models for the GCC Research Intelligence Platform.

This module defines the database schema including Users, ResearchResults, 
and ProcessingSessions tables with proper relationships and constraints.
"""

from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import (
    Boolean, 
    Column, 
    Integer, 
    String, 
    Text, 
    DateTime, 
    CheckConstraint,
    Index,
    UniqueConstraint
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()


class User(Base):
    """
    User model for authentication and session management.
    
    Stores user passcodes with secure hashing and tracks login activity.
    Supports multi-user access with individual authentication.
    """
    __tablename__ = 'users'
    
    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Authentication fields
    passcode = Column(String(255), unique=True, nullable=False, index=True)
    
    # Audit fields
    created_at = Column(
        DateTime(timezone=True), 
        nullable=False, 
        default=func.now(),
        server_default=func.now()
    )
    last_login = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default='true')
    
    def __repr__(self) -> str:
        return f"<User(id={self.id}, is_active={self.is_active}, created_at={self.created_at})>"


class ResearchResult(Base):
    """
    Research results model for storing company analysis data.
    
    Stores AI-generated research results with normalized keys for deduplication.
    Implements caching strategy to prevent duplicate OpenAI API calls.
    """
    __tablename__ = 'research_results'
    
    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Cache key and company identification
    normalized_key = Column(String(255), unique=True, nullable=False, index=True)
    company_name = Column(String(255), nullable=False)
    company_domain = Column(String(255), nullable=True)
    
    # Research results fields
    gcc_presence = Column(Boolean, nullable=True)
    gcc_location = Column(String(255), nullable=True)
    suitability_score = Column(
        Integer,
        CheckConstraint('suitability_score >= 1 AND suitability_score <= 10'),
        nullable=True
    )
    
    # Analysis content fields
    business_pain_points = Column(Text, nullable=True)
    expansion_indicators = Column(Text, nullable=True)
    hiring_signals = Column(Text, nullable=True)
    research_summary = Column(Text, nullable=True)
    
    # Metadata and audit fields
    research_metadata = Column(JSONB, nullable=True)
    created_at = Column(
        DateTime(timezone=True), 
        nullable=False, 
        default=func.now(),
        server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True), 
        nullable=False, 
        default=func.now(),
        onupdate=func.now(),
        server_default=func.now()
    )
    
    # Define constraints
    __table_args__ = (
        # Ensure suitability score is within valid range
        CheckConstraint(
            'suitability_score IS NULL OR (suitability_score >= 1 AND suitability_score <= 10)',
            name='ck_research_results_suitability_score'
        ),
        # Performance indexes
        Index('idx_research_normalized_key', 'normalized_key'),
        Index('idx_research_created_at', 'created_at'),
        Index('idx_research_suitability', 'suitability_score'),
        Index('idx_research_gcc_presence', 'gcc_presence'),
        Index('idx_research_company_name', 'company_name'),
    )
    
    def __repr__(self) -> str:
        return (
            f"<ResearchResult(id={self.id}, "
            f"normalized_key='{self.normalized_key}', "
            f"company_name='{self.company_name}', "
            f"suitability_score={self.suitability_score})>"
        )


class ProcessingSession(Base):
    """
    Processing session model for tracking batch operations.
    
    Monitors batch processing progress, cache hits, and error counts.
    Enables progress tracking and session resumption capabilities.
    """
    __tablename__ = 'processing_sessions'
    
    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Session identification
    session_id = Column(String(255), nullable=False, index=True)
    
    # Progress tracking fields
    total_companies = Column(Integer, nullable=False)
    processed_companies = Column(Integer, nullable=False, default=0, server_default='0')
    cache_hits = Column(Integer, nullable=False, default=0, server_default='0')
    errors = Column(Integer, nullable=False, default=0, server_default='0')
    
    # Session status tracking
    status = Column(String(50), nullable=False, default='running', server_default='running')
    
    # Timing fields
    created_at = Column(
        DateTime(timezone=True), 
        nullable=False, 
        default=func.now(),
        server_default=func.now()
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Define constraints and indexes
    __table_args__ = (
        # Ensure non-negative counts
        CheckConstraint('total_companies >= 0', name='ck_processing_sessions_total_companies'),
        CheckConstraint('processed_companies >= 0', name='ck_processing_sessions_processed_companies'),
        CheckConstraint('cache_hits >= 0', name='ck_processing_sessions_cache_hits'),
        CheckConstraint('errors >= 0', name='ck_processing_sessions_errors'),
        CheckConstraint(
            'processed_companies <= total_companies', 
            name='ck_processing_sessions_processed_le_total'
        ),
        # Valid status values
        CheckConstraint(
            "status IN ('running', 'completed', 'stopped', 'error')",
            name='ck_processing_sessions_status'
        ),
        # Performance indexes
        Index('idx_processing_sessions_session_id', 'session_id'),
        Index('idx_processing_sessions_status', 'status'),
        Index('idx_processing_sessions_created_at', 'created_at'),
    )
    
    def __repr__(self) -> str:
        return (
            f"<ProcessingSession(id={self.id}, "
            f"session_id='{self.session_id}', "
            f"status='{self.status}', "
            f"processed={self.processed_companies}/{self.total_companies})>"
        )
    
    @property
    def completion_percentage(self) -> float:
        """Calculate completion percentage for progress tracking."""
        if self.total_companies == 0:
            return 0.0
        return (self.processed_companies / self.total_companies) * 100.0
    
    @property
    def cache_hit_rate(self) -> float:
        """Calculate cache hit rate as percentage."""
        if self.processed_companies == 0:
            return 0.0
        return (self.cache_hits / self.processed_companies) * 100.0


class ApiSetting(Base):
    """
    Key-value store for user-managed API credentials (OpenAI / Gemini keys).

    Lets any authenticated user view/update the research provider API keys
    from the Settings UI, persisted to the database (encrypted at rest via
    src.utils.crypto) rather than requiring a server restart to pick up a
    new key. `setting_key` is a small fixed vocabulary defined by the
    application (e.g. 'openai_api_key', 'gemini_api_key_1',
    'gemini_api_key_2') -- not user-supplied -- so this stays a simple
    key/value table rather than a generic settings system.

    `encrypted_value` holds a Fernet ciphertext token, never plaintext.
    `updated_by` stores the updating user's id (as a string, to avoid a
    hard FK dependency on the users table for what is otherwise a generic
    settings table) for audit purposes.
    """
    __tablename__ = 'api_settings'

    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Identification
    setting_key = Column(String(100), unique=True, nullable=False, index=True)

    # Encrypted secret value (Fernet ciphertext, never plaintext)
    encrypted_value = Column(Text, nullable=False)

    # Audit fields
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=func.now(),
        onupdate=func.now(),
        server_default=func.now()
    )
    updated_by = Column(String(50), nullable=True)

    __table_args__ = (
        UniqueConstraint('setting_key', name='uq_api_settings_setting_key'),
        Index('idx_api_settings_setting_key', 'setting_key'),
    )

    def __repr__(self) -> str:
        return (
            f"<ApiSetting(id={self.id}, "
            f"setting_key='{self.setting_key}', "
            f"updated_at={self.updated_at})>"
        )