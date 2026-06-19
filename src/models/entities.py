"""
Data Transfer Objects (DTOs) and entity classes for the GCC Research Intelligence Platform.

This module contains the core data structures used throughout the application,
including validation logic and type safety.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional


@dataclass
class CompanyRecord:
    """
    Data Transfer Object representing a company record for research processing.
    
    This class encapsulates company information extracted from CSV uploads
    and provides validation for required fields.
    
    Attributes:
        name: The company name (required, cannot be empty)
        domain: Optional company domain/website
        normalized_key: Standardized cache key for deduplication
        row_index: Original row position in the uploaded CSV
    
    Raises:
        ValueError: If company name is empty or contains only whitespace
    
    **Validates: Requirements 5.3, 14.1, 14.2, 13.6**
    """
    name: str
    domain: Optional[str]
    normalized_key: str
    row_index: int
    
    def __post_init__(self) -> None:
        """
        Validates company record data after initialization.
        
        Ensures that the company name is not empty or whitespace-only.
        This validation is critical for maintaining data quality and
        preventing invalid cache keys.
        
        Raises:
            ValueError: If company name is empty, None, or contains only whitespace
        """
        if not self.name or not self.name.strip():
            raise ValueError("Company name cannot be empty")
        
        # Ensure normalized_key is not empty
        if not self.normalized_key or not self.normalized_key.strip():
            raise ValueError("Normalized key cannot be empty")
        
        # Validate row_index is non-negative
        if self.row_index < 0:
            raise ValueError("Row index must be non-negative")


@dataclass
class ResearchResult:
    """
    Data Transfer Object representing the result of AI-powered company research.
    
    This class encapsulates all research findings about a company's GCC
    potential and business characteristics, with validation for score boundaries.
    
    Attributes:
        company_name: The researched company's name
        company_domain: Optional company domain/website
        gcc_presence: Whether the company already has a GCC in India
        gcc_location: Location of existing GCC (if any)
        suitability_score: GCC establishment suitability rating (1-10)
        business_pain_points: List of identified business challenges
        expansion_indicators: List of growth and expansion signals
        hiring_signals: List of active hiring patterns
        research_summary: Comprehensive research summary text
        is_cached: Whether this result was retrieved from cache
        created_at: Timestamp of research completion
    
    Raises:
        ValueError: If suitability_score is not between 1 and 10 (inclusive)
    
    **Validates: Requirements 5.3, 14.1, 14.2, 13.6**
    """
    company_name: str
    company_domain: Optional[str]
    gcc_presence: bool
    gcc_location: Optional[str]
    suitability_score: int
    business_pain_points: List[str]
    expansion_indicators: List[str]
    hiring_signals: List[str]
    research_summary: str
    is_cached: bool
    created_at: datetime
    
    def __post_init__(self) -> None:
        """
        Validates research result data after initialization.
        
        Ensures that the suitability score is within the valid range (1-10)
        as specified in the requirements. This validation is critical for
        maintaining data integrity and API contract compliance.
        
        Raises:
            ValueError: If suitability_score is not between 1 and 10 (inclusive)
        """
        if not 1 <= self.suitability_score <= 10:
            raise ValueError("Suitability score must be between 1 and 10")
        
        # Ensure company_name is not empty
        if not self.company_name or not self.company_name.strip():
            raise ValueError("Company name cannot be empty")
        
        # Ensure research_summary is not empty
        if not self.research_summary or not self.research_summary.strip():
            raise ValueError("Research summary cannot be empty")
        
        # Ensure lists are not None (can be empty)
        if self.business_pain_points is None:
            self.business_pain_points = []
        if self.expansion_indicators is None:
            self.expansion_indicators = []
        if self.hiring_signals is None:
            self.hiring_signals = []


@dataclass
class ProcessingSession:
    """
    Data Transfer Object representing a batch processing session.
    
    This class tracks the progress and metrics of a company research
    batch operation, providing real-time progress monitoring capabilities.
    
    Attributes:
        session_id: Unique identifier for the processing session
        total_companies: Total number of companies in the batch
        processed_companies: Number of companies processed so far
        cache_hits: Number of results retrieved from cache
        errors: Number of processing errors encountered
        status: Current processing status ('running', 'stopped', 'completed', 'error')
        created_at: Session creation timestamp
        completed_at: Session completion timestamp (if finished)
    
    Raises:
        ValueError: If counts are negative or processed exceeds total
    
    **Validates: Requirements 6.2, 6.5**
    """
    session_id: str
    total_companies: int
    processed_companies: int = 0
    cache_hits: int = 0
    errors: int = 0
    status: str = 'running'
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    def __post_init__(self) -> None:
        """
        Validates processing session data after initialization.
        
        Ensures that all counts are non-negative and that processed
        companies doesn't exceed the total count.
        
        Raises:
            ValueError: If validation constraints are violated
        """
        if self.total_companies < 0:
            raise ValueError("Total companies must be non-negative")
        
        if self.processed_companies < 0:
            raise ValueError("Processed companies must be non-negative")
        
        if self.cache_hits < 0:
            raise ValueError("Cache hits must be non-negative")
        
        if self.errors < 0:
            raise ValueError("Errors must be non-negative")
        
        if self.processed_companies > self.total_companies:
            raise ValueError("Processed companies cannot exceed total companies")
        
        # Validate status is one of the allowed values
        valid_statuses = {'running', 'stopped', 'completed', 'error'}
        if self.status not in valid_statuses:
            raise ValueError(f"Status must be one of: {', '.join(valid_statuses)}")
        
        # Ensure session_id is not empty
        if not self.session_id or not self.session_id.strip():
            raise ValueError("Session ID cannot be empty")
        
        # Set created_at if not provided
        if self.created_at is None:
            self.created_at = datetime.utcnow()
    
    @property
    def progress_percentage(self) -> float:
        """
        Calculate the current progress as a percentage.
        
        Returns:
            Progress percentage (0.0 to 100.0)
        """
        if self.total_companies == 0:
            return 100.0
        return (self.processed_companies / self.total_companies) * 100.0
    
    @property
    def cache_hit_rate(self) -> float:
        """
        Calculate the cache hit rate as a percentage.
        
        Returns:
            Cache hit rate percentage (0.0 to 100.0)
        """
        if self.processed_companies == 0:
            return 0.0
        return (self.cache_hits / self.processed_companies) * 100.0
    
    def is_completed(self) -> bool:
        """
        Check if the processing session has completed.
        
        Returns:
            True if processing is completed, False otherwise
        """
        return self.status in {'completed', 'stopped', 'error'}


@dataclass
class UserSession:
    """
    Data Transfer Object representing an authenticated user session.
    
    This class manages user authentication state and session metadata
    for the platform's security system.
    
    Attributes:
        user_id: Unique identifier for the authenticated user
        session_token: Secure session token
        created_at: Session creation timestamp
        expires_at: Session expiration timestamp
        is_active: Whether the session is currently active
        last_activity: Timestamp of last user activity
    
    Raises:
        ValueError: If session token is empty or expiration is in the past
    
    **Validates: Requirements 1.1, 1.4, 1.5**
    """
    user_id: int
    session_token: str
    created_at: datetime
    expires_at: datetime
    is_active: bool = True
    last_activity: Optional[datetime] = None
    
    def __post_init__(self) -> None:
        """
        Validates user session data after initialization.
        
        Ensures that session tokens are not empty and expiration
        times are in the future.
        
        Raises:
            ValueError: If validation constraints are violated
        """
        if not self.session_token or not self.session_token.strip():
            raise ValueError("Session token cannot be empty")
        
        if self.user_id <= 0:
            raise ValueError("User ID must be positive")
        
        if self.expires_at <= self.created_at:
            raise ValueError("Expiration time must be after creation time")
        
        # Set last_activity if not provided
        if self.last_activity is None:
            self.last_activity = self.created_at
    
    def is_expired(self) -> bool:
        """
        Check if the session has expired.

        Compares against a "now" with the same timezone-awareness as
        `expires_at`, since this codebase's convention is tz-aware UTC
        datetimes (`datetime.now(timezone.utc)`) everywhere else, but this
        DTO may also be constructed with naive datetimes by older or
        external callers -- mixing the two in a direct comparison raises
        TypeError, so we match awareness rather than assume one or the other.

        Returns:
            True if session has expired, False otherwise
        """
        if self.expires_at.tzinfo is not None:
            now = datetime.now(timezone.utc)
        else:
            now = datetime.utcnow()
        return now > self.expires_at
    
    def is_valid(self) -> bool:
        """
        Check if the session is valid (active and not expired).
        
        Returns:
            True if session is valid, False otherwise
        """
        return self.is_active and not self.is_expired()