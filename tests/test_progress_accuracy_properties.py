"""
Property-based tests for progress tracking accuracy functionality.

This module implements Property 12: Progress Tracking Accuracy from the design document.
Tests verify that progress metrics (processed count, cache hits, errors, progress fraction)
accurately reflect the current state of processing sessions at all times.

**Validates: Requirements 6.2, 6.5**
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from datetime import datetime, timezone
from typing import List, Optional, Tuple
from unittest.mock import MagicMock, Mock, patch
import uuid

import pytest
from hypothesis import given, strategies as st, assume, settings, HealthCheck

from src.components.results_processor import (
    PROVIDER_OPENAI, PROVIDER_GEMINI, ProcessedItem, ProcessingState,
    clear_state, get_current_state, start_new_batch, _process_one
)
from src.models.entities import CompanyRecord, ResearchResult
from src.core.normalization import normalize_company


# Test data generation strategies
@st.composite
def company_names(draw):
    """Generate realistic company names for testing."""
    base_names = [
        "Microsoft", "Apple", "Google", "Amazon", "Tesla", "Meta", 
        "Netflix", "Spotify", "Uber", "Airbnb", "Stripe", "Zoom",
        "Salesforce", "Oracle", "IBM", "Intel", "AMD", "NVIDIA"
    ]
    
    base = draw(st.sampled_from(base_names))
    suffix = draw(st.sampled_from(["", " Inc", " Corp", " LLC", " Ltd"]))
    
    return base + suffix


@st.composite
def domains(draw):
    """Generate realistic domain names for testing.""" 
    base_names = ["example", "test", "demo", "company", "corp"]
    tlds = [".com", ".org", ".net", ".io"]
    
    base = draw(st.sampled_from(base_names))
    tld = draw(st.sampled_from(tlds))
    
    return base + tld


@st.composite
def company_records_list(draw, min_size=1, max_size=10):
    """Generate a list of unique CompanyRecord instances."""
    size = draw(st.integers(min_value=min_size, max_value=max_size))
    companies = []
    
    for i in range(size):
        name = draw(company_names())
        domain = draw(st.one_of(st.none(), domains()))
        
        # Ensure unique names for meaningful tracking
        name = f"{name} {i+1}"
        
        normalized_key = normalize_company(name, domain)
        
        companies.append(CompanyRecord(
            name=name,
            domain=domain,
            normalized_key=normalized_key,
            row_index=i
        ))
    
    return companies


@st.composite
def research_results(draw):
    """Generate ResearchResult instances for testing."""
    company_name = draw(company_names())
    company_domain = draw(st.one_of(st.none(), domains()))
    gcc_presence = draw(st.booleans())
    
    return ResearchResult(
        company_name=company_name,
        company_domain=company_domain,
        gcc_presence=gcc_presence,
        gcc_location="Test Location" if gcc_presence else None,
        suitability_score=draw(st.integers(min_value=1, max_value=10)),
        business_pain_points=["Test pain point"],
        expansion_indicators=["Test expansion"],
        hiring_signals=["Test hiring"],
        research_summary="Test summary for property testing",
        is_cached=False,
        created_at=datetime.now(timezone.utc)
    )


def _make_research_result() -> ResearchResult:
    """
    Build a placeholder ResearchResult with fixed, valid field values.

    Used where a test only cares about overriding company_name/
    company_domain/is_cached afterward and the remaining fields are
    irrelevant to what's being asserted. Deliberately NOT
    `research_results().example()` -- calling a Hypothesis strategy's
    `.example()` from inside a test body (rather than for one-off
    interactive exploration) raises `HypothesisException` in current
    Hypothesis versions ("Using example() inside a test function is a bad
    idea"), which made both tests using it fail unconditionally.
    """
    return ResearchResult(
        company_name="Placeholder",
        company_domain=None,
        gcc_presence=True,
        gcc_location="Test Location",
        suitability_score=7,
        business_pain_points=["Test pain point"],
        expansion_indicators=["Test expansion"],
        hiring_signals=["Test hiring"],
        research_summary="Test summary for property testing",
        is_cached=False,
        created_at=datetime.now(timezone.utc),
    )


class MockResearchEngine:
    """Mock research engine for controlled testing."""
    
    def __init__(self):
        self.results = {}
        self.call_count = 0
    
    def set_result_for_company(self, company_name: str, result: ResearchResult):
        """Set a specific result for a company."""
        self.results[company_name] = result
    
    def research_company(self, name: str, domain: str, session_id: str) -> ResearchResult:
        """Mock research with controllable results."""
        self.call_count += 1
        
        if name in self.results:
            return self.results[name]
        else:
            # Default result
            return ResearchResult(
                company_name=name,
                company_domain=domain,
                gcc_presence=True,
                gcc_location="Default Location",
                suitability_score=7,
                business_pain_points=["Default pain"],
                expansion_indicators=["Default expansion"],
                hiring_signals=["Default hiring"],
                research_summary=f"Default research for {name}",
                is_cached=False,
                created_at=datetime.now(timezone.utc)
            )


class MockCacheManager:
    """Mock cache manager for controlled cache hits/misses."""
    
    def __init__(self):
        self.cache = {}
    
    def set_cached_result(self, normalized_key: str, result: ResearchResult):
        """Manually set a cached result."""
        self.cache[normalized_key] = result
    
    def lookup_cache(self, normalized_key: str) -> Optional[ResearchResult]:
        """Mock cache lookup."""
        return self.cache.get(normalized_key)
    
    def store_cache(self, company_record: CompanyRecord, result: ResearchResult, provider: str = "openai") -> bool:
        """Mock cache storage."""
        self.cache[company_record.normalized_key] = result
        return True


class TestProgressTrackingAccuracyProperties:
    """Property 12: Progress Tracking Accuracy tests."""
    
    def setup_method(self):
        """Clear state before each test."""
        clear_state()
    
    def teardown_method(self):
        """Clear state after each test."""
        clear_state()
    
    @given(company_records_list(min_size=2, max_size=8))
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=25)
    def test_property_12_processed_count_accuracy(self, company_records):
        """
        **Validates: Requirements 6.2, 6.5**
        
        Property 12: Progress Tracking Accuracy (Processed Count)
        For any processing session, the processed count metric shall accurately 
        reflect the current number of companies that have been processed.
        """
        mock_engine = MockResearchEngine()
        mock_cache = MockCacheManager()
        
        # Set up results for all companies
        for company in company_records:
            result = _make_research_result()
            result.company_name = company.name
            result.company_domain = company.domain
            mock_engine.set_result_for_company(company.name, result)
        
        # Initialize processing
        session_id = str(uuid.uuid4())
        start_new_batch(company_records, session_id, PROVIDER_OPENAI)
        state = get_current_state()
        assert state is not None
        
        with patch('src.components.results_processor.get_research_engine', return_value=mock_engine), \
             patch('src.components.results_processor.get_cache_manager', return_value=mock_cache):
            
            # Test accuracy at each processing step
            for expected_processed in range(len(company_records) + 1):
                # Verify processed count accuracy
                assert state.current_index == expected_processed, \
                    f"Processed count should be {expected_processed}, got {state.current_index}"
                
                # Verify total is consistent
                total_companies = len(company_records)
                assert len(state.company_records) == total_companies, \
                    f"Total should remain {total_companies} throughout processing"
                
                # Verify processed items count matches current index
                assert len(state.items) == expected_processed, \
                    f"Number of processed items should match current index {expected_processed}"
                
                # Progress fraction should be accurate
                if total_companies > 0:
                    expected_fraction = expected_processed / total_companies
                    actual_fraction = (state.current_index / total_companies) if total_companies > 0 else 1.0
                    assert actual_fraction == expected_fraction, \
                        f"Progress fraction should be {expected_fraction}, got {actual_fraction}"
                
                # Process next company if not at end
                if state.current_index < len(company_records):
                    _process_one(state, user_session_id="test_session")
                else:
                    break
    
    @given(company_records_list(min_size=4, max_size=10))
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=20)
    def test_property_12_cache_hits_accuracy(self, company_records):
        """
        **Validates: Requirements 6.2, 6.5**
        
        Property 12: Progress Tracking Accuracy (Cache Hits Count)
        For any processing session with mixed cache hits/misses, the cache hits 
        metric shall accurately reflect the actual number of cache hits.
        """
        assume(len(company_records) >= 4)  # Need enough for meaningful test
        
        mock_engine = MockResearchEngine()
        mock_cache = MockCacheManager()
        
        # Set up mixed cache scenario: cache hits for even indices
        expected_cache_hits = 0
        for i, company in enumerate(company_records):
            if i % 2 == 0:  # Even indices get cache hits
                cached_result = _make_research_result()
                cached_result.company_name = company.name
                cached_result.company_domain = company.domain
                cached_result.is_cached = True
                mock_cache.set_cached_result(company.normalized_key, cached_result)
                expected_cache_hits += 1
            else:  # Odd indices will miss cache
                fresh_result = _make_research_result()
                fresh_result.company_name = company.name
                fresh_result.company_domain = company.domain
                fresh_result.is_cached = False
                mock_engine.set_result_for_company(company.name, fresh_result)
        
        # Initialize processing
        session_id = str(uuid.uuid4())
        start_new_batch(company_records, session_id, PROVIDER_OPENAI)
        state = get_current_state()
        
        with patch('src.components.results_processor.get_research_engine', return_value=mock_engine), \
             patch('src.components.results_processor.get_cache_manager', return_value=mock_cache):
            
            # Process all companies and verify cache hits accuracy at each step
            actual_cache_hits = 0
            for i in range(len(company_records)):
                # Process one company
                _process_one(state, user_session_id="test_session")
                
                # Update expected cache hits based on whether this company hit cache
                if i % 2 == 0:  # Even index should have hit cache
                    actual_cache_hits += 1
                
                # Verify cache hits metric accuracy
                assert state.cache_hits == actual_cache_hits, \
                    f"After processing company {i}, cache hits should be {actual_cache_hits}, got {state.cache_hits}"
                
                # Verify the processed item has correct cache flag
                processed_item = state.items[i]
                expected_cached = (i % 2 == 0)
                assert processed_item.is_cached == expected_cached, \
                    f"Company {i} should have is_cached={expected_cached}"
            
            # Final verification
            assert state.cache_hits == expected_cache_hits, \
                f"Final cache hits should be {expected_cache_hits}, got {state.cache_hits}"