"""
Property-based tests for column detection consistency.

This module implements property tests that verify column detection behavior
according to Requirement 2.2 - recognizable patterns are consistently detected.

**Validates: Requirements 2.2**
"""

import pytest
from hypothesis import given, strategies as st, assume, settings, HealthCheck
from typing import List, Dict, Optional, Tuple
import string
import pandas as pd

# Add src to path for imports
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.utils.validation import detect_company_columns, ColumnDetectionResult


# Hypothesis strategies for generating test data
valid_header_chars = string.ascii_letters + string.digits + " _-"

@st.composite
def recognizable_name_columns(draw):
    """Generate column names that should be recognized as company name columns."""
    base_patterns = [
        "Company Name",
        "company_name", 
        "companyname",
        "Organization Name",
        "Business Name",
        "Company",
        "Organization",
        "Business",
        "Firm Name",
        "Entity Name",
        "Corporation Name"
    ]
    
    pattern = draw(st.sampled_from(base_patterns))
    
    # Sometimes add variations in case or spacing
    variations = draw(st.integers(min_value=0, max_value=3))
    
    if variations == 0:
        return pattern  # Exact match
    elif variations == 1:
        return pattern.upper()  # ALL CAPS
    elif variations == 2:
        return pattern.lower()  # all lowercase
    else:
        # Add extra spaces or underscores
        return pattern.replace(" ", "  ").replace("_", "__")


@st.composite
def recognizable_domain_columns(draw):
    """Generate column names that should be recognized as domain/website columns."""
    base_patterns = [
        "Company Domain",
        "company_domain",
        "companydomain", 
        "Website URL",
        "website_url",
        "Company Website",
        "Business Website",
        "Domain Name",
        "Website",
        "Domain",
        "URL",
        "Web Site",
        "Homepage"
    ]
    
    pattern = draw(st.sampled_from(base_patterns))
    
    # Sometimes add variations in case or spacing
    variations = draw(st.integers(min_value=0, max_value=3))
    
    if variations == 0:
        return pattern  # Exact match
    elif variations == 1:
        return pattern.upper()  # ALL CAPS
    elif variations == 2:
        return pattern.lower()  # all lowercase  
    else:
        # Add extra spaces or underscores
        return pattern.replace(" ", "  ").replace("_", "__")


@st.composite
def non_recognizable_columns(draw):
    """Generate column names that should NOT be recognized as company/domain columns."""
    unrelated_patterns = [
        "Employee Count",
        "Revenue",
        "Address",
        "Phone Number", 
        "Email",
        "Industry",
        "Location",
        "Founded Year",
        "CEO Name",
        "Stock Price",
        "Market Cap",
        "Description",
        "Notes",
        "Contact Person",
        "Sales Rep",
        "Last Updated",
        "Status",
        "Priority",
        "Category"
    ]
    
    return draw(st.sampled_from(unrelated_patterns))


@st.composite
def ambiguous_columns(draw):
    """Generate column names that might be ambiguous (low confidence matches)."""
    ambiguous_patterns = [
        "Name",  # Could be company name or person name
        "Site",  # Could be website or physical site
        "Link",  # Could be website or other link
        "Web"    # Could be website or web-related data
    ]
    
    return draw(st.sampled_from(ambiguous_patterns))


