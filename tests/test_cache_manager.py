"""
Unit tests for the CacheManager class.

Tests cache lookup, storage, error handling, and cache statistics functionality
to ensure reliable operation of the research result caching system.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, patch, MagicMock
from sqlalchemy.exc import SQLAlchemyError, IntegrityError

# Add src to path for imports
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.core.cache_manager import (
    CacheManager, 
    CacheError, 
    CacheLookupError, 
    CacheStorageError,
    cache_manager,
    get_cache_manager,
    lookup_research_cache,
    store_research_cache
)
from src.models.entities import CompanyRecord, ResearchResult
from src.models.schemas import ResearchResult as ResearchResultModel


class TestCacheManager:
    """Test suite for CacheManager class."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.cache_manager = CacheManager()
        
        # Sample test data
        self.sample_company_record = CompanyRecord(
            name="Microsoft Corporation",
            domain="microsoft.com",
            normalized_key="microsoft_microsoft.com",
            row_index=0
        )
        
        self.sample_research_result = ResearchResult(
            company_name="Microsoft Corporation",
            company_domain="microsoft.com",
            gcc_presence=True,
            gcc_location="Hyderabad, India",
            suitability_score=8,
            business_pain_points=["High operational costs", "Talent shortage"],
            expansion_indicators=["Recent funding", "New product lines"],
            hiring_signals=["Active job postings", "Expansion announcements"],
            research_summary="Microsoft has established GCC presence in India with strong growth indicators.",
            is_cached=False,
            created_at=datetime.now(timezone.utc)
        )
    
    def test_cache_manager_initialization(self):
        """Test CacheManager initialization with default values."""
        manager = CacheManager()
        
        assert manager._cache_stats['hits'] == 0
        assert manager._cache_stats['misses'] == 0
        assert manager._cache_stats['stores'] == 0
        assert manager._cache_stats['errors'] == 0
    
    def test_cache_manager_initialization_with_session_factory(self):
        """Test CacheManager initialization with custom session factory."""
        mock_session_factory = Mock()
        manager = CacheManager(session_factory=mock_session_factory)
        
        assert manager.session_factory == mock_session_factory
    
    @patch('src.core.cache_manager.db_manager')
    def test_lookup_cache_hit(self, mock_db_manager):
        """Test successful cache lookup with hit."""
        # Mock database session and query
        mock_session = Mock()
        mock_db_manager.get_session.return_value.__enter__.return_value = mock_session
        
        # Mock database result
        mock_db_result = Mock()
        mock_db_result.normalized_key = "microsoft_microsoft.com"
        mock_db_result.company_name = "Microsoft Corporation"
        mock_db_result.company_domain = "microsoft.com"
        mock_db_result.gcc_presence = True
        mock_db_result.gcc_location = "Hyderabad, India"
        mock_db_result.suitability_score = 8
        mock_db_result.business_pain_points = '["High operational costs", "Talent shortage"]'
        mock_db_result.expansion_indicators = '["Recent funding", "New product lines"]'
        mock_db_result.hiring_signals = '["Active job postings", "Expansion announcements"]'
        mock_db_result.research_summary = "Microsoft has established GCC presence in India."
        mock_db_result.created_at = datetime.now(timezone.utc)
        
        # Mock query chain
        mock_query = Mock()
        mock_query.filter.return_value.first.return_value = mock_db_result
        mock_session.query.return_value = mock_query
        
        # Test cache lookup
        result = self.cache_manager.lookup_cache("microsoft_microsoft.com")
        
        # Verify result
        assert result is not None
        assert result.company_name == "Microsoft Corporation"
        assert result.company_domain == "microsoft.com"
        assert result.gcc_presence is True
        assert result.suitability_score == 8
        assert result.is_cached is True
        assert len(result.business_pain_points) == 2
        assert "High operational costs" in result.business_pain_points
        
        # Verify statistics
        assert self.cache_manager._cache_stats['hits'] == 1
        assert self.cache_manager._cache_stats['misses'] == 0
    
    @patch('src.core.cache_manager.db_manager')
    def test_lookup_cache_miss(self, mock_db_manager):
        """Test cache lookup with miss (no result found)."""
        # Mock database session and query
        mock_session = Mock()
        mock_db_manager.get_session.return_value.__enter__.return_value = mock_session
        
        # Mock query chain returning None (cache miss)
        mock_query = Mock()
        mock_query.filter.return_value.first.return_value = None
        mock_session.query.return_value = mock_query
        
        # Test cache lookup
        result = self.cache_manager.lookup_cache("nonexistent_company.com")
        
        # Verify result
        assert result is None
        
        # Verify statistics
        assert self.cache_manager._cache_stats['hits'] == 0
        assert self.cache_manager._cache_stats['misses'] == 1
    
    def test_lookup_cache_empty_key(self):
        """Test cache lookup with empty normalized key."""
        with pytest.raises(ValueError, match="Normalized key cannot be empty"):
            self.cache_manager.lookup_cache("")
        
        with pytest.raises(ValueError, match="Normalized key cannot be empty"):
            self.cache_manager.lookup_cache("   ")
    
    @patch('src.core.cache_manager.db_manager')
    def test_lookup_cache_database_error(self, mock_db_manager):
        """Test cache lookup with database error."""
        # Mock database session to raise SQLAlchemyError
        mock_session = Mock()
        mock_session.query.side_effect = SQLAlchemyError("Connection failed")
        mock_db_manager.get_session.return_value.__enter__.return_value = mock_session
        
        # Test cache lookup
        with pytest.raises(CacheLookupError, match="Failed to lookup cache"):
            self.cache_manager.lookup_cache("test_key")
        
        # Verify error statistics
        assert self.cache_manager._cache_stats['errors'] == 1
    
    @patch('src.core.cache_manager.db_manager')
    def test_store_cache_new_entry(self, mock_db_manager):
        """Test storing new cache entry."""
        # Mock database session
        mock_session = Mock()
        mock_db_manager.get_session.return_value.__enter__.return_value = mock_session
        
        # Mock query to return None (no existing entry)
        mock_query = Mock()
        mock_query.filter.return_value.first.return_value = None
        mock_session.query.return_value = mock_query
        
        # Test cache storage
        result = self.cache_manager.store_cache(
            self.sample_company_record, 
            self.sample_research_result
        )
        
        # Verify result
        assert result is True
        
        # Verify session.add was called
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()
        
        # Verify statistics
        assert self.cache_manager._cache_stats['stores'] == 1
    
    @patch('src.core.cache_manager.db_manager')
    def test_store_cache_update_existing(self, mock_db_manager):
        """Test updating existing cache entry."""
        # Mock database session
        mock_session = Mock()
        mock_db_manager.get_session.return_value.__enter__.return_value = mock_session
        
        # Mock existing database entry
        mock_existing = Mock()
        mock_existing.normalized_key = "microsoft_microsoft.com"
        mock_existing.created_at = datetime.now(timezone.utc)
        mock_existing.research_metadata = {}
        
        # Mock query to return existing entry
        mock_query = Mock()
        mock_query.filter.return_value.first.return_value = mock_existing
        mock_session.query.return_value = mock_query
        
        # Test cache storage
        result = self.cache_manager.store_cache(
            self.sample_company_record, 
            self.sample_research_result
        )
        
        # Verify result
        assert result is True
        
        # Verify existing entry was updated
        assert mock_existing.company_name == "Microsoft Corporation"
        assert mock_existing.suitability_score == 8
        
        # Verify session.add was not called (updating existing)
        mock_session.add.assert_not_called()
        mock_session.commit.assert_called_once()
        
        # Verify statistics
        assert self.cache_manager._cache_stats['stores'] == 1
    
    def test_store_cache_invalid_parameters(self):
        """Test cache storage with invalid parameters."""
        # Test with None company record
        with pytest.raises(ValueError, match="Company record and normalized key are required"):
            self.cache_manager.store_cache(None, self.sample_research_result)
        
        # Test with None research result
        with pytest.raises(ValueError, match="Research result is required"):
            self.cache_manager.store_cache(self.sample_company_record, None)
        
        # CompanyRecord itself rejects an empty normalized_key at construction
        # time (Property: Normalization Consistency), so store_cache's own
        # "empty normalized key" guard is unreachable via a real CompanyRecord
        # and is instead exercised directly below.
        with pytest.raises(ValueError, match="Normalized key cannot be empty"):
            CompanyRecord(
                name="Test Company",
                domain="test.com",
                normalized_key="",
                row_index=0
            )

        # Exercise store_cache's own guard directly using a Mock that bypasses
        # CompanyRecord's constructor-time validation.
        mock_record = Mock(spec=CompanyRecord)
        mock_record.normalized_key = ""
        with pytest.raises(ValueError, match="Company record and normalized key are required"):
            self.cache_manager.store_cache(mock_record, self.sample_research_result)
    
    @patch('src.core.cache_manager.db_manager')
    def test_store_cache_integrity_error(self, mock_db_manager):
        """Test cache storage with integrity error."""
        # Mock database session to raise IntegrityError
        mock_session = Mock()
        mock_session.query.return_value.filter.return_value.first.return_value = None
        mock_session.commit.side_effect = IntegrityError("Duplicate key", None, None)
        mock_db_manager.get_session.return_value.__enter__.return_value = mock_session
        
        # Test cache storage
        with pytest.raises(CacheStorageError, match="Cache integrity error"):
            self.cache_manager.store_cache(
                self.sample_company_record, 
                self.sample_research_result
            )
        
        # Verify error statistics
        assert self.cache_manager._cache_stats['errors'] == 1
    
    @patch('src.core.cache_manager.CacheManager.lookup_cache')
    def test_lookup_or_store_cache_hit(self, mock_lookup):
        """Test lookup_or_store with cache hit."""
        # Mock cache hit
        mock_lookup.return_value = self.sample_research_result
        
        # Mock research function (should not be called)
        mock_research_function = Mock()
        
        # Test lookup_or_store
        result, was_cached = self.cache_manager.lookup_or_store(
            self.sample_company_record, 
            mock_research_function
        )
        
        # Verify result
        assert result == self.sample_research_result
        assert was_cached is True
        
        # Verify research function was not called
        mock_research_function.assert_not_called()
    
    @patch('src.core.cache_manager.CacheManager.store_cache')
    @patch('src.core.cache_manager.CacheManager.lookup_cache')
    def test_lookup_or_store_cache_miss_with_research(self, mock_lookup, mock_store):
        """Test lookup_or_store with cache miss and research function."""
        # Mock cache miss
        mock_lookup.return_value = None
        
        # Mock successful storage
        mock_store.return_value = True
        
        # Mock research function
        fresh_result = ResearchResult(
            company_name="Fresh Research",
            company_domain="fresh.com",
            gcc_presence=False,
            gcc_location=None,
            suitability_score=5,
            business_pain_points=[],
            expansion_indicators=[],
            hiring_signals=[],
            research_summary="Fresh research summary",
            is_cached=False,
            created_at=datetime.now(timezone.utc)
        )
        mock_research_function = Mock(return_value=fresh_result)
        
        # Test lookup_or_store
        result, was_cached = self.cache_manager.lookup_or_store(
            self.sample_company_record, 
            mock_research_function
        )
        
        # Verify result
        assert result == fresh_result
        assert was_cached is False
        assert result.is_cached is False
        
        # Verify research function was called
        mock_research_function.assert_called_once()
        
        # Verify storage was called
        mock_store.assert_called_once_with(self.sample_company_record, fresh_result)
    
    @patch('src.core.cache_manager.CacheManager.lookup_cache')
    def test_lookup_or_store_cache_miss_no_research_function(self, mock_lookup):
        """Test lookup_or_store with cache miss and no research function."""
        # Mock cache miss
        mock_lookup.return_value = None
        
        # Test lookup_or_store without research function
        result, was_cached = self.cache_manager.lookup_or_store(
            self.sample_company_record
        )
        
        # Verify result
        assert result is None
        assert was_cached is False
    
    def test_get_cache_statistics(self):
        """Test cache statistics calculation."""
        # Manually set some statistics
        self.cache_manager._cache_stats['hits'] = 80
        self.cache_manager._cache_stats['misses'] = 20
        self.cache_manager._cache_stats['stores'] = 25
        self.cache_manager._cache_stats['errors'] = 5
        
        # Get statistics
        stats = self.cache_manager.get_cache_statistics()
        
        # Verify statistics
        assert stats['cache_hits'] == 80
        assert stats['cache_misses'] == 20
        assert stats['cache_stores'] == 25
        assert stats['cache_errors'] == 5
        assert stats['total_lookups'] == 100
        assert stats['hit_rate'] == 0.8  # 80/100
        assert stats['error_rate'] == 0.05  # 5/100
    
    def test_get_cache_statistics_no_lookups(self):
        """Test cache statistics with no lookups performed."""
        stats = self.cache_manager.get_cache_statistics()
        
        assert stats['cache_hits'] == 0
        assert stats['cache_misses'] == 0
        assert stats['total_lookups'] == 0
        assert stats['hit_rate'] == 0.0
        assert stats['error_rate'] == 0.0
    
    def test_clear_cache_statistics(self):
        """Test clearing cache statistics."""
        # Set some statistics
        self.cache_manager._cache_stats['hits'] = 10
        self.cache_manager._cache_stats['misses'] = 5
        self.cache_manager._cache_stats['stores'] = 3
        self.cache_manager._cache_stats['errors'] = 1
        
        # Clear statistics
        self.cache_manager.clear_cache_statistics()
        
        # Verify statistics are reset
        assert self.cache_manager._cache_stats['hits'] == 0
        assert self.cache_manager._cache_stats['misses'] == 0
        assert self.cache_manager._cache_stats['stores'] == 0
        assert self.cache_manager._cache_stats['errors'] == 0
    
    @patch('src.core.cache_manager.db_manager')
    def test_get_cached_companies(self, mock_db_manager):
        """Test retrieving list of cached companies."""
        # Mock database session
        mock_session = Mock()
        mock_db_manager.get_session.return_value.__enter__.return_value = mock_session
        
        # Mock database results
        mock_result1 = Mock()
        mock_result1.id = 1
        mock_result1.normalized_key = "microsoft_microsoft.com"
        mock_result1.company_name = "Microsoft Corporation"
        mock_result1.company_domain = "microsoft.com"
        mock_result1.gcc_presence = True
        mock_result1.gcc_location = "Hyderabad, India"
        mock_result1.suitability_score = 8
        mock_result1.research_summary = "Short summary"
        mock_result1.created_at = datetime.now(timezone.utc)
        mock_result1.updated_at = datetime.now(timezone.utc)
        
        mock_result2 = Mock()
        mock_result2.id = 2
        mock_result2.normalized_key = "apple_apple.com"
        mock_result2.company_name = "Apple Inc."
        mock_result2.company_domain = "apple.com"
        mock_result2.gcc_presence = False
        mock_result2.gcc_location = None
        mock_result2.suitability_score = 6
        mock_result2.research_summary = "A" * 250  # Long summary to test truncation
        mock_result2.created_at = datetime.now(timezone.utc)
        mock_result2.updated_at = datetime.now(timezone.utc)
        
        # Mock query chain
        mock_query = Mock()
        mock_query.order_by.return_value.all.return_value = [mock_result1, mock_result2]
        mock_session.query.return_value = mock_query
        
        # Test get cached companies
        companies = self.cache_manager.get_cached_companies()
        
        # Verify results
        assert len(companies) == 2
        
        # Check first company
        assert companies[0]['id'] == 1
        assert companies[0]['company_name'] == "Microsoft Corporation"
        assert companies[0]['gcc_presence'] is True
        assert companies[0]['suitability_score'] == 8
        
        # Check second company (with summary truncation)
        assert companies[1]['id'] == 2
        assert companies[1]['company_name'] == "Apple Inc."
        assert companies[1]['gcc_presence'] is False
        assert len(companies[1]['research_summary']) <= 203  # 200 + "..."
        assert companies[1]['research_summary'].endswith('...')
    
    @patch('src.core.cache_manager.db_manager')
    def test_get_cached_companies_with_limit(self, mock_db_manager):
        """Test retrieving cached companies with limit."""
        # Mock database session and query
        mock_session = Mock()
        mock_db_manager.get_session.return_value.__enter__.return_value = mock_session
        
        mock_query = Mock()
        mock_limited_query = Mock()
        mock_query.order_by.return_value = mock_limited_query
        mock_limited_query.limit.return_value.all.return_value = []
        mock_session.query.return_value = mock_query
        
        # Test with limit
        companies = self.cache_manager.get_cached_companies(limit=5)
        
        # Verify limit was applied
        mock_limited_query.limit.assert_called_once_with(5)
        assert isinstance(companies, list)
    
    @patch('src.core.cache_manager.db_manager')
    def test_delete_cache_entry(self, mock_db_manager):
        """Test deleting cache entry."""
        # Mock database session
        mock_session = Mock()
        mock_db_manager.get_session.return_value.__enter__.return_value = mock_session
        
        # Mock existing entry
        mock_entry = Mock()
        mock_query = Mock()
        mock_query.filter.return_value.first.return_value = mock_entry
        mock_session.query.return_value = mock_query
        
        # Test deletion
        result = self.cache_manager.delete_cache_entry("microsoft_microsoft.com")
        
        # Verify result
        assert result is True
        
        # Verify deletion was performed
        mock_session.delete.assert_called_once_with(mock_entry)
        mock_session.commit.assert_called_once()
    
    @patch('src.core.cache_manager.db_manager')
    def test_delete_cache_entry_not_found(self, mock_db_manager):
        """Test deleting non-existent cache entry."""
        # Mock database session
        mock_session = Mock()
        mock_db_manager.get_session.return_value.__enter__.return_value = mock_session
        
        # Mock no entry found
        mock_query = Mock()
        mock_query.filter.return_value.first.return_value = None
        mock_session.query.return_value = mock_query
        
        # Test deletion
        result = self.cache_manager.delete_cache_entry("nonexistent_key")
        
        # Verify result
        assert result is False
        
        # Verify no deletion was performed
        mock_session.delete.assert_not_called()
    
    def test_delete_cache_entry_empty_key(self):
        """Test deleting cache entry with empty key."""
        with pytest.raises(ValueError, match="Normalized key cannot be empty"):
            self.cache_manager.delete_cache_entry("")
    
    def test_parse_text_array_json_format(self):
        """Test parsing JSON array format."""
        result = self.cache_manager._parse_text_array('["item1", "item2", "item3"]')
        assert result == ["item1", "item2", "item3"]
    
    def test_parse_text_array_comma_separated(self):
        """Test parsing comma-separated format."""
        result = self.cache_manager._parse_text_array("item1, item2, item3")
        assert result == ["item1", "item2", "item3"]
    
    def test_parse_text_array_single_item(self):
        """Test parsing single item."""
        result = self.cache_manager._parse_text_array("single item")
        assert result == ["single item"]
    
    def test_parse_text_array_empty(self):
        """Test parsing empty or None values."""
        assert self.cache_manager._parse_text_array(None) == []
        assert self.cache_manager._parse_text_array("") == []
        assert self.cache_manager._parse_text_array("   ") == []
    
    def test_format_text_array_normal(self):
        """Test formatting normal array."""
        result = self.cache_manager._format_text_array(["item1", "item2", "item3"])
        assert result == '["item1", "item2", "item3"]'
    
    def test_format_text_array_empty(self):
        """Test formatting empty array."""
        assert self.cache_manager._format_text_array([]) == "[]"
        assert self.cache_manager._format_text_array(None) == "[]"


