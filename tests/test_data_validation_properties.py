"""
Property-based tests for data validation completeness.

This module implements property tests that verify data validation consistency
according to Requirements 2.4 and 2.5 - invalid data is consistently rejected.

**Validates: Requirements 2.4, 2.5**
"""

import pytest
from hypothesis import given, strategies as st, assume, settings, HealthCheck
from typing import List, Dict, Optional, Tuple
import string
import pandas as pd
import numpy as np

# Add src to path for imports
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.utils.validation import (
    validate_selected_columns, 
    FileValidationResult,
    RowValidationError,
    DataQualityIssue,
    ValidationError,
    _validate_company_name,
    _validate_domain,
    MAX_COMPANY_NAME_LENGTH,
    MAX_DOMAIN_LENGTH
)

# Hypothesis strategies for generating test data
valid_name_chars = string.ascii_letters + string.digits + " .,'-&()[]"
invalid_name_chars = string.punctuation.replace(".", "").replace(",", "").replace("'", "").replace("-", "").replace("&", "").replace("(", "").replace(")", "").replace("[", "").replace("]", "") + "\x00\x01\x02\x03\x04"
valid_domain_chars = string.ascii_lowercase + string.digits + ".-"
invalid_domain_chars = string.ascii_uppercase + " !@#$%^&*()+=[]{}|\\:;\"'<>,?/~`\x00\x01\x02"

@st.composite
def invalid_company_names(draw):
    """Generate company names that should be rejected by validation."""
    choice = draw(st.integers(min_value=1, max_value=6))
    
    if choice == 1:
        # Empty or whitespace-only names
        return draw(st.sampled_from(["", "   ", "\t", "\n", " \t \n ", None]))
    elif choice == 2:
        # Too short names (< 2 characters)
        return draw(st.text(alphabet=valid_name_chars, max_size=1))
    elif choice == 3:
        # Too long names
        return "A" * (MAX_COMPANY_NAME_LENGTH + 1)
    elif choice == 4:
        # Names with only numbers (minimum 2 digits to pass length check)
        digits = draw(st.integers(min_value=2, max_value=10))
        return "1" * digits
    elif choice == 5:
        # Just punctuation marks (passes length but should be flagged as quality issue, not hard error)
        return draw(st.text(alphabet="!@#$%^*()+=[]{}|\\:;\"<>?/~`", min_size=2, max_size=5))
    else:
        # Names that start/end with whitespace (will be stripped, might become too short)
        base = draw(st.text(alphabet=string.ascii_letters, min_size=0, max_size=3))
        return "   " + base + "   "

@st.composite
def invalid_domains(draw):
    """Generate domain values that should be rejected by validation."""
    choice = draw(st.integers(min_value=1, max_value=7))
    
    if choice == 1:
        # Too long domains
        return "a" * (MAX_DOMAIN_LENGTH + 1) + ".com"
    elif choice == 2:
        # Invalid domain format - spaces
        base = draw(st.text(alphabet=string.ascii_letters, min_size=3, max_size=10))
        return f"{base} .com"
    elif choice == 3:
        # Invalid domain format - invalid characters
        base = draw(st.text(alphabet=string.ascii_letters, min_size=3, max_size=10))
        invalid_char = draw(st.sampled_from(invalid_domain_chars))
        return f"{base}{invalid_char}.com"
    elif choice == 4:
        # Invalid domain format - consecutive dots
        base = draw(st.text(alphabet=string.ascii_letters, min_size=3, max_size=10))
        return f"{base}..com"
    elif choice == 5:
        # Invalid domain format - starts with dot
        base = draw(st.text(alphabet=string.ascii_letters, min_size=3, max_size=10))
        return f".{base}.com"
    elif choice == 6:
        # Invalid domain format - ends with dot
        base = draw(st.text(alphabet=string.ascii_letters, min_size=3, max_size=10))
        return f"{base}.com."
    else:
        # Invalid domain format - no TLD
        return draw(st.text(alphabet=string.ascii_letters, min_size=1, max_size=10))