@st.composite
def csv_dataframes_with_recognizable_patterns(draw):
    """Generate DataFrames with recognizable company name and domain column patterns."""
    # Generate truly distinct recognizable column names
    name_patterns = [
        "Company Name", "Organization Name", "Business Name", "Firm Name",
        "Entity Name", "Corporation Name"  # These are clearly name-focused
    ]
    
    domain_patterns = [
        "Website URL", "Company Website", "Domain Name", "Website", 
        "Domain", "URL", "Homepage"  # These are clearly domain-focused
    ]
    
    name_col = draw(st.sampled_from(name_patterns))
    domain_col = draw(st.sampled_from(domain_patterns))
    
    # Ensure columns have different names
    assume(name_col.lower().strip() != domain_col.lower().strip())
    
    # Add some additional unrelated columns
    extra_cols = draw(st.lists(
        non_recognizable_columns(),
        min_size=0,
        max_size=3,
        unique=True
    ))
    
    # Ensure no naming conflicts
    all_cols = [name_col, domain_col] + extra_cols
    normalized_cols = [col.lower().strip() for col in all_cols]
    assume(len(set(normalized_cols)) == len(all_cols))  # All unique when normalized
    
    # Generate sample data
    num_rows = draw(st.integers(min_value=1, max_value=10))
    
    data = {}
    
    # Company names
    company_names = [
        "Acme Corporation", "Beta Industries", "Gamma LLC", "Delta Corp",
        "Echo Enterprises", "Foxtrot Inc", "Golf Company", "Hotel Ltd"
    ]
    data[name_col] = draw(st.lists(
        st.sampled_from(company_names),
        min_size=num_rows,
        max_size=num_rows
    ))
    
    # Domain names  
    domains = [
        "acme.com", "beta.org", "gamma.net", "delta.io",
        "echo.tech", "foxtrot.co", "golf.biz", "hotel.info"
    ]
    data[domain_col] = draw(st.lists(
        st.sampled_from(domains),
        min_size=num_rows,
        max_size=num_rows
    ))
    
    # Extra column data
    for col in extra_cols:
        data[col] = draw(st.lists(
            st.text(alphabet=string.ascii_letters + string.digits + " ", min_size=1, max_size=20),
            min_size=num_rows,
            max_size=num_rows
        ))
    
    df = pd.DataFrame(data)
    
    return df, name_col, domain_col


@st.composite
def csv_dataframes_with_ambiguous_patterns(draw):
    """Generate DataFrames with ambiguous column patterns for testing confidence levels."""
    # Use ambiguous column names
    name_col = draw(ambiguous_columns())
    
    # Sometimes include a domain column, sometimes not
    include_domain = draw(st.booleans())
    domain_col = draw(ambiguous_columns()) if include_domain else None
    
    # Ensure different names if both present
    if domain_col:
        assume(name_col.lower().strip() != domain_col.lower().strip())
    
    # Add many other columns to make ambiguous columns less obvious
    extra_cols = draw(st.lists(
        non_recognizable_columns(),
        min_size=3,
        max_size=8,
        unique=True
    ))
    
    # Build column list
    all_cols = [name_col]
    if domain_col:
        all_cols.append(domain_col)
    all_cols.extend(extra_cols)
    
    # Ensure no naming conflicts
    normalized_cols = [col.lower().strip() for col in all_cols]
    assume(len(set(normalized_cols)) == len(all_cols))
    
    # Generate sample data
    num_rows = draw(st.integers(min_value=1, max_value=10))
    
    data = {}
    
    # Company names in ambiguous column
    company_names = ["Microsoft", "Apple", "Google", "Amazon"]
    data[name_col] = draw(st.lists(
        st.sampled_from(company_names),
        min_size=num_rows,
        max_size=num_rows
    ))
    
    # Domain data if present
    if domain_col:
        domains = ["microsoft.com", "apple.com", "google.com", "amazon.com"]
        data[domain_col] = draw(st.lists(
            st.sampled_from(domains),
            min_size=num_rows,
            max_size=num_rows
        ))
    
    # Extra column data
    for col in extra_cols:
        data[col] = draw(st.lists(
            st.text(alphabet=string.ascii_letters + string.digits + " ", min_size=1, max_size=20),
            min_size=num_rows,
            max_size=num_rows
        ))
    
    df = pd.DataFrame(data)
    
    return df, name_col, domain_col