class TestGlobalFunctions:
    """Test suite for global cache manager functions."""
    
    def test_get_cache_manager(self):
        """Test getting global cache manager instance."""
        manager = get_cache_manager()
        
        assert isinstance(manager, CacheManager)
        assert manager is cache_manager
    
    @patch('src.core.cache_manager.cache_manager.lookup_cache')
    def test_lookup_research_cache(self, mock_lookup):
        """Test global lookup function."""
        mock_lookup.return_value = None
        
        result = lookup_research_cache("test_key")
        
        mock_lookup.assert_called_once_with("test_key")
        assert result is None
    
    @patch('src.core.cache_manager.cache_manager.store_cache')
    def test_store_research_cache(self, mock_store):
        """Test global store function."""
        mock_store.return_value = True
        
        # Create test data
        company_record = CompanyRecord("Test", "test.com", "test_test.com", 0)
        research_result = ResearchResult(
            company_name="Test",
            company_domain="test.com",
            gcc_presence=False,
            gcc_location=None,
            suitability_score=5,
            business_pain_points=[],
            expansion_indicators=[],
            hiring_signals=[],
            research_summary="Test summary",
            is_cached=False,
            created_at=datetime.now(timezone.utc)
        )
        
        result = store_research_cache(company_record, research_result)
        
        mock_store.assert_called_once_with(company_record, research_result)
        assert result is True


if __name__ == '__main__':
    pytest.main([__file__])