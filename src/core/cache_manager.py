"""
Cache Manager for research result caching in the GCC Research Intelligence Platform.

This module implements intelligent caching to prevent duplicate AI research costs
by storing and retrieving research results using normalized company keys.
Provides cache lookup, storage, and integrity management across all users.
"""

import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from contextlib import contextmanager
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError, IntegrityError

from ..models.schemas import ResearchResult as ResearchResultModel
from ..models.entities import ResearchResult, CompanyRecord
from .database import db_manager, get_db_session
from .normalization import normalize_company

# Set up logger for cache operations
logger = logging.getLogger(__name__)


class CacheError(Exception):
    """Base exception for cache-related errors."""
    pass


class CacheStorageError(CacheError):
    """Exception raised when cache storage operations fail."""
    pass


class CacheLookupError(CacheError):
    """Exception raised when cache lookup operations fail."""
    pass


class CacheManager:
    """
    Research result cache manager with database operations.
    
    Implements intelligent caching to prevent duplicate AI research costs by
    storing and retrieving research results using normalized company keys.
    Maintains cache integrity across all users and provides performance optimization.
    
    **Validates: Requirements 4.1, 4.2, 4.3, 4.5**
    """
    
    def __init__(self, session_factory=None):
        """
        Initialize the cache manager.

        Args:
            session_factory: Optional SQLAlchemy session factory for testing.
                If not provided, the global db_manager's session factory is
                resolved lazily on first use (not here), so that constructing
                a CacheManager never requires database credentials to be
                configured yet.
        """
        self._session_factory = session_factory
        self._cache_stats = {
            'hits': 0,
            'misses': 0,
            'stores': 0,
            'errors': 0
        }

    @property
    def session_factory(self):
        """
        Resolve the session factory lazily.

        Falls back to the global db_manager's session factory the first time
        it's actually needed, rather than at __init__ time. This mirrors the
        lazy-construction fix applied to DatabaseManager: simply creating a
        CacheManager (including the module-level singleton below) must not
        require SUPABASE_URL/SUPABASE_KEY to already be set.
        """
        if self._session_factory is None:
            return db_manager.session_factory
        return self._session_factory

    @contextmanager
    def _get_session(self):
        """Get database session with proper error handling."""
        if self._session_factory:
            session = self._session_factory()
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()
        else:
            # Use the global session manager
            with db_manager.get_session() as session:
                yield session
    
    def lookup_cache(self, normalized_key: str) -> Optional[ResearchResult]:
        """
        Look up research results in cache by normalized key.
        
        Searches the research cache for existing results using the normalized
        company key. Returns cached results if found to prevent duplicate AI calls.
        
        Args:
            normalized_key: Standardized cache key for the company
            
        Returns:
            ResearchResult if found in cache, None otherwise
            
        Raises:
            CacheLookupError: If database lookup fails
            ValueError: If normalized_key is empty or invalid
            
        Examples:
            >>> cache = CacheManager()
            >>> result = cache.lookup_cache("microsoft_microsoft.com")
            >>> if result:
            ...     print(f"Cache hit: {result.company_name}")
            
        **Validates: Requirements 4.2, 4.3**
        """
        if not normalized_key or not normalized_key.strip():
            raise ValueError("Normalized key cannot be empty")
        
        try:
            with self._get_session() as session:
                # Query for existing research result
                db_result = session.query(ResearchResultModel).filter(
                    ResearchResultModel.normalized_key == normalized_key
                ).first()
                
                if db_result:
                    # Cache hit - convert to ResearchResult entity
                    self._cache_stats['hits'] += 1
                    
                    # Parse JSON arrays from text fields
                    business_pain_points = self._parse_text_array(db_result.business_pain_points)
                    expansion_indicators = self._parse_text_array(db_result.expansion_indicators)
                    hiring_signals = self._parse_text_array(db_result.hiring_signals)
                    
                    result = ResearchResult(
                        company_name=db_result.company_name,
                        company_domain=db_result.company_domain,
                        gcc_presence=db_result.gcc_presence or False,
                        gcc_location=db_result.gcc_location,
                        suitability_score=db_result.suitability_score or 1,
                        business_pain_points=business_pain_points,
                        expansion_indicators=expansion_indicators,
                        hiring_signals=hiring_signals,
                        research_summary=db_result.research_summary or "",
                        is_cached=True,
                        created_at=db_result.created_at
                    )
                    
                    logger.info(
                        f"Cache hit for key '{normalized_key}' - "
                        f"Company: {db_result.company_name}"
                    )
                    return result
                else:
                    # Cache miss
                    self._cache_stats['misses'] += 1
                    logger.info(f"Cache miss for key '{normalized_key}'")
                    return None
                    
        except SQLAlchemyError as e:
            self._cache_stats['errors'] += 1
            logger.error(f"Database error during cache lookup for key '{normalized_key}': {e}")
            raise CacheLookupError(f"Failed to lookup cache for key '{normalized_key}': {e}")
        except Exception as e:
            self._cache_stats['errors'] += 1
            logger.error(f"Unexpected error during cache lookup for key '{normalized_key}': {e}")
            raise CacheLookupError(f"Unexpected error during cache lookup: {e}")
    
    def store_cache(self, company_record: CompanyRecord, research_result: ResearchResult,
                    provider: Optional[str] = None) -> bool:
        """
        Store research result in cache with proper error handling.

        Saves new research results to the cache using the company's normalized key.
        Updates existing cache entries if the key already exists. Ensures cache
        integrity across all users.

        Args:
            company_record: Original company record with normalized key
            research_result: Research result to store in cache
            provider: Optional identifier of which research provider produced
                this result (e.g. 'openai', 'gemini'), recorded in
                research_metadata for traceability when multiple providers
                are in use.

        Returns:
            True if storage successful, False otherwise

        Raises:
            CacheStorageError: If database storage fails
            ValueError: If required parameters are invalid

        Examples:
            >>> cache = CacheManager()
            >>> record = CompanyRecord("Microsoft", "microsoft.com", "microsoft_microsoft.com", 0)
            >>> result = ResearchResult(...)
            >>> success = cache.store_cache(record, result, provider="openai")

        **Validates: Requirements 4.5**
        """
        if not company_record or not company_record.normalized_key:
            raise ValueError("Company record and normalized key are required")
        
        if not research_result:
            raise ValueError("Research result is required")
        
        try:
            with self._get_session() as session:
                # Check if cache entry already exists
                existing = session.query(ResearchResultModel).filter(
                    ResearchResultModel.normalized_key == company_record.normalized_key
                ).first()
                
                if existing:
                    # Update existing cache entry
                    existing.company_name = research_result.company_name
                    existing.company_domain = research_result.company_domain
                    existing.gcc_presence = research_result.gcc_presence
                    existing.gcc_location = research_result.gcc_location
                    existing.suitability_score = research_result.suitability_score
                    existing.business_pain_points = self._format_text_array(research_result.business_pain_points)
                    existing.expansion_indicators = self._format_text_array(research_result.expansion_indicators)
                    existing.hiring_signals = self._format_text_array(research_result.hiring_signals)
                    existing.research_summary = research_result.research_summary
                    existing.updated_at = datetime.now(timezone.utc)
                    
                    # Set research metadata
                    existing.research_metadata = {
                        'cache_updated': True,
                        'original_created_at': existing.created_at.isoformat(),
                        'update_count': (existing.research_metadata or {}).get('update_count', 0) + 1,
                        'provider': provider or (existing.research_metadata or {}).get('provider')
                    }
                    
                    logger.info(
                        f"Updated cache entry for key '{company_record.normalized_key}' - "
                        f"Company: {research_result.company_name}"
                    )
                else:
                    # Create new cache entry
                    cache_entry = ResearchResultModel(
                        normalized_key=company_record.normalized_key,
                        company_name=research_result.company_name,
                        company_domain=research_result.company_domain,
                        gcc_presence=research_result.gcc_presence,
                        gcc_location=research_result.gcc_location,
                        suitability_score=research_result.suitability_score,
                        business_pain_points=self._format_text_array(research_result.business_pain_points),
                        expansion_indicators=self._format_text_array(research_result.expansion_indicators),
                        hiring_signals=self._format_text_array(research_result.hiring_signals),
                        research_summary=research_result.research_summary,
                        research_metadata={
                            'cache_created': True,
                            'source_row_index': company_record.row_index,
                            'provider': provider
                        }
                    )
                    
                    session.add(cache_entry)
                    
                    logger.info(
                        f"Created new cache entry for key '{company_record.normalized_key}' - "
                        f"Company: {research_result.company_name}"
                    )
                
                # Commit the transaction
                session.commit()
                self._cache_stats['stores'] += 1
                return True
                
        except IntegrityError as e:
            self._cache_stats['errors'] += 1
            logger.error(
                f"Integrity error storing cache for key '{company_record.normalized_key}': {e}"
            )
            raise CacheStorageError(f"Cache integrity error: {e}")
        except SQLAlchemyError as e:
            self._cache_stats['errors'] += 1
            logger.error(
                f"Database error storing cache for key '{company_record.normalized_key}': {e}"
            )
            raise CacheStorageError(f"Failed to store cache: {e}")
        except Exception as e:
            self._cache_stats['errors'] += 1
            logger.error(
                f"Unexpected error storing cache for key '{company_record.normalized_key}': {e}"
            )
            raise CacheStorageError(f"Unexpected error storing cache: {e}")
    
    def lookup_or_store(self, company_record: CompanyRecord, 
                       research_function=None) -> tuple[Optional[ResearchResult], bool]:
        """
        Lookup cache first, then execute research function if cache miss.
        
        This is the primary cache interface that implements the cache-first strategy.
        Looks up results in cache first, and only executes expensive research if
        no cached result is found.
        
        Args:
            company_record: Company record with normalized key
            research_function: Function to call for research if cache miss (optional)
            
        Returns:
            Tuple of (ResearchResult or None, was_cached_boolean)
            
        Raises:
            CacheLookupError: If cache lookup fails
            CacheStorageError: If cache storage fails (when storing new results)
            
        Examples:
            >>> cache = CacheManager()
            >>> def do_research():
            ...     return ResearchResult(...)
            >>> result, was_cached = cache.lookup_or_store(record, do_research)
            >>> if was_cached:
            ...     print("Used cached result")
            
        **Validates: Requirements 4.2, 4.3, 4.5**
        """
        # First, try cache lookup
        cached_result = self.lookup_cache(company_record.normalized_key)
        
        if cached_result:
            return cached_result, True
        
        # Cache miss - execute research function if provided
        if research_function:
            try:
                research_result = research_function()
                if research_result:
                    # Store in cache for future use
                    self.store_cache(company_record, research_result)
                    # Mark as not cached since it's a fresh result
                    research_result.is_cached = False
                    return research_result, False
            except Exception as e:
                logger.error(f"Research function failed for '{company_record.normalized_key}': {e}")
                raise
        
        return None, False
    
    def get_cache_statistics(self) -> Dict[str, Any]:
        """
        Get cache performance statistics.
        
        Returns statistics about cache hits, misses, storage operations,
        and error counts for performance monitoring and optimization.
        
        Returns:
            Dictionary containing cache statistics
            
        Examples:
            >>> cache = CacheManager()
            >>> stats = cache.get_cache_statistics()
            >>> print(f"Hit rate: {stats['hit_rate']:.2%}")
            
        **Validates: Requirements 4.4**
        """
        total_lookups = self._cache_stats['hits'] + self._cache_stats['misses']
        hit_rate = (self._cache_stats['hits'] / total_lookups) if total_lookups > 0 else 0.0
        
        return {
            'cache_hits': self._cache_stats['hits'],
            'cache_misses': self._cache_stats['misses'],
            'cache_stores': self._cache_stats['stores'],
            'cache_errors': self._cache_stats['errors'],
            'total_lookups': total_lookups,
            'hit_rate': hit_rate,
            'error_rate': (self._cache_stats['errors'] / max(total_lookups, 1))
        }
    
    def clear_cache_statistics(self) -> None:
        """Reset cache statistics counters."""
        self._cache_stats = {
            'hits': 0,
            'misses': 0,
            'stores': 0,
            'errors': 0
        }
    
    def get_cached_companies(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get list of all cached companies for historical access.
        
        Retrieves information about all companies currently in the cache
        for display in historical research access interfaces.
        
        Args:
            limit: Optional limit on number of results to return
            
        Returns:
            List of dictionaries containing cached company information
            
        Raises:
            CacheLookupError: If database query fails
            
        Examples:
            >>> cache = CacheManager()
            >>> companies = cache.get_cached_companies(limit=10)
            >>> for company in companies:
            ...     print(f"{company['company_name']}: {company['suitability_score']}")
            
        **Validates: Requirements 9.1, 9.2**
        """
        try:
            with self._get_session() as session:
                query = session.query(ResearchResultModel).order_by(
                    ResearchResultModel.created_at.desc()
                )
                
                if limit:
                    query = query.limit(limit)
                
                results = query.all()
                
                companies = []
                for result in results:
                    companies.append({
                        'id': result.id,
                        'normalized_key': result.normalized_key,
                        'company_name': result.company_name,
                        'company_domain': result.company_domain,
                        'gcc_presence': result.gcc_presence,
                        'gcc_location': result.gcc_location,
                        'suitability_score': result.suitability_score,
                        'research_summary': result.research_summary[:200] + '...' if result.research_summary and len(result.research_summary) > 200 else result.research_summary,
                        'created_at': result.created_at,
                        'updated_at': result.updated_at
                    })
                
                return companies
                
        except SQLAlchemyError as e:
            logger.error(f"Database error retrieving cached companies: {e}")
            raise CacheLookupError(f"Failed to retrieve cached companies: {e}")
    
    def delete_cache_entry(self, normalized_key: str) -> bool:
        """
        Delete a specific cache entry by normalized key.
        
        Removes a cache entry from the database. Use with caution as this
        will force re-research of the company on next lookup.
        
        Args:
            normalized_key: The cache key to delete
            
        Returns:
            True if entry was deleted, False if not found
            
        Raises:
            CacheStorageError: If database deletion fails
            ValueError: If normalized_key is empty
            
        **Validates: Requirements 4.5**
        """
        if not normalized_key or not normalized_key.strip():
            raise ValueError("Normalized key cannot be empty")
        
        try:
            with self._get_session() as session:
                entry = session.query(ResearchResultModel).filter(
                    ResearchResultModel.normalized_key == normalized_key
                ).first()
                
                if entry:
                    session.delete(entry)
                    session.commit()
                    logger.info(f"Deleted cache entry for key '{normalized_key}'")
                    return True
                else:
                    logger.warning(f"Cache entry not found for key '{normalized_key}'")
                    return False
                    
        except SQLAlchemyError as e:
            logger.error(f"Database error deleting cache entry '{normalized_key}': {e}")
            raise CacheStorageError(f"Failed to delete cache entry: {e}")
    
    def _parse_text_array(self, text_value: Optional[str]) -> List[str]:
        """
        Parse text field containing array data back to list.
        
        Converts stored text arrays back to Python lists. Handles various
        formats and provides fallback for corrupted data.
        
        Args:
            text_value: Text representation of array
            
        Returns:
            List of strings
        """
        if not text_value:
            return []
        
        try:
            # Handle JSON array format
            if text_value.startswith('[') and text_value.endswith(']'):
                import json
                return json.loads(text_value)
            
            # Handle comma-separated format
            if ',' in text_value:
                return [item.strip() for item in text_value.split(',') if item.strip()]
            
            # Handle single item
            return [text_value.strip()] if text_value.strip() else []
            
        except Exception as e:
            logger.warning(f"Error parsing text array '{text_value}': {e}")
            return []
    
    def _format_text_array(self, array_value: List[str]) -> str:
        """
        Format list of strings for storage in text field.
        
        Converts Python lists to text representation for database storage.
        Uses JSON format for reliable parsing.
        
        Args:
            array_value: List of strings to format
            
        Returns:
            JSON string representation
        """
        if not array_value:
            return "[]"
        
        try:
            import json
            return json.dumps(array_value)
        except Exception as e:
            logger.warning(f"Error formatting text array {array_value}: {e}")
            return "[]"


# Global cache manager instance for application use
cache_manager = CacheManager()


def get_cache_manager() -> CacheManager:
    """
    Get the global cache manager instance.
    
    Provides access to the shared cache manager for dependency injection
    or direct usage throughout the application.
    
    Returns:
        Global CacheManager instance
        
    **Validates: Requirements 4.1**
    """
    return cache_manager


def lookup_research_cache(normalized_key: str) -> Optional[ResearchResult]:
    """
    Convenience function for cache lookup using global cache manager.
    
    Args:
        normalized_key: Standardized cache key for the company
        
    Returns:
        ResearchResult if found in cache, None otherwise
        
    **Validates: Requirements 4.2, 4.3**
    """
    return cache_manager.lookup_cache(normalized_key)


def store_research_cache(company_record: CompanyRecord, 
                        research_result: ResearchResult) -> bool:
    """
    Convenience function for cache storage using global cache manager.
    
    Args:
        company_record: Original company record with normalized key
        research_result: Research result to store in cache
        
    Returns:
        True if storage successful, False otherwise
        
    **Validates: Requirements 4.5**
    """
    return cache_manager.store_cache(company_record, research_result)