class TestColumnDetectionProperties:
    """Property-based tests for column detection consistency."""
    
    @given(csv_dataframes_with_recognizable_patterns())
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=100)
    def test_property_4_column_detection_consistency_recognizable_patterns(self, df_and_columns):
        """
        **Validates: Requirements 2.2**
        
        Property 4: Column Detection Consistency
        For any CSV file with recognizable company name and domain column patterns,
        auto-detection shall consistently identify the correct columns.
        
        This property ensures that when clear, recognizable patterns are present,
        the detection algorithm consistently identifies the correct columns.
        """
        df, expected_name_col, expected_domain_col = df_and_columns
        
        # Run column detection
        result = detect_company_columns(df)
        
        # Verify that recognizable patterns are detected
        assert result.name_column is not None, (
            f"Should detect name column for recognizable pattern: '{expected_name_col}'. "
            f"Available columns: {list(df.columns)}"
        )
        
        # Verify the detected column is actually a name-related column
        # The algorithm might pick a different but still valid name column due to priority order
        detected_name_normalized = result.name_column.lower().strip()
        
        # Check that the detected column matches a name pattern
        name_keywords = [
            "company", "organization", "organisation", "business", "firm", 
            "enterprise", "corp", "corporation", "entity", "name"
        ]
        
        assert any(keyword in detected_name_normalized for keyword in name_keywords), (
            f"Detected column '{result.name_column}' should match a company name pattern. "
            f"Available columns: {list(df.columns)}"
        )
        
        # Domain column detection
        assert result.domain_column is not None, (
            f"Should detect domain column for recognizable pattern: '{expected_domain_col}'. "
            f"Available columns: {list(df.columns)}"
        )
        
        # Verify the detected column is actually a domain-related column
        detected_domain_normalized = result.domain_column.lower().strip()
        
        domain_keywords = [
            "domain", "website", "web", "url", "site", "homepage", "link"
        ]
        
        assert any(keyword in detected_domain_normalized for keyword in domain_keywords), (
            f"Detected column '{result.domain_column}' should match a domain pattern. "
            f"Available columns: {list(df.columns)}"
        )
        
        # Test consistency - running detection multiple times should yield same results
        result2 = detect_company_columns(df)
        assert result2.name_column == result.name_column, (
            "Column detection should be consistent across multiple calls"
        )
        assert result2.domain_column == result.domain_column, (
            "Domain detection should be consistent across multiple calls"  
        )
        assert result2.name_confident == result.name_confident, (
            "Name confidence should be consistent across multiple calls"
        )
        assert result2.domain_confident == result.domain_confident, (
            "Domain confidence should be consistent across multiple calls"
        )
    
    @given(csv_dataframes_with_recognizable_patterns())
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=50)
    def test_property_4_column_detection_consistency_high_confidence(self, df_and_columns):
        """
        **Validates: Requirements 2.2**
        
        Property 4 Extended: High Confidence Detection for Clear Patterns
        For any CSV file with clear, recognizable company name and domain patterns,
        auto-detection shall consistently report high confidence in its detection.
        """
        df, expected_name_col, expected_domain_col = df_and_columns
        
        # Run column detection  
        result = detect_company_columns(df)
        
        # For recognizable patterns, confidence should generally be high
        # (though some patterns may still be ambiguous depending on context)
        
        # Check if the pattern should be high confidence
        high_confidence_name_patterns = [
            "company name", "company_name", "companyname",
            "organization name", "business name", "firm name"
        ]
        
        expected_name_lower = expected_name_col.lower().strip()
        should_be_high_confidence_name = any(
            pattern in expected_name_lower for pattern in high_confidence_name_patterns
        )
        
        if should_be_high_confidence_name:
            assert result.name_confident is True, (
                f"Should have high confidence for clear name pattern: '{expected_name_col}'"
            )
        
        # Check domain confidence
        high_confidence_domain_patterns = [
            "company domain", "company_domain", "website url", 
            "company website", "domain name"
        ]
        
        expected_domain_lower = expected_domain_col.lower().strip()
        should_be_high_confidence_domain = any(
            pattern in expected_domain_lower for pattern in high_confidence_domain_patterns
        )
        
        if should_be_high_confidence_domain:
            assert result.domain_confident is True, (
                f"Should have high confidence for clear domain pattern: '{expected_domain_col}'"
            )
    
    @given(csv_dataframes_with_ambiguous_patterns())
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=50) 
    def test_property_4_column_detection_consistency_ambiguous_patterns(self, df_and_columns):
        """
        **Validates: Requirements 2.2**
        
        Property 4 Extended: Consistent Handling of Ambiguous Patterns  
        For any CSV file with ambiguous column patterns (like generic "Name" or "Site"),
        auto-detection shall consistently handle these cases and report appropriate confidence levels.
        """
        df, expected_name_col, expected_domain_col = df_and_columns
        
        # Run column detection
        result = detect_company_columns(df)
        
        # For ambiguous patterns, detection might still work but confidence should be lower
        # or detection might fail entirely - both are acceptable as long as it's consistent
        
        # Test consistency - same input should always produce same output
        result2 = detect_company_columns(df)
        
        assert result2.name_column == result.name_column, (
            "Name column detection should be consistent for ambiguous patterns"
        )
        assert result2.domain_column == result.domain_column, (
            "Domain column detection should be consistent for ambiguous patterns"
        )
        assert result2.name_confident == result.name_confident, (
            "Name confidence should be consistent for ambiguous patterns"
        )
        assert result2.domain_confident == result.domain_confident, (
            "Domain confidence should be consistent for ambiguous patterns"
        )
        
        # If detection succeeds for ambiguous patterns, confidence should generally be low
        # (unless there are very few columns making the choice obvious)
        if result.name_column is not None:
            num_columns = len(df.columns)
            if num_columns > 3:  # Multiple columns make ambiguous names less obvious
                expected_name_lower = expected_name_col.lower().strip()
                if expected_name_lower in ["name", "site", "link", "web"]:
                    # For very generic terms with many columns, confidence should be low
                    assert result.name_confident is False, (
                        f"Should have low confidence for ambiguous pattern '{expected_name_col}' "
                        f"with {num_columns} total columns"
                    )
    
    @given(st.integers(min_value=1, max_value=20))
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=30)
    def test_property_4_column_detection_consistency_empty_and_edge_cases(self, num_unrelated_cols):
        """
        **Validates: Requirements 2.2**
        
        Property 4 Extended: Consistent Handling of Edge Cases
        For any CSV file without recognizable patterns, auto-detection shall
        consistently report no detection or low confidence.
        """
        # Create DataFrame with only unrelated columns (no recognizable patterns)
        unrelated_patterns = [
            "Employee Count", "Revenue", "Address", "Phone Number", 
            "Email", "Industry", "Location", "Founded Year", "CEO Name",
            "Stock Price", "Market Cap", "Description", "Notes"
        ]
        
        # Select random unrelated columns
        selected_cols = []
        for i in range(min(num_unrelated_cols, len(unrelated_patterns))):
            col_name = f"{unrelated_patterns[i % len(unrelated_patterns)]}_{i}" if i >= len(unrelated_patterns) else unrelated_patterns[i]
            selected_cols.append(col_name)
        
        if not selected_cols:
            selected_cols = ["Unrelated Column"]
        
        # Create DataFrame with sample data
        data = {}
        for col in selected_cols:
            data[col] = ["sample1", "sample2", "sample3"]
        
        df = pd.DataFrame(data)
        
        # Run detection
        result = detect_company_columns(df)
        
        # Should either find nothing, or find something with low confidence
        # (since there are no clear company/domain patterns)
        
        # Test consistency
        result2 = detect_company_columns(df)
        
        assert result2.name_column == result.name_column, (
            "Detection should be consistent for DataFrames without recognizable patterns"
        )
        assert result2.domain_column == result.domain_column, (
            "Domain detection should be consistent for DataFrames without recognizable patterns"
        )
        assert result2.name_confident == result.name_confident, (
            "Name confidence should be consistent for DataFrames without recognizable patterns"
        )
        assert result2.domain_confident == result.domain_confident, (
            "Domain confidence should be consistent for DataFrames without recognizable patterns"
        )
        
        # If anything is detected from unrelated columns, confidence should be low
        if result.name_column is not None:
            # The algorithm might pick the first column or make some heuristic choice
            # but it shouldn't be confident about it
            assert result.name_confident is False, (
                f"Should not be confident when detecting from unrelated columns. "
                f"Detected: '{result.name_column}' from {selected_cols}"
            )
    
    def test_property_4_column_detection_deterministic_behavior(self):
        """
        **Validates: Requirements 2.2**
        
        Property 4 Extended: Deterministic Behavior
        Column detection should produce the same results for the same input DataFrame.
        This tests that the detection algorithm is deterministic and not affected by 
        random factors or internal state.
        """
        # Create a specific test DataFrame
        df = pd.DataFrame({
            "Company Name": ["Microsoft", "Apple", "Google"],
            "Website": ["microsoft.com", "apple.com", "google.com"], 
            "Employee Count": ["100000", "150000", "120000"],
            "Revenue": ["1B", "2B", "1.5B"]
        })
        
        # Run detection multiple times
        results = []
        for _ in range(10):
            result = detect_company_columns(df)
            results.append(result)
        
        # All results should be identical
        first_result = results[0]
        for i, result in enumerate(results[1:], 1):
            assert result.name_column == first_result.name_column, (
                f"Name column detection should be deterministic. "
                f"Run {i} got '{result.name_column}', expected '{first_result.name_column}'"
            )
            assert result.domain_column == first_result.domain_column, (
                f"Domain column detection should be deterministic. "
                f"Run {i} got '{result.domain_column}', expected '{first_result.domain_column}'"
            )
            assert result.name_confident == first_result.name_confident, (
                f"Name confidence should be deterministic. "
                f"Run {i} got {result.name_confident}, expected {first_result.name_confident}"
            )
            assert result.domain_confident == first_result.domain_confident, (
                f"Domain confidence should be deterministic. "
                f"Run {i} got {result.domain_confident}, expected {first_result.domain_confident}"
            )


