"""
Property-based tests for sequential processing order functionality.

This module implements property tests that verify sequential processing order 
behavior according to Requirement 6.1 and Property 11 from the design document.

**Validates: Requirements 6.1**
"""

import pytest
from hypothesis import given, strategies as st, assume, settings, HealthCheck
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Tuple
import string
from unittest.mock import Mock, patch, MagicMock, call
import uuid

# Add src to path for imports
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.components.results_processor import (
    ProcessingState, ProcessedItem, start_new_batch, get_current_state, 
    clear_state, _process_one, PROVIDER_OPENAI, PROVIDER_GEMINI
)
from src.models.entities import CompanyRecord, ResearchResult
from src.core.normalization import normalize_company


# Hypothesis strategies for generating test data
@st.composite
def company_names(draw):
    """Generate realistic company names for testing."""
    base_names = [
        "Microsoft", "Apple", "Google", "Amazon", "Tesla", "Meta", 
        "Netflix", "Spotify", "Uber", "Airbnb", "Stripe", "Zoom",
        "Salesforce", "Oracle", "IBM", "Intel", "AMD", "NVIDIA",
        "Acme Corp", "Beta Inc", "Gamma LLC", "Delta Co", "Epsilon Ltd"
    ]
    
    base = draw(st.sampled_from(base_names))
    
    # Sometimes add suffixes
    suffixes = ["", " Inc", " Corporation", " Corp", " LLC", " Ltd", " Company", " Co"]
    suffix = draw(st.sampled_from(suffixes))
    
    return base + suffix


@st.composite
def domains(draw):
    """Generate realistic domain names for testing.""" 
    base_names = ["example", "test", "demo", "company", "corp", "inc"]
    tlds = [".com", ".org", ".net", ".io", ".co"]
    
    base = draw(st.sampled_from(base_names))
    tld = draw(st.sampled_from(tlds))
    
    return base + tld


@st.composite
def company_records_list(draw, min_size=2, max_size=10):
    """Generate a list of CompanyRecord instances for testing processing order."""
    size = draw(st.integers(min_value=min_size, max_value=max_size))
    companies = []
    
    for i in range(size):
        name = draw(company_names())
        domain = draw(st.one_of(st.none(), domains()))
        
        # Ensure unique names to make order tracking meaningful
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
    gcc_location = draw(st.one_of(
        st.none(),
        st.sampled_from([
            "Bangalore, India", "Hyderabad, India", "Chennai, India", 
            "Mumbai, India", "Pune, India", "Delhi, India"
        ])
    )) if gcc_presence else None
    
    suitability_score = draw(st.integers(min_value=1, max_value=10))
    
    return ResearchResult(
        company_name=company_name,
        company_domain=company_domain,
        gcc_presence=gcc_presence,
        gcc_location=gcc_location,
        suitability_score=suitability_score,
        business_pain_points=["Test pain point"],
        expansion_indicators=["Test expansion"],
        hiring_signals=["Test hiring"],
        research_summary="Test summary for property testing",
        is_cached=False,
        created_at=datetime.now(timezone.utc)
    )


class MockResearchEngine:
    """Mock research engine that tracks processing order."""
    
    def __init__(self):
        self.call_order = []
        self.call_count = 0
        self.results = {}
    
    def set_result_for_company(self, company_name: str, result: ResearchResult):
        """Set a specific result for a company."""
        self.results[company_name] = result
    
    def research_company(self, name: str, domain: str, session_id: str) -> ResearchResult:
        """Mock research that tracks order of calls."""
        self.call_count += 1
        self.call_order.append(name)
        
        # Return stored result or create default one
        if name in self.results:
            return self.results[name]
        else:
            return ResearchResult(
                company_name=name,
                company_domain=domain,
                gcc_presence=True,
                gcc_location="Mumbai, India",
                suitability_score=7,
                business_pain_points=["Default pain"],
                expansion_indicators=["Default expansion"],
                hiring_signals=["Default hiring"],
                research_summary=f"Default research for {name}",
                is_cached=False,
                created_at=datetime.now(timezone.utc)
            )
    
    def reset(self):
        """Reset call tracking."""
        self.call_order = []
        self.call_count = 0


