"""
Property-based tests for cache deduplication functionality.

This module implements property tests that verify cache deduplication behavior
and cache integrity according to Requirements 4.2, 4.3, and 4.5.

**Validates: Requirements 4.2, 4.3, 4.5**
"""

import pytest
from hypothesis import given, strategies as st, assume, settings, HealthCheck
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
import string
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Text, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import func
from unittest.mock import Mock, patch, MagicMock

# Add src to path for imports
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.core.cache_manager import CacheManager, CacheError, CacheLookupError, CacheStorageError
from src.models.entities import CompanyRecord, ResearchResult
from src.core.normalization import normalize_company


# Test database models compatible with SQLite
TestBase = declarative_base()


class TestResearchResult(TestBase):
    """Test version of ResearchResult model compatible with SQLite."""
    __tablename__ = 'research_results'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    normalized_key = Column(String(255), unique=True, nullable=False)
    company_name = Column(String(255), nullable=False)
    company_domain = Column(String(255), nullable=True)
    gcc_presence = Column(Boolean, nullable=True)
    gcc_location = Column(String(255), nullable=True)
    suitability_score = Column(Integer, nullable=True)
    business_pain_points = Column(Text, nullable=True)
    expansion_indicators = Column(Text, nullable=True)
    hiring_signals = Column(Text, nullable=True)
    research_summary = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now())
    research_metadata = Column(Text, nullable=True)  # JSON as text for SQLite


# Hypothesis strategies for generating test data
valid_company_chars = string.ascii_letters + string.digits + " .-&'"
valid_domain_chars = string.ascii_letters + string.digits + ".-"

@st.composite
def company_names(draw):
    """Generate realistic company names."""
    base_names = [
        "Microsoft", "Apple", "Google", "Amazon", "Tesla", "Meta", 
        "Netflix", "Spotify", "Uber", "Airbnb", "Stripe", "Zoom",
        "Salesforce", "Oracle", "IBM", "Intel", "AMD", "NVIDIA"
    ]
    
    base = draw(st.sampled_from(base_names))
    
    # Sometimes add suffixes
    suffixes = ["", " Inc", " Corporation", " Corp", " LLC", " Ltd", " Company", " Co"]
    suffix = draw(st.sampled_from(suffixes))
    
    return base + suffix


@st.composite
def domains(draw):
    """Generate realistic domain names."""
    # Use the company name as base for domain
    company = draw(company_names())
    base = company.lower().replace(" ", "").replace(".", "")
    
    # Remove common suffixes for domain
    for suffix in ["inc", "corporation", "corp", "llc", "ltd", "company", "co"]:
        base = base.replace(suffix, "")
    
    # Add TLD
    tlds = [".com", ".org", ".net", ".io", ".co", ".tech"]
    tld = draw(st.sampled_from(tlds))
    
    return base + tld


@st.composite
def company_records(draw):
    """Generate CompanyRecord instances for testing."""
    name = draw(company_names())
    domain = draw(st.one_of(st.none(), domains()))
    row_index = draw(st.integers(min_value=0, max_value=1000))
    
    # Generate normalized key
    normalized_key = normalize_company(name, domain)
    
    return CompanyRecord(
        name=name,
        domain=domain,
        normalized_key=normalized_key,
        row_index=row_index
    )