class TestColumnDetectionEdgeCases:
    """Edge case tests for column detection robustness."""
    
    def test_empty_dataframe_handling(self):
        """Test that empty DataFrames are handled gracefully."""
        # DataFrame with no columns
        df_no_cols = pd.DataFrame()
        result = detect_company_columns(df_no_cols)
        
        assert result.name_column is None, "Should return None for name column with no columns"
        assert result.domain_column is None, "Should return None for domain column with no columns"
        assert result.name_confident is False, "Should not be confident with no columns"
        assert result.domain_confident is False, "Should not be confident with no columns"
        
        # DataFrame with columns but no rows
        df_no_rows = pd.DataFrame({"Company Name": [], "Website": []})
        result2 = detect_company_columns(df_no_rows)
        
        # Should still detect columns even with no data rows
        assert result2.name_column == "Company Name", "Should detect name column even with no rows"
        assert result2.domain_column == "Website", "Should detect domain column even with no rows"
    
    def test_single_column_dataframe(self):
        """Test detection with only one column."""
        # Single column that matches company name pattern
        df_single_name = pd.DataFrame({"Company Name": ["Microsoft", "Apple"]})
        result = detect_company_columns(df_single_name)
        
        assert result.name_column == "Company Name", "Should detect single name column"
        assert result.domain_column is None, "Should not detect domain column when none exists"
        
        # Single column that matches domain pattern  
        df_single_domain = pd.DataFrame({"Website": ["microsoft.com", "apple.com"]})
        result2 = detect_company_columns(df_single_domain)
        
        # Might detect Website as domain, but no name column available
        assert result2.domain_column == "Website", "Should detect single domain column"
        assert result2.name_column is None, "Should not detect name column when none exists"
    
    def test_duplicate_pattern_preferences(self):
        """Test that when multiple columns match patterns, preferences are consistent."""
        # Multiple columns that could be company names
        df_multiple_names = pd.DataFrame({
            "Company Name": ["Microsoft", "Apple"],
            "Organization": ["Microsoft Corp", "Apple Inc"],
            "Business Name": ["Microsoft LLC", "Apple LLC"],
            "Revenue": ["1B", "2B"]
        })
        
        result = detect_company_columns(df_multiple_names)
        
        # Should pick one consistently (preference order should be deterministic)
        assert result.name_column is not None, "Should detect a name column from multiple candidates"
        
        # Run again to ensure consistency
        result2 = detect_company_columns(df_multiple_names)
        assert result2.name_column == result.name_column, "Should consistently pick same column from multiple candidates"
    
    def test_case_insensitive_detection(self):
        """Test that detection works regardless of case."""
        test_cases = [
            {"company name": ["Microsoft"], "website": ["microsoft.com"]},  # lowercase
            {"COMPANY NAME": ["Microsoft"], "WEBSITE": ["microsoft.com"]},  # uppercase  
            {"Company Name": ["Microsoft"], "Website": ["microsoft.com"]},  # title case
            {"CoMpAnY nAmE": ["Microsoft"], "WeBsItE": ["microsoft.com"]},  # mixed case
        ]
        
        results = []
        for data in test_cases:
            df = pd.DataFrame(data)
            result = detect_company_columns(df)
            results.append((result.name_column, result.domain_column))
        
        # All should detect the appropriate columns regardless of case
        for i, (name_col, domain_col) in enumerate(results):
            assert name_col is not None, f"Case variant {i} should detect name column"
            assert domain_col is not None, f"Case variant {i} should detect domain column"
            
            # Normalize for comparison (the exact column name returned will match input case)
            name_normalized = name_col.lower().replace(" ", "")
            domain_normalized = domain_col.lower()
            
            assert "company" in name_normalized and "name" in name_normalized, f"Case variant {i} should detect company name pattern"
            assert "website" in domain_normalized or "web" in domain_normalized, f"Case variant {i} should detect website pattern"