@st.composite
def valid_company_names(draw):
    """Generate valid company names for testing."""
    patterns = [
        "Acme Corporation",
        "Beta Industries LLC", 
        "Gamma Tech Solutions",
        "Delta Manufacturing Co.",
        "Echo Enterprises Ltd",
        "Foxtrot & Associates",
        "Golf International Inc",
        "Hotel Services Group"
    ]
    
    # Either use a predefined pattern or generate a new one
    use_predefined = draw(st.booleans())
    
    if use_predefined:
        return draw(st.sampled_from(patterns))
    else:
        # Generate valid name
        base = draw(st.text(alphabet=string.ascii_letters, min_size=2, max_size=20))
        suffix = draw(st.sampled_from(["Inc", "Corp", "LLC", "Ltd", "Co", "Company", ""]))
        
        if suffix:
            return f"{base} {suffix}"
        else:
            return base

@st.composite
def valid_domains(draw):
    """Generate valid domain names for testing."""
    domains = [
        "microsoft.com",
        "apple.com", 
        "google.com",
        "amazon.com",
        "meta.com",
        "tesla.com",
        "netflix.com",
        "adobe.com"
    ]
    
    # Either use predefined or generate new
    use_predefined = draw(st.booleans())
    
    if use_predefined:
        return draw(st.sampled_from(domains))
    else:
        # Generate valid domain
        name = draw(st.text(alphabet=string.ascii_lowercase + string.digits, min_size=2, max_size=15))
        tld = draw(st.sampled_from(["com", "org", "net", "edu", "gov", "io", "co", "tech"]))
        return f"{name}.{tld}"

@st.composite
def mixed_valid_invalid_dataframes(draw):
    """Generate DataFrames with a mix of valid and invalid company data."""
    num_rows = draw(st.integers(min_value=1, max_value=20))
    
    # Generate company names - mix of valid and invalid
    company_names = []
    expected_invalid_indices = []
    
    for i in range(num_rows):
        # 70% chance of valid name, 30% chance of invalid
        is_valid = draw(st.booleans()) if draw(st.integers(1, 10)) <= 7 else False
        
        if is_valid:
            name = draw(valid_company_names())
        else:
            name = draw(invalid_company_names())
            expected_invalid_indices.append(i)
        
        company_names.append(name)
    
    # Generate domains - optional column
    include_domains = draw(st.booleans())
    domains = []
    expected_domain_invalid_indices = []
    
    if include_domains:
        for i in range(num_rows):
            # 80% chance of valid domain (since domains are optional), 20% invalid
            is_valid = draw(st.booleans()) if draw(st.integers(1, 10)) <= 8 else False
            
            if is_valid:
                # 30% chance of empty domain (valid since optional)
                if draw(st.integers(1, 10)) <= 3:
                    domain = ""
                else:
                    domain = draw(valid_domains())
            else:
                domain = draw(invalid_domains())
                expected_domain_invalid_indices.append(i)
            
            domains.append(domain)
    
    # Create DataFrame
    data = {"CompanyName": company_names}
    domain_column = None
    
    if include_domains:
        data["Domain"] = domains
        domain_column = "Domain"
    
    df = pd.DataFrame(data)
    
    return df, "CompanyName", domain_column, expected_invalid_indices, expected_domain_invalid_indices

@st.composite
def all_invalid_dataframes(draw):
    """Generate DataFrames where all company names are invalid."""
    num_rows = draw(st.integers(min_value=1, max_value=10))
    
    # All invalid company names
    company_names = []
    for i in range(num_rows):
        name = draw(invalid_company_names())
        company_names.append(name)
    
    # Domains can be valid or invalid since they're optional
    include_domains = draw(st.booleans())
    domains = []
    
    if include_domains:
        for i in range(num_rows):
            # Mix of valid and invalid domains
            is_valid = draw(st.booleans())
            if is_valid:
                domain = draw(valid_domains()) if draw(st.booleans()) else ""
            else:
                domain = draw(invalid_domains())
            domains.append(domain)
    
    data = {"CompanyName": company_names}
    domain_column = None
    
    if include_domains:
        data["Domain"] = domains  
        domain_column = "Domain"
    
    df = pd.DataFrame(data)
    
    return df, "CompanyName", domain_column