@st.composite
def research_results(draw):
    """Generate ResearchResult instances for testing."""
    company_name = draw(company_names())
    company_domain = draw(st.one_of(st.none(), domains()))
    gcc_presence = draw(st.booleans())
    gcc_location = draw(st.one_of(
        st.none(),
        st.sampled_from([
            "Bangalore, India", "Hyderabad, India", "Chennai, India", 
            "Mumbai, India", "Pune, India", "Delhi, India"
        ])
    )) if gcc_presence else None
    
    suitability_score = draw(st.integers(min_value=1, max_value=10))
    
    # Generate lists of strings for business insights
    pain_points = draw(st.lists(
        st.sampled_from([
            "High operational costs", "Talent shortage", "Scalability challenges",
            "Market competition", "Regulatory compliance", "Technology debt"
        ]),
        min_size=0, max_size=5
    ))
    
    expansion_indicators = draw(st.lists(
        st.sampled_from([
            "Recent funding", "New product lines", "Geographic expansion",
            "Partnership announcements", "Patent filings", "Executive hiring"
        ]),
        min_size=0, max_size=5
    ))
    
    hiring_signals = draw(st.lists(
        st.sampled_from([
            "Active job postings", "Expansion announcements", "Team growth",
            "New office openings", "Recruitment campaigns", "Skills training"
        ]),
        min_size=0, max_size=5
    ))
    
    research_summary = draw(st.text(
        alphabet=string.ascii_letters + string.digits + " .,!?",
        min_size=10, max_size=200
    ))
    
    return ResearchResult(
        company_name=company_name,
        company_domain=company_domain,
        gcc_presence=gcc_presence,
        gcc_location=gcc_location,
        suitability_score=suitability_score,
        business_pain_points=pain_points,
        expansion_indicators=expansion_indicators,
        hiring_signals=hiring_signals,
        research_summary=research_summary,
        is_cached=False,
        created_at=datetime.now(timezone.utc)
    )


class MockAIResearchFunction:
    """Mock AI research function that tracks calls for testing cache behavior."""
    
    def __init__(self, result: ResearchResult):
        self.result = result
        self.call_count = 0
        self.called_with = []
    
    def __call__(self, *args, **kwargs):
        """Simulate an expensive AI research call."""
        self.call_count += 1
        self.called_with.append((args, kwargs))
        # Simulate network delay
        import time
        time.sleep(0.01)  # Small delay to simulate AI API call
        return self.result
    
    def reset(self):
        """Reset call tracking."""
        self.call_count = 0
        self.called_with = []