class MockCacheManager:
    """Mock cache manager that allows controlled cache hits/misses."""
    
    def __init__(self):
        self.cache = {}
        self.lookup_order = []
        self.store_order = []
    
    def set_cached_result(self, normalized_key: str, result: ResearchResult):
        """Manually set a cached result."""
        self.cache[normalized_key] = result
    
    def lookup_cache(self, normalized_key: str) -> Optional[ResearchResult]:
        """Mock cache lookup that tracks order."""
        self.lookup_order.append(normalized_key)
        return self.cache.get(normalized_key)
    
    def store_cache(self, company_record: CompanyRecord, result: ResearchResult, provider: str = "openai") -> bool:
        """Mock cache storage that tracks order."""
        self.store_order.append(company_record.normalized_key)
        self.cache[company_record.normalized_key] = result
        return True
    
    def reset(self):
        """Reset tracking."""
        self.lookup_order = []
        self.store_order = []


class TestSequentialProcessingOrderProperties:
    """Property-based tests for sequential processing order behavior."""
    
    def setup_method(self):
        """Clear state before each test."""
        clear_state()
    
    def teardown_method(self):
        """Clear state after each test."""
        clear_state()
    
    @given(company_records_list(min_size=3, max_size=8))
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=30)
    def test_property_11_sequential_processing_order_cache_miss(self, company_records):
        """
        **Validates: Requirements 6.1**
        
        Property 11: Sequential Processing Order (Cache Miss Scenario)
        For any list of companies to process, the results processor shall handle them 
        in the exact order provided, one at a time, when all companies miss cache.
        
        This property ensures that companies are processed sequentially in the exact
        order provided, which is critical for respecting API rate limits.
        """
        # Mock dependencies to control behavior
        mock_engine = MockResearchEngine()
        mock_cache = MockCacheManager()
        
        # Set up different research results for each company to track order
        for i, company in enumerate(company_records):
            result = ResearchResult(
                company_name=company.name,
                company_domain=company.domain,
                gcc_presence=i % 2 == 0,  # Alternate presence for variety
                gcc_location=f"Location {i}" if i % 2 == 0 else None,
                suitability_score=((i % 10) + 1),  # Score 1-10
                business_pain_points=[f"Pain point {i}"],
                expansion_indicators=[f"Expansion {i}"],
                hiring_signals=[f"Hiring {i}"],
                research_summary=f"Research summary for company {i}: {company.name}",
                is_cached=False,
                created_at=datetime.now(timezone.utc)
            )
            mock_engine.set_result_for_company(company.name, result)
        
        # Initialize processing state
        session_id = str(uuid.uuid4())
        start_new_batch(company_records, session_id, provider=PROVIDER_OPENAI)
        state = get_current_state()
        assert state is not None
        
        # Process each company one by one (simulating the sequential processor behavior)
        with patch('src.components.results_processor.get_research_engine', return_value=mock_engine), \
             patch('src.components.results_processor.get_cache_manager', return_value=mock_cache):
            
            expected_order = [company.name for company in company_records]
            
            # Process all companies sequentially
            while state.current_index < len(company_records):
                current_company = company_records[state.current_index]
                _process_one(state, user_session_id="test_session")
            
            # Verify processing order matches input order exactly
            assert len(mock_engine.call_order) == len(company_records), \
                f"Should process all {len(company_records)} companies, but processed {len(mock_engine.call_order)}"
            
            assert mock_engine.call_order == expected_order, \
                f"Processing order {mock_engine.call_order} should match input order {expected_order}"
            
            # Verify cache lookups happened in the correct order
            expected_lookup_keys = [company.normalized_key for company in company_records]
            assert mock_cache.lookup_order == expected_lookup_keys, \
                f"Cache lookup order {mock_cache.lookup_order} should match expected {expected_lookup_keys}"
            
            # Verify results are in the same order as input
            processed_names = [item.company_record.name for item in state.items]
            assert processed_names == expected_order, \
                f"Processed results order {processed_names} should match input order {expected_order}"
            
            # Verify state progression is sequential (one at a time)
            assert state.current_index == len(company_records), \
                f"Should have processed all {len(company_records)} companies"
    
    @given(company_records_list(min_size=4, max_size=6))
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=20)
    def test_property_11_sequential_processing_order_mixed_cache(self, company_records):
        """
        **Validates: Requirements 6.1**
        
        Property 11: Sequential Processing Order (Mixed Cache Scenario)
        For any list of companies where some hit cache and others miss,
        the processor shall still handle them in exact input order.
        """
        assume(len(company_records) >= 4)  # Need enough for meaningful mix
        
        mock_engine = MockResearchEngine()
        mock_cache = MockCacheManager()
        
        # Set up mixed cache scenario: cache hits for even indices, misses for odd
        for i, company in enumerate(company_records):
            if i % 2 == 0:  # Even indices get cache hits
                cached_result = ResearchResult(
                    company_name=company.name,
                    company_domain=company.domain,
                    gcc_presence=True,
                    gcc_location="Cached Location",
                    suitability_score=8,
                    business_pain_points=["Cached pain"],
                    expansion_indicators=["Cached expansion"],
                    hiring_signals=["Cached hiring"],
                    research_summary=f"Cached result for {company.name}",
                    is_cached=True,
                    created_at=datetime.now(timezone.utc)
                )
                mock_cache.set_cached_result(company.normalized_key, cached_result)
            else:  # Odd indices will miss cache and need AI research
                fresh_result = ResearchResult(
                    company_name=company.name,
                    company_domain=company.domain,
                    gcc_presence=False,
                    gcc_location=None,
                    suitability_score=5,
                    business_pain_points=["Fresh pain"],
                    expansion_indicators=["Fresh expansion"],
                    hiring_signals=["Fresh hiring"],
                    research_summary=f"Fresh research for {company.name}",
                    is_cached=False,
                    created_at=datetime.now(timezone.utc)
                )
                mock_engine.set_result_for_company(company.name, fresh_result)
        
        # Initialize processing
        session_id = str(uuid.uuid4())
        start_new_batch(company_records, session_id, provider=PROVIDER_OPENAI)
        state = get_current_state()
        
        # Process all companies
        with patch('src.components.results_processor.get_research_engine', return_value=mock_engine), \
             patch('src.components.results_processor.get_cache_manager', return_value=mock_cache):
            
            expected_order = [company.name for company in company_records]
            
            while state.current_index < len(company_records):
                _process_one(state, user_session_id="test_session")
            
            # Verify overall processing order regardless of cache hits/misses
            processed_names = [item.company_record.name for item in state.items]
            assert processed_names == expected_order, \
                f"Processing order {processed_names} should match input order {expected_order} even with mixed cache"
            
            # Verify cache lookups happened in input order
            expected_lookup_keys = [company.normalized_key for company in company_records]
            assert mock_cache.lookup_order == expected_lookup_keys, \
                f"Cache lookups should happen in input order {expected_lookup_keys}"
            
            # Verify AI calls only for cache misses, but still in order
            expected_ai_calls = [company.name for i, company in enumerate(company_records) if i % 2 == 1]
            assert mock_engine.call_order == expected_ai_calls, \
                f"AI calls {mock_engine.call_order} should only be for cache misses {expected_ai_calls}"
            
            # Verify correct cache hit flags
            for i, item in enumerate(state.items):
                expected_cached = (i % 2 == 0)
                assert item.is_cached == expected_cached, \
                    f"Item {i} ({item.company_record.name}) should have is_cached={expected_cached}"
    
    @given(company_records_list(min_size=3, max_size=6))
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=20)
    def test_property_11_sequential_processing_order_with_errors(self, company_records):
        """
        **Validates: Requirements 6.1, 10.4**
        
        Property 11: Sequential Processing Order with Error Isolation
        For any list of companies where some fail during research,
        the processor shall continue with remaining companies in exact order,
        and errors should not disrupt the sequential processing of subsequent companies.
        """
        assume(len(company_records) >= 3)
        
        mock_engine = MockResearchEngine()
        mock_cache = MockCacheManager()
        
        # Set up scenario where middle companies will fail
        for i, company in enumerate(company_records):
            if i == 1:  # Second company will fail
                # Don't set a result, and mock will raise an error
                pass
            else:
                result = ResearchResult(
                    company_name=company.name,
                    company_domain=company.domain,
                    gcc_presence=True,
                    gcc_location=f"Location {i}",
                    suitability_score=7,
                    business_pain_points=[f"Pain {i}"],
                    expansion_indicators=[f"Expansion {i}"],
                    hiring_signals=[f"Hiring {i}"],
                    research_summary=f"Success for {company.name}",
                    is_cached=False,
                    created_at=datetime.now(timezone.utc)
                )
                mock_engine.set_result_for_company(company.name, result)
        
        # Mock the research engine to fail for the second company
        original_research = mock_engine.research_company
        
        def research_with_failure(name: str, domain: str, session_id: str):
            if name == company_records[1].name:
                from src.components.research_engine import ResearchAPIError
                raise ResearchAPIError(f"API failed for {name}")
            return original_research(name, domain, session_id)
        
        mock_engine.research_company = research_with_failure
        
        # Initialize processing
        session_id = str(uuid.uuid4())
        start_new_batch(company_records, session_id, provider=PROVIDER_OPENAI)
        state = get_current_state()
        
        # Process all companies (including the failing one)
        with patch('src.components.results_processor.get_research_engine', return_value=mock_engine), \
             patch('src.components.results_processor.get_cache_manager', return_value=mock_cache):
            
            expected_order = [company.name for company in company_records]
            
            while state.current_index < len(company_records):
                _process_one(state, user_session_id="test_session")
            
            # Verify all companies were processed in order (even the failing one)
            processed_names = [item.company_record.name for item in state.items]
            assert processed_names == expected_order, \
                f"Processing should continue in order {expected_order} even with errors"
            
            # Verify the failed company has error set but processing continued
            failed_item = state.items[1]  # Second company should have failed
            assert failed_item.error is not None, "Failed company should have error recorded"
            assert failed_item.research_result is None, "Failed company should have no research result"
            assert "API failed" in failed_item.error, "Error message should indicate API failure"
            
            # Verify other companies processed successfully
            successful_items = [item for i, item in enumerate(state.items) if i != 1]
            for item in successful_items:
                assert item.error is None, f"Non-failing companies should have no error: {item.company_record.name}"
                assert item.research_result is not None, f"Non-failing companies should have results: {item.company_record.name}"
            
            # Verify error count is accurate
            assert state.errors == 1, "Should have exactly 1 error recorded"
    
    @given(company_records_list(min_size=2, max_size=5), st.sampled_from([PROVIDER_OPENAI, PROVIDER_GEMINI]))
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=20)
    def test_property_11_sequential_processing_order_provider_independence(self, company_records, provider):
        """
        **Validates: Requirements 6.1**
        
        Property 11: Sequential Processing Order with Provider Independence
        For any list of companies and any supported research provider (OpenAI or Gemini),
        the processor shall handle companies in the exact order provided regardless of provider.
        """
        mock_openai_engine = MockResearchEngine()
        mock_gemini_engine = MockResearchEngine()
        mock_cache = MockCacheManager()
        
        # Set up results for both engines
        for i, company in enumerate(company_records):
            result = ResearchResult(
                company_name=company.name,
                company_domain=company.domain,
                gcc_presence=True,
                gcc_location=f"Provider Location {i}",
                suitability_score=6,
                business_pain_points=[f"Provider pain {i}"],
                expansion_indicators=[f"Provider expansion {i}"],
                hiring_signals=[f"Provider hiring {i}"],
                research_summary=f"Research via {provider} for {company.name}",
                is_cached=False,
                created_at=datetime.now(timezone.utc)
            )
            mock_openai_engine.set_result_for_company(company.name, result)
            mock_gemini_engine.set_result_for_company(company.name, result)
        
        # Initialize processing with specified provider
        session_id = str(uuid.uuid4())
        start_new_batch(company_records, session_id, provider=provider)
        state = get_current_state()
        
        # Verify provider was set correctly
        assert state.provider == provider, f"Provider should be set to {provider}"
        
        # Process all companies
        with patch('src.components.results_processor.get_research_engine', return_value=mock_openai_engine), \
             patch('src.components.results_processor.get_gemini_engine', return_value=mock_gemini_engine), \
             patch('src.components.results_processor.get_cache_manager', return_value=mock_cache):
            
            expected_order = [company.name for company in company_records]
            
            while state.current_index < len(company_records):
                _process_one(state, user_session_id="test_session")
            
            # Verify processing order is maintained regardless of provider
            processed_names = [item.company_record.name for item in state.items]
            assert processed_names == expected_order, \
                f"Processing order should be maintained with {provider} provider"
            
            # Verify correct engine was used
            if provider == PROVIDER_OPENAI:
                assert len(mock_openai_engine.call_order) == len(company_records), \
                    "OpenAI engine should be used when provider is openai"
                assert len(mock_gemini_engine.call_order) == 0, \
                    "Gemini engine should not be used when provider is openai"
                assert mock_openai_engine.call_order == expected_order, \
                    "OpenAI calls should be in correct order"
            else:  # PROVIDER_GEMINI
                assert len(mock_gemini_engine.call_order) == len(company_records), \
                    "Gemini engine should be used when provider is gemini"
                assert len(mock_openai_engine.call_order) == 0, \
                    "OpenAI engine should not be used when provider is gemini"
                assert mock_gemini_engine.call_order == expected_order, \
                    "Gemini calls should be in correct order"
    
    @given(st.lists(st.tuples(company_records_list(min_size=2, max_size=4), st.integers(min_value=0, max_value=3)), min_size=1, max_size=3))
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=15)
    def test_property_11_sequential_processing_order_batch_consistency(self, batch_specs):
        """
        **Validates: Requirements 6.1**
        
        Property 11: Sequential Processing Order Across Multiple Batches
        For any sequence of processing batches, each batch should process
        its companies in the exact order provided, independent of other batches.
        """
        mock_engine = MockResearchEngine()
        mock_cache = MockCacheManager()
        
        all_batch_orders = []
        
        # Process each batch independently
        for batch_companies, _ in batch_specs:
            # Flatten the batch companies list (it's a list of lists from the strategy)
            if isinstance(batch_companies[0], list):
                companies = batch_companies[0]
            else:
                companies = batch_companies
                
            if len(companies) < 2:
                continue
                
            # Set up results for this batch
            for company in companies:
                result = ResearchResult(
                    company_name=company.name,
                    company_domain=company.domain,
                    gcc_presence=True,
                    gcc_location="Batch Location",
                    suitability_score=7,
                    business_pain_points=["Batch pain"],
                    expansion_indicators=["Batch expansion"],
                    hiring_signals=["Batch hiring"],
                    research_summary=f"Batch research for {company.name}",
                    is_cached=False,
                    created_at=datetime.now(timezone.utc)
                )
                mock_engine.set_result_for_company(company.name, result)
            
            # Process this batch
            session_id = str(uuid.uuid4())
            clear_state()  # Clear previous batch
            start_new_batch(companies, session_id, provider=PROVIDER_OPENAI)
            state = get_current_state()
            
            with patch('src.components.results_processor.get_research_engine', return_value=mock_engine), \
                 patch('src.components.results_processor.get_cache_manager', return_value=mock_cache):
                
                expected_order = [company.name for company in companies]
                mock_engine.reset()  # Reset for this batch
                
                while state.current_index < len(companies):
                    _process_one(state, user_session_id="test_session")
                
                # Verify this batch processed in correct order
                processed_names = [item.company_record.name for item in state.items]
                assert processed_names == expected_order, \
                    f"Batch should process in order {expected_order}"
                
                # Track this batch's order
                all_batch_orders.append(processed_names)
        
        # Verify each batch maintained its own order independently
        for i, (batch_spec, actual_order) in enumerate(zip(batch_specs, all_batch_orders)):
            batch_companies = batch_spec[0]
            if isinstance(batch_companies[0], list):
                companies = batch_companies[0]
            else:
                companies = batch_companies
                
            if len(companies) >= 2:
                expected_order = [company.name for company in companies]
                assert actual_order == expected_order, \
                    f"Batch {i} order should be preserved independently"