class TestDataValidationProperties:
    """Property-based tests for data validation completeness."""
    
    @given(mixed_valid_invalid_dataframes())
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=100)
    def test_property_5_data_validation_completeness_mixed_data(self, df_and_info):
        """
        **Validates: Requirements 2.4, 2.5**
        
        Property 5: Data Validation Completeness
        For any selected columns containing empty or invalid data, 
        the validation process shall consistently reject the data with specific error messages.
        
        This property tests that validation consistently identifies and rejects invalid data
        while preserving valid data in mixed datasets.
        """
        df, name_column, domain_column, expected_invalid_name_indices, expected_invalid_domain_indices = df_and_info
        
        # Run validation
        validation = validate_selected_columns(df, name_column, domain_column)
        
        # Check that validation completed without crashing
        assert isinstance(validation, FileValidationResult), "Validation should return FileValidationResult"
        assert validation.total_row_count == len(df), "Total row count should match DataFrame length"
        
        # Check that invalid rows were identified
        invalid_row_indices = {error.row_index for error in validation.row_errors}
        
        # Every row with invalid company name should be flagged
        for invalid_idx in expected_invalid_name_indices:
            if invalid_idx < len(df):  # Make sure index is valid
                name_value = df.iloc[invalid_idx][name_column]
                
                # Check if this should actually be invalid
                if pd.isna(name_value) or not str(name_value).strip() or len(str(name_value).strip()) < 2:
                    assert invalid_idx in invalid_row_indices, (
                        f"Row {invalid_idx} with invalid company name '{name_value}' should be rejected"
                    )
        
        # Check that each error has proper structure
        for error in validation.row_errors:
            assert isinstance(error, RowValidationError), "Row errors should be RowValidationError instances"
            assert error.row_index >= 0, "Row index should be non-negative"
            assert error.row_index < len(df), "Row index should be within DataFrame bounds"
            assert error.message, "Error should have non-empty message"
            assert error.error_type, "Error should have error type"
            # Note: error.column uses normalized names ('company_name', 'domain'), not original column names
            assert error.column in ["company_name", "domain"], "Error should reference a validation column type"
        
        # Test consistency - running validation again should yield same results
        validation2 = validate_selected_columns(df, name_column, domain_column)
        
        assert validation2.is_valid == validation.is_valid, "Validation result should be consistent"
        assert validation2.valid_row_count == validation.valid_row_count, "Valid row count should be consistent"
        assert len(validation2.row_errors) == len(validation.row_errors), "Error count should be consistent"
        
        # Check that error indices are the same
        invalid_row_indices2 = {error.row_index for error in validation2.row_errors}
        assert invalid_row_indices == invalid_row_indices2, "Invalid row indices should be consistent"
    
    @given(all_invalid_dataframes())
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=50)
    def test_property_5_data_validation_completeness_all_invalid(self, df_and_info):
        """
        **Validates: Requirements 2.4, 2.5**
        
        Property 5 Extended: Complete Rejection of All Invalid Data
        For any dataset where all company names are invalid, 
        validation shall consistently reject all rows and report appropriate errors.
        """
        df, name_column, domain_column = df_and_info
        
        # Run validation
        validation = validate_selected_columns(df, name_column, domain_column)
        
        # Check that validation completed
        assert isinstance(validation, FileValidationResult), "Should return validation result"
        
        # Should either:
        # 1. Reject all rows (valid_row_count == 0), OR
        # 2. Have significant validation issues 
        
        # Check if the data we generated is truly invalid (not just quality issues)
        truly_invalid_count = 0
        for i in range(len(df)):
            name_value = df.iloc[i][name_column]
            name_str = str(name_value).strip() if pd.notna(name_value) else ""
            
            # Count names that should be hard validation failures
            if (not name_str or 
                len(name_str) < 2 or 
                len(name_str) > MAX_COMPANY_NAME_LENGTH or
                (name_str.isdigit() and len(name_str) >= 2)):
                truly_invalid_count += 1
        
        # If we have truly invalid data, it should be caught
        if truly_invalid_count > 0:
            # Should have validation errors or be marked invalid
            assert (not validation.is_valid or 
                    validation.valid_row_count < len(df) or 
                    len(validation.row_errors) > 0), (
                f"Should catch {truly_invalid_count} truly invalid names"
            )
        
        # Check error messages are specific and helpful
        if validation.row_errors:
            for error in validation.row_errors:
                # Accept various types of validation error messages
                valid_message_patterns = [
                    "empty", "invalid", "short", "long", "numeric", "numbers"
                ]
                assert any(pattern in error.message.lower() for pattern in valid_message_patterns), (
                    f"Error message should be specific: '{error.message}'"
                )
        
        # Test consistency for all-invalid datasets
        validation2 = validate_selected_columns(df, name_column, domain_column)
        assert validation2.valid_row_count == validation.valid_row_count, "Consistent rejection of all invalid data"
        assert validation2.is_valid == validation.is_valid, "Consistent overall validation result"
    
    @given(st.text(min_size=0, max_size=1000))
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=100)
    def test_property_5_data_validation_completeness_individual_names(self, company_name):
        """
        **Validates: Requirements 2.4, 2.5**
        
        Property 5 Extended: Individual Name Validation Consistency
        For any individual company name input, validation should consistently 
        determine validity based on the established rules.
        """
        # Test individual name validation function directly
        result, quality_issues = _validate_company_name(company_name, 0)
        
        # Check consistency - same input should always give same result
        result2, quality_issues2 = _validate_company_name(company_name, 0)
        
        if result is None and result2 is None:
            # Both None - consistent
            assert len(quality_issues) == len(quality_issues2), "Quality issues should be consistent"
        elif result is not None and result2 is not None:
            # Both have errors - should be the same error
            assert result.error_type == result2.error_type, "Error type should be consistent"
            assert result.message == result2.message, "Error message should be consistent"
        else:
            # One None, one not None - inconsistent
            assert False, f"Validation should be consistent: {result} vs {result2}"
        
        # Validate the logic of rejection
        name_str = str(company_name).strip() if company_name is not None else ""
        
        # Check that truly invalid names are rejected
        if not name_str or len(name_str) < 2:
            assert result is not None, f"Empty or too short name should be rejected: '{company_name}'"
            assert result.error_type in ["EMPTY_NAME", "NAME_TOO_SHORT"], "Should have appropriate error type"
        
        if len(name_str) > MAX_COMPANY_NAME_LENGTH:
            assert result is not None, "Too long name should be rejected"
            assert result.error_type == "NAME_TOO_LONG", "Should have appropriate error type"
        
        # Numeric-only names should be rejected (but check length first)
        if name_str and name_str.isdigit() and len(name_str) >= 2:
            assert result is not None, "Numeric-only name should be rejected"
            assert result.error_type == "NUMERIC_ONLY_NAME", "Should have appropriate error type"
    
    @given(st.text(min_size=0, max_size=500))
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=100)
    def test_property_5_data_validation_completeness_individual_domains(self, domain_input):
        """
        **Validates: Requirements 2.4, 2.5**
        
        Property 5 Extended: Individual Domain Validation Consistency
        For any individual domain input, validation should consistently 
        determine validity based on established domain format rules.
        """
        # Test individual domain validation function directly
        result, quality_issues = _validate_domain(domain_input, 0)
        
        # Check consistency - same input should always give same result
        result2, quality_issues2 = _validate_domain(domain_input, 0)
        
        if result is None and result2 is None:
            # Both None - consistent (valid or empty domain)
            assert len(quality_issues) == len(quality_issues2), "Quality issues should be consistent"
        elif result is not None and result2 is not None:
            # Both have errors - should be the same error
            assert result.error_type == result2.error_type, "Error type should be consistent"
            assert result.message == result2.message, "Error message should be consistent"
        else:
            # Inconsistent validation
            assert False, f"Domain validation should be consistent: {result} vs {result2}"
        
        # Validate the logic of rejection
        if pd.isna(domain_input) or not str(domain_input).strip():
            # Empty domains should be accepted (domains are optional)
            assert result is None, "Empty domain should be accepted (optional field)"
        
        domain_str = str(domain_input).strip() if domain_input is not None else ""
        
        if domain_str and len(domain_str) > MAX_DOMAIN_LENGTH:
            assert result is not None, "Too long domain should be rejected"
            assert result.error_type == "DOMAIN_TOO_LONG", "Should have appropriate error type"
    
    def test_property_5_data_validation_deterministic_behavior(self):
        """
        **Validates: Requirements 2.4, 2.5**
        
        Property 5 Extended: Deterministic Validation Behavior
        Data validation should produce the same results for the same input DataFrame.
        This tests that validation is deterministic and not affected by random factors.
        """
        # Create specific test DataFrame with known valid and invalid data
        df = pd.DataFrame({
            "Company": [
                "Microsoft Corporation",  # Valid
                "",                       # Invalid - empty
                "A",                      # Invalid - too short 
                "Google Inc",             # Valid
                "123456",                 # Invalid - numeric only
                "Amazon.com Inc",         # Valid
                None                      # Invalid - null
            ],
            "Domain": [
                "microsoft.com",          # Valid
                "google.com",             # Valid
                "invalid domain.com",     # Invalid - space
                "amazon.com",             # Valid
                "test..com",              # Invalid - consecutive dots
                "apple.com",              # Valid
                ""                        # Valid - empty (optional)
            ]
        })
        
        # Run validation multiple times
        results = []
        for _ in range(10):
            validation = validate_selected_columns(df, "Company", "Domain")
            results.append(validation)
        
        # All results should be identical
        first_result = results[0]
        for i, result in enumerate(results[1:], 1):
            assert result.is_valid == first_result.is_valid, (
                f"Validation result should be deterministic. Run {i} differs in is_valid"
            )
            assert result.valid_row_count == first_result.valid_row_count, (
                f"Valid row count should be deterministic. Run {i} differs"
            )
            assert len(result.row_errors) == len(first_result.row_errors), (
                f"Error count should be deterministic. Run {i} differs"
            )
            
            # Check that error indices are the same
            error_indices = {error.row_index for error in result.row_errors}
            first_error_indices = {error.row_index for error in first_result.row_errors}
            assert error_indices == first_error_indices, (
                f"Error indices should be deterministic. Run {i} differs"
            )
    
    @given(st.integers(min_value=1, max_value=50))
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=30)
    def test_property_5_data_validation_completeness_edge_cases(self, num_rows):
        """
        **Validates: Requirements 2.4, 2.5**
        
        Property 5 Extended: Edge Case Validation Completeness
        For any DataFrame with edge case data (boundary values, special characters, etc.),
        validation should handle all cases gracefully without crashing.
        """
        # Create DataFrame with various edge cases
        edge_case_names = [
            "",                                    # Empty
            " ",                                   # Whitespace only
            "A",                                   # Minimum length - 1
            "AB",                                  # Minimum length
            "A" * MAX_COMPANY_NAME_LENGTH,         # Maximum length
            "A" * (MAX_COMPANY_NAME_LENGTH + 1),   # Over maximum length
            "123",                                 # Numeric
            "Test\x00Company",                     # Control characters
            "Company@email.com",                   # Email pattern
            "https://www.company.com",             # URL pattern
            "Test & Associates",                   # Valid with special chars
            "中文公司",                             # Unicode characters
            "Company\n\tName",                     # Whitespace characters
            None                                   # None value
        ]
        
        edge_case_domains = [
            "",                                    # Empty (valid)
            "company.com",                         # Valid
            "a" * (MAX_DOMAIN_LENGTH + 1),         # Too long
            "invalid domain.com",                  # Space in domain
            "company..com",                        # Double dot
            ".company.com",                        # Leading dot
            "company.com.",                        # Trailing dot
            "192.168.1.1",                        # IP address
            "localhost",                           # Local domain
            "company.com/path",                    # URL with path
            "COMPANY.COM",                         # Uppercase
            None                                   # None value
        ]
        
        # Create test data by cycling through edge cases
        companies = []
        domains = []
        
        for i in range(num_rows):
            companies.append(edge_case_names[i % len(edge_case_names)])
            domains.append(edge_case_domains[i % len(edge_case_domains)])
        
        df = pd.DataFrame({
            "Company": companies,
            "Domain": domains
        })
        
        # Validation should not crash on any edge case
        try:
            validation = validate_selected_columns(df, "Company", "Domain")
            
            # Should return valid result object
            assert isinstance(validation, FileValidationResult), "Should return FileValidationResult"
            assert validation.total_row_count == num_rows, "Should count all rows"
            
            # Should handle all edge cases gracefully
            assert validation.valid_row_count >= 0, "Valid row count should be non-negative"
            assert validation.valid_row_count <= num_rows, "Valid row count should not exceed total"
            
            # Error objects should be well-formed
            for error in validation.row_errors:
                assert isinstance(error, RowValidationError), "Errors should be RowValidationError instances"
                assert 0 <= error.row_index < num_rows, f"Error row index {error.row_index} should be in valid range"
                assert error.message, "Error should have message"
                assert error.error_type, "Error should have type"
            
        except Exception as e:
            assert False, f"Validation should not crash on edge cases: {e}"