@pytest.fixture
def engine():
    """Create in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    TestBase.metadata.create_all(engine)
    return engine


@pytest.fixture
def db_session(engine):
    """Create database session for testing."""
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def cache_manager_with_db(db_session, engine):
    """Create CacheManager with test database session."""
    # Create a session factory that returns our test session
    def test_session_factory():
        return db_session
    
    return CacheManager(session_factory=test_session_factory)


class TestCacheDeduplicationProperties:
    """Property-based tests for cache deduplication behavior."""
    
    @given(company_records(), research_results())
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=50)
    def test_property_7_cache_deduplication(self, company_record, research_result):
        """
        **Validates: Requirements 4.2, 4.3**
        
        Property 7: Cache Deduplication
        For any company record with a normalized key that exists in the research cache,
        the system shall return cached results without making new AI API calls.
        
        This property ensures that once a company is researched and cached,
        subsequent lookups prevent duplicate AI spending.
        """
        # Create fresh database for each test
        engine = create_engine("sqlite:///:memory:", echo=False)
        TestBase.metadata.create_all(engine)
        
        Session = sessionmaker(bind=engine)
        session = Session()
        
        def test_session_factory():
            return session
        
        cache_manager = CacheManager(session_factory=test_session_factory)
        
        try:
            # Mock AI research function to track calls
            mock_ai_function = MockAIResearchFunction(research_result)
            
            # First call - should miss cache and call AI
            result1, was_cached1 = cache_manager.lookup_or_store(
                company_record, mock_ai_function
            )
            
            # Verify first call behavior
            assert result1 is not None, "First lookup should return research result"
            assert was_cached1 is False, "First lookup should not be from cache"
            assert mock_ai_function.call_count == 1, "AI function should be called once on cache miss"
            
            # Store the result in cache (this should happen automatically in lookup_or_store)
            session.commit()
            
            # Second call with same normalized key - should hit cache
            mock_ai_function.reset()  # Reset call counter
            result2, was_cached2 = cache_manager.lookup_or_store(
                company_record, mock_ai_function
            )
            
            # Verify cache hit behavior
            assert result2 is not None, "Second lookup should return cached result"
            assert was_cached2 is True, "Second lookup should be from cache"
            assert mock_ai_function.call_count == 0, "AI function should NOT be called on cache hit"
            
            # Verify cached result matches original (key properties)
            assert result2.company_name == result1.company_name, "Cached company name should match"
            assert result2.suitability_score == result1.suitability_score, "Cached suitability score should match"
            assert result2.gcc_presence == result1.gcc_presence, "Cached GCC presence should match"
            assert result2.is_cached is True, "Cached result should be marked as cached"
            
            # Third call to verify consistent cache behavior
            result3, was_cached3 = cache_manager.lookup_or_store(
                company_record, mock_ai_function
            )
            
            assert result3 is not None, "Third lookup should return cached result"
            assert was_cached3 is True, "Third lookup should be from cache"
            assert mock_ai_function.call_count == 0, "AI function should still not be called"
            
        finally:
            session.close()
    
    @given(st.lists(company_records(), min_size=2, max_size=5), research_results())
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=30)
    def test_property_7_cache_deduplication_multiple_companies(self, company_records_list, research_result):
        """
        **Validates: Requirements 4.2, 4.3**
        
        Property 7 Extended: Cache Deduplication with Multiple Companies
        For any set of company records where some have duplicate normalized keys,
        the system shall call AI research only once per unique normalized key.
        """
        # Create fresh database for each test
        engine = create_engine("sqlite:///:memory:", echo=False)
        TestBase.metadata.create_all(engine)
        
        Session = sessionmaker(bind=engine)
        session = Session()
        
        def test_session_factory():
            return session
        
        cache_manager = CacheManager(session_factory=test_session_factory)
        
        try:
            # Mock AI research function to track calls
            mock_ai_function = MockAIResearchFunction(research_result)
            
            # Track unique normalized keys
            unique_keys = set()
            expected_ai_calls = 0
            
            # Process each company record
            for company_record in company_records_list:
                if company_record.normalized_key not in unique_keys:
                    unique_keys.add(company_record.normalized_key)
                    expected_ai_calls += 1
                
                result, was_cached = cache_manager.lookup_or_store(
                    company_record, mock_ai_function
                )
                
                assert result is not None, f"Result should not be None for {company_record.name}"
                session.commit()  # Ensure cache is persisted
            
            # Verify that AI was called only once per unique normalized key
            assert mock_ai_function.call_count == expected_ai_calls, (
                f"AI function should be called {expected_ai_calls} times for "
                f"{len(unique_keys)} unique keys, but was called {mock_ai_function.call_count} times"
            )
            
            # Now test that all lookups are served from cache
            mock_ai_function.reset()
            
            for company_record in company_records_list:
                result, was_cached = cache_manager.lookup_or_store(
                    company_record, mock_ai_function
                )
                
                assert result is not None, f"Cached result should not be None for {company_record.name}"
                assert was_cached is True, f"Result should be cached for {company_record.name}"
            
            # Verify no additional AI calls were made
            assert mock_ai_function.call_count == 0, "No AI calls should be made when all results are cached"
            
        finally:
            session.close()
    
    @given(company_records(), research_results())
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=50)
    def test_property_8_cache_integrity(self, company_record, research_result):
        """
        **Validates: Requirements 4.5**
        
        Property 8: Cache Integrity
        For any new research result, the system shall immediately store it in the cache
        with the correct normalized key, making it available for future lookups.
        
        This property ensures that successful research results are always cached
        and can be retrieved by their normalized key.
        """
        # Create fresh database for each test
        engine = create_engine("sqlite:///:memory:", echo=False)
        TestBase.metadata.create_all(engine)
        
        Session = sessionmaker(bind=engine)
        session = Session()
        
        def test_session_factory():
            return session
        
        cache_manager = CacheManager(session_factory=test_session_factory)
        
        try:
            # Verify cache is initially empty for this key
            initial_lookup = cache_manager.lookup_cache(company_record.normalized_key)
            assert initial_lookup is None, "Cache should initially be empty for new key"
            
            # Store research result in cache
            success = cache_manager.store_cache(company_record, research_result)
            assert success is True, "Cache storage should succeed"
            
            session.commit()  # Ensure transaction is committed
            
            # Verify result is immediately available from cache
            cached_result = cache_manager.lookup_cache(company_record.normalized_key)
            assert cached_result is not None, "Stored result should be immediately available from cache"
            
            # Verify cache integrity - all key properties match
            assert cached_result.company_name == research_result.company_name, "Cached company name should match stored"
            assert cached_result.company_domain == research_result.company_domain, "Cached domain should match stored"
            assert cached_result.gcc_presence == research_result.gcc_presence, "Cached GCC presence should match stored"
            assert cached_result.gcc_location == research_result.gcc_location, "Cached GCC location should match stored"
            assert cached_result.suitability_score == research_result.suitability_score, "Cached suitability score should match stored"
            assert cached_result.business_pain_points == research_result.business_pain_points, "Cached pain points should match stored"
            assert cached_result.expansion_indicators == research_result.expansion_indicators, "Cached expansion indicators should match stored"
            assert cached_result.hiring_signals == research_result.hiring_signals, "Cached hiring signals should match stored"
            assert cached_result.research_summary == research_result.research_summary, "Cached research summary should match stored"
            assert cached_result.is_cached is True, "Retrieved result should be marked as cached"
            
            # Verify the cached result can be retrieved multiple times consistently
            for _ in range(3):
                subsequent_lookup = cache_manager.lookup_cache(company_record.normalized_key)
                assert subsequent_lookup is not None, "Cached result should remain available"
                assert subsequent_lookup.company_name == research_result.company_name, "Subsequent lookups should return same data"
                assert subsequent_lookup.suitability_score == research_result.suitability_score, "Subsequent lookups should maintain integrity"
            
        finally:
            session.close()
    
    @given(company_records(), research_results(), research_results())
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=30)
    def test_property_8_cache_integrity_updates(self, company_record, initial_result, updated_result):
        """
        **Validates: Requirements 4.5**
        
        Property 8 Extended: Cache Integrity with Updates
        For any company record that is updated with new research results,
        the cache shall maintain integrity and provide the most recent data.
        """
        # Ensure different results to make test meaningful
        assume(initial_result.suitability_score != updated_result.suitability_score or
               initial_result.gcc_presence != updated_result.gcc_presence or
               initial_result.research_summary != updated_result.research_summary)
        
        # Create fresh database for each test
        engine = create_engine("sqlite:///:memory:", echo=False)
        TestBase.metadata.create_all(engine)
        
        Session = sessionmaker(bind=engine)
        session = Session()
        
        def test_session_factory():
            return session
        
        cache_manager = CacheManager(session_factory=test_session_factory)
        
        try:
            # Store initial result
            success1 = cache_manager.store_cache(company_record, initial_result)
            assert success1 is True, "Initial cache storage should succeed"
            session.commit()
            
            # Verify initial result is cached
            cached_initial = cache_manager.lookup_cache(company_record.normalized_key)
            assert cached_initial is not None, "Initial result should be cached"
            assert cached_initial.suitability_score == initial_result.suitability_score, "Initial cached score should match"
            
            # Update with new result (same normalized key)
            success2 = cache_manager.store_cache(company_record, updated_result)
            assert success2 is True, "Cache update should succeed"
            session.commit()
            
            # Verify updated result is now in cache
            cached_updated = cache_manager.lookup_cache(company_record.normalized_key)
            assert cached_updated is not None, "Updated result should be cached"
            
            # Verify the cache now contains the updated data, not the initial data
            if initial_result.suitability_score != updated_result.suitability_score:
                assert cached_updated.suitability_score == updated_result.suitability_score, (
                    f"Cached score should be updated value {updated_result.suitability_score}, "
                    f"not initial value {initial_result.suitability_score}"
                )
            
            if initial_result.gcc_presence != updated_result.gcc_presence:
                assert cached_updated.gcc_presence == updated_result.gcc_presence, (
                    "Cached GCC presence should be updated value"
                )
            
            if initial_result.research_summary != updated_result.research_summary:
                assert cached_updated.research_summary == updated_result.research_summary, (
                    "Cached research summary should be updated value"
                )
            
            # Verify cache integrity is maintained after update
            assert cached_updated.company_name == updated_result.company_name, "Company name should match updated result"
            assert cached_updated.is_cached is True, "Updated result should still be marked as cached"
            
        finally:
            session.close()
    
    @given(st.lists(st.tuples(company_records(), research_results()), min_size=3, max_size=8))
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=20)
    def test_property_cache_concurrent_integrity(self, company_result_pairs):
        """
        **Validates: Requirements 4.2, 4.3, 4.5**
        
        Property: Cache Concurrent Integrity
        For any sequence of cache operations (store, lookup, store, lookup),
        the cache shall maintain consistency and return correct results.
        """
        # Create fresh database for each test
        engine = create_engine("sqlite:///:memory:", echo=False)
        TestBase.metadata.create_all(engine)
        
        Session = sessionmaker(bind=engine)
        session = Session()
        
        def test_session_factory():
            return session
        
        cache_manager = CacheManager(session_factory=test_session_factory)
        
        try:
            stored_results = {}  # Track what we stored
            
            # Store all results first
            for company_record, research_result in company_result_pairs:
                success = cache_manager.store_cache(company_record, research_result)
                assert success is True, f"Storage should succeed for {company_record.name}"
                stored_results[company_record.normalized_key] = research_result
                session.commit()
            
            # Verify all results can be retrieved correctly
            for company_record, original_research_result in company_result_pairs:
                cached_result = cache_manager.lookup_cache(company_record.normalized_key)
                assert cached_result is not None, f"Result should be cached for {company_record.name}"
                
                # The cached result should match what we stored (which might be the most recent
                # for that normalized_key if there were duplicates)
                expected_result = stored_results[company_record.normalized_key]
                assert cached_result.company_name == expected_result.company_name, "Cached company name should match expected"
                assert cached_result.suitability_score == expected_result.suitability_score, "Cached suitability score should match expected"
                assert cached_result.is_cached is True, "Result should be marked as cached"
            
            # Test that cache statistics are consistent
            stats = cache_manager.get_cache_statistics()
            assert stats['cache_stores'] == len(company_result_pairs), "Store count should match operations performed"
            assert stats['cache_hits'] >= 0, "Hit count should be non-negative"
            assert stats['cache_misses'] >= 0, "Miss count should be non-negative"
            
        finally:
            session.close()


class TestCacheDeduplicationEdgeCases:
    """Edge case tests for cache deduplication robustness."""
    
    def test_cache_deduplication_with_identical_companies_different_domains(self):
        """Test that companies with same name but different domains get different cache keys."""
        engine = create_engine("sqlite:///:memory:", echo=False)
        TestBase.metadata.create_all(engine)
        
        Session = sessionmaker(bind=engine)
        session = Session()
        
        def test_session_factory():
            return session
        
        cache_manager = CacheManager(session_factory=test_session_factory)
        
        try:
            # Create two companies with same name but different domains
            company1 = CompanyRecord(
                name="Microsoft Corporation",
                domain="microsoft.com", 
                normalized_key=normalize_company("Microsoft Corporation", "microsoft.com"),
                row_index=0
            )
            
            company2 = CompanyRecord(
                name="Microsoft Corporation",
                domain="microsoft.org",
                normalized_key=normalize_company("Microsoft Corporation", "microsoft.org"), 
                row_index=1
            )
            
            # Verify they have different normalized keys
            assert company1.normalized_key != company2.normalized_key, (
                "Companies with different domains should have different normalized keys"
            )
            
            # Create different research results
            result1 = ResearchResult(
                company_name="Microsoft Corporation",
                company_domain="microsoft.com",
                gcc_presence=True,
                gcc_location="Hyderabad, India",
                suitability_score=9,
                business_pain_points=["High costs"],
                expansion_indicators=["Growth"],
                hiring_signals=["Job postings"],
                research_summary="Strong GCC presence",
                is_cached=False,
                created_at=datetime.now(timezone.utc)
            )
            
            result2 = ResearchResult(
                company_name="Microsoft Corporation", 
                company_domain="microsoft.org",
                gcc_presence=False,
                gcc_location=None,
                suitability_score=5,
                business_pain_points=["Different org"],
                expansion_indicators=["No indicators"],
                hiring_signals=["No signals"],
                research_summary="Different organization",
                is_cached=False,
                created_at=datetime.now(timezone.utc)
            )
            
            # Store both results
            cache_manager.store_cache(company1, result1)
            cache_manager.store_cache(company2, result2)
            session.commit()
            
            # Verify both are cached separately
            cached1 = cache_manager.lookup_cache(company1.normalized_key)
            cached2 = cache_manager.lookup_cache(company2.normalized_key)
            
            assert cached1 is not None, "First company should be cached"
            assert cached2 is not None, "Second company should be cached"
            assert cached1.gcc_presence != cached2.gcc_presence, "Results should be different"
            assert cached1.suitability_score != cached2.suitability_score, "Scores should be different"
            
        finally:
            session.close()
    
    def test_cache_deduplication_preserves_ai_cost_savings(self):
        """Test that cache deduplication actually prevents expensive AI calls."""
        engine = create_engine("sqlite:///:memory:", echo=False)
        TestBase.metadata.create_all(engine)
        
        Session = sessionmaker(bind=engine)
        session = Session()
        
        def test_session_factory():
            return session
        
        cache_manager = CacheManager(session_factory=test_session_factory)
        
        try:
            company = CompanyRecord(
                name="Test Company",
                domain="test.com",
                normalized_key=normalize_company("Test Company", "test.com"),
                row_index=0
            )
            
            result = ResearchResult(
                company_name="Test Company",
                company_domain="test.com", 
                gcc_presence=True,
                gcc_location="Mumbai, India",
                suitability_score=7,
                business_pain_points=["Scaling challenges"],
                expansion_indicators=["Recent investment"],
                hiring_signals=["Tech hiring"],
                research_summary="Good GCC candidate",
                is_cached=False,
                created_at=datetime.now(timezone.utc)
            )
            
            # Track expensive AI calls
            ai_call_count = 0
            ai_call_cost = 0.0
            
            def expensive_ai_research():
                nonlocal ai_call_count, ai_call_cost
                ai_call_count += 1
                ai_call_cost += 0.50  # Simulate $0.50 per AI call
                return result
            
            # First research - should call AI
            result1, cached1 = cache_manager.lookup_or_store(company, expensive_ai_research)
            session.commit()
            
            assert ai_call_count == 1, "AI should be called once on first lookup"
            assert ai_call_cost == 0.50, "Cost should be $0.50 for one call"
            assert cached1 is False, "First result should not be from cache"
            
            # Subsequent researches - should use cache
            for i in range(10):
                result_n, cached_n = cache_manager.lookup_or_store(company, expensive_ai_research)
                assert cached_n is True, f"Lookup {i+2} should use cache"
            
            # Verify no additional AI calls were made
            assert ai_call_count == 1, "AI should still only be called once after multiple lookups"
            assert ai_call_cost == 0.50, "Cost should remain $0.50 (no additional calls)"
            
            # Verify cache statistics reflect the cost savings
            stats = cache_manager.get_cache_statistics()
            assert stats['cache_hits'] == 10, "Should have 10 cache hits"
            assert stats['cache_misses'] == 1, "Should have 1 cache miss"
            
        finally:
            session.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])