class TestSequentialProcessingOrderEdgeCases:
    """Edge case tests for sequential processing order."""
    
    def setup_method(self):
        clear_state()
    
    def teardown_method(self):
        clear_state()
    
    def test_single_company_maintains_order_trivially(self):
        """Test that single company processing maintains order (trivial case)."""
        mock_engine = MockResearchEngine()
        mock_cache = MockCacheManager()
        
        company = CompanyRecord(
            name="Single Company",
            domain="single.com",
            normalized_key=normalize_company("Single Company", "single.com"),
            row_index=0
        )
        
        result = ResearchResult(
            company_name="Single Company",
            company_domain="single.com",
            gcc_presence=True,
            gcc_location="Single Location",
            suitability_score=8,
            business_pain_points=["Single pain"],
            expansion_indicators=["Single expansion"],
            hiring_signals=["Single hiring"],
            research_summary="Single company research",
            is_cached=False,
            created_at=datetime.now(timezone.utc)
        )
        mock_engine.set_result_for_company("Single Company", result)
        
        session_id = str(uuid.uuid4())
        start_new_batch([company], session_id)
        state = get_current_state()
        
        with patch('src.components.results_processor.get_research_engine', return_value=mock_engine), \
             patch('src.components.results_processor.get_cache_manager', return_value=mock_cache):
            
            _process_one(state, user_session_id="test_session")
            
            assert len(state.items) == 1
            assert state.items[0].company_record.name == "Single Company"
            assert mock_engine.call_order == ["Single Company"]
    
    def test_empty_list_maintains_order_trivially(self):
        """Test that empty company list doesn't break processing order logic."""
        session_id = str(uuid.uuid4())
        start_new_batch([], session_id)
        state = get_current_state()
        
        assert state is not None
        assert len(state.company_records) == 0
        assert len(state.items) == 0
        assert state.current_index == 0
        
        # Processing should be immediately complete
        assert state.current_index >= len(state.company_records)
    
    def test_duplicate_companies_maintain_input_order(self):
        """Test that duplicate companies (same normalized key) maintain input order."""
        mock_engine = MockResearchEngine()
        mock_cache = MockCacheManager()
        
        # Create companies with same normalized key but different row indices
        company1 = CompanyRecord(
            name="Duplicate Corp",
            domain="duplicate.com",
            normalized_key=normalize_company("Duplicate Corp", "duplicate.com"),
            row_index=0
        )
        
        company2 = CompanyRecord(
            name="Duplicate Corp",
            domain="duplicate.com", 
            normalized_key=normalize_company("Duplicate Corp", "duplicate.com"),
            row_index=1
        )
        
        result = ResearchResult(
            company_name="Duplicate Corp",
            company_domain="duplicate.com",
            gcc_presence=True,
            gcc_location="Duplicate Location",
            suitability_score=6,
            business_pain_points=["Duplicate pain"],
            expansion_indicators=["Duplicate expansion"],
            hiring_signals=["Duplicate hiring"],
            research_summary="Duplicate research",
            is_cached=False,
            created_at=datetime.now(timezone.utc)
        )
        mock_engine.set_result_for_company("Duplicate Corp", result)
        
        companies = [company1, company2]
        session_id = str(uuid.uuid4())
        start_new_batch(companies, session_id)
        state = get_current_state()
        
        with patch('src.components.results_processor.get_research_engine', return_value=mock_engine), \
             patch('src.components.results_processor.get_cache_manager', return_value=mock_cache):
            
            # Process both companies
            _process_one(state, user_session_id="test_session")  # First company
            _process_one(state, user_session_id="test_session")  # Second company
            
            # Verify input order is maintained even for duplicates
            processed_row_indices = [item.company_record.row_index for item in state.items]
            assert processed_row_indices == [0, 1], "Duplicate companies should maintain input order"
            
            # First should be from research, second should be from cache
            assert state.items[0].is_cached is False, "First duplicate should not be cached"
            assert state.items[1].is_cached is True, "Second duplicate should be cached"