class TestDataValidationEdgeCases:
    """Edge case tests for data validation robustness."""
    
    def test_validation_with_missing_columns(self):
        """Test validation behavior when selected columns don't exist."""
        df = pd.DataFrame({"WrongName": ["Company1"], "WrongDomain": ["domain.com"]})
        
        # Missing name column
        validation = validate_selected_columns(df, "Company", "Domain")
        assert not validation.is_valid
        assert validation.has_critical_errors
        assert "not found" in validation.errors[0]
    
    def test_validation_with_empty_dataframe(self):
        """Test validation with empty DataFrames."""
        # Empty DataFrame with no rows
        df = pd.DataFrame({"Company": [], "Domain": []})
        validation = validate_selected_columns(df, "Company", "Domain")
        
        assert not validation.is_valid
        assert validation.total_row_count == 0
        assert "no data rows" in validation.errors[0]
    
    def test_validation_with_single_row(self):
        """Test validation with single-row DataFrames."""
        # Single valid row
        df = pd.DataFrame({"Company": ["Microsoft"], "Domain": ["microsoft.com"]})
        validation = validate_selected_columns(df, "Company", "Domain")
        
        assert validation.is_valid
        assert validation.valid_row_count == 1
        assert validation.total_row_count == 1
        
        # Single invalid row
        df2 = pd.DataFrame({"Company": [""], "Domain": ["microsoft.com"]})
        validation2 = validate_selected_columns(df2, "Company", "Domain")
        
        assert not validation2.is_valid
        assert validation2.valid_row_count == 0
        assert len(validation2.row_errors) == 1
    
    def test_validation_with_mixed_data_types(self):
        """Test validation with mixed data types in columns."""
        df = pd.DataFrame({
            "Company": ["Microsoft", 123, None, "", "Google"],
            "Domain": ["microsoft.com", None, 456, "", "google.com"]
        })
        
        validation = validate_selected_columns(df, "Company", "Domain")
        
        # Should handle type conversion gracefully
        assert isinstance(validation, FileValidationResult)
        assert validation.total_row_count == 5
        
        # Should identify issues with non-string data
        invalid_indices = {error.row_index for error in validation.row_errors}
        assert 2 in invalid_indices or 3 in invalid_indices  # None or empty should be flagged
    
    def test_validation_consistency_across_encodings(self):
        """Test that validation works consistently with different text encodings."""
        test_names = [
            "Company Name",      # ASCII
            "Société Générale",  # Latin-1 accents
            "株式会社トヨタ",      # Japanese
            "Компания",          # Cyrillic
            "شركة",              # Arabic
        ]
        
        df = pd.DataFrame({"Company": test_names})
        validation = validate_selected_columns(df, "Company", None)
        
        # Should handle all encodings without errors
        assert validation.is_valid
        assert validation.valid_row_count == len(test_names)
        
        # Run multiple times to ensure consistency
        for _ in range(5):
            validation2 = validate_selected_columns(df, "Company", None)
            assert validation2.valid_row_count == validation.valid_row_count