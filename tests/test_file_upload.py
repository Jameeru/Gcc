"""
Unit tests for the enhanced CSV validation functionality.

Tests the comprehensive validation features added in task 6.3:
- Enhanced error messages
- File format and encoding support  
- Comprehensive data validation

**Validates: Requirements 2.4, 2.5, 14.1, 14.2**
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

import pandas as pd
import pytest

from src.utils.validation import FileValidationResult, RowValidationError, validate_selected_columns


class TestEnhancedValidation:
    """Test the enhanced validation functionality for task 6.3."""

    def test_validates_basic_data_successfully(self):
        """Test successful validation of clean data."""
        df = pd.DataFrame({"Company": ["Acme Inc", "Beta Corp"], "Website": ["acme.com", "beta.com"]})
        validation = validate_selected_columns(df, "Company", "Website")

        assert validation.is_valid
        assert validation.valid_row_count == 2
        assert validation.total_row_count == 2
        assert len(validation.errors) == 0

    def test_detects_empty_company_names_with_enhanced_errors(self):
        """Test detection of empty company names with detailed error info."""
        df = pd.DataFrame({"Company": ["Acme Inc", "", "Gamma LLC"]})
        validation = validate_selected_columns(df, "Company", None)

        assert validation.valid_row_count == 2
        assert len(validation.row_errors) == 1
        
        # Check enhanced error details
        error = validation.row_errors[0]
        assert error.row_index == 1
        assert error.error_type == "EMPTY_NAME"
        assert "empty" in error.message.lower()

    def test_validates_domain_data_quality(self):
        """Test that domain validation detects quality issues."""
        df = pd.DataFrame({
            "Company": ["Acme Inc", "Beta Corp"],
            "Website": ["acme.com", "192.168.1.1"]  # IP address should be flagged
        })
        validation = validate_selected_columns(df, "Company", "Website")

        assert validation.is_valid  # Still valid but with quality issues
        assert validation.has_quality_issues
        assert len(validation.quality_issues) > 0

    def test_detects_test_data_quality_issues(self):
        """Test detection of test/example data."""
        df = pd.DataFrame({
            "Company": ["Real Company", "Test Company Inc"],
            "Website": ["real.com", "example.com"]
        })
        validation = validate_selected_columns(df, "Company", "Website")

        # Should detect quality issues with test data
        assert validation.has_quality_issues
        test_issues = [issue for issue in validation.quality_issues if issue.issue_type in ["TEST_DATA", "SUSPICIOUS_DOMAIN"]]
        assert len(test_issues) > 0

    def test_missing_column_generates_clear_error(self):
        """Test enhanced error message for missing columns."""
        df = pd.DataFrame({"Company_Name": ["Acme Inc"]})  # Wrong column name
        validation = validate_selected_columns(df, "Company", None)

        assert not validation.is_valid
        assert validation.has_critical_errors
        assert len(validation.errors) > 0
        assert "not found" in validation.errors[0]
        assert "Available columns:" in validation.errors[0]

    def test_high_error_rate_generates_warnings(self):
        """Test that high error rates generate appropriate warnings."""
        df = pd.DataFrame({
            "Company": ["", "", "", "Valid Company", ""]  # 80% error rate
        })
        validation = validate_selected_columns(df, "Company", None)

        assert len(validation.warnings) > 0
        assert any("high error rate" in warning.lower() for warning in validation.warnings)

    def test_validation_summary_methods(self):
        """Test that validation result provides comprehensive summary."""
        df = pd.DataFrame({
            "Company": ["Acme Inc", "", "Test Company"],
            "Website": ["acme.com", "beta.com", "example.com"]
        })
        validation = validate_selected_columns(df, "Company", "Website")

        # Test summary methods
        summary = validation.get_summary()
        assert isinstance(summary, dict)
        assert "total_rows" in summary
        assert "valid_rows" in summary
        assert "error_rate" in summary

        # Test error rate calculation
        expected_error_rate = (1 / 3) * 100  # 1 out of 3 rows has error
        assert abs(validation.error_rate - expected_error_rate) < 0.1

    def test_enhanced_file_validation_result_properties(self):
        """Test enhanced FileValidationResult properties."""
        validation = FileValidationResult(
            is_valid=True,
            total_row_count=100,
            valid_row_count=90,
            row_errors=[RowValidationError(0, "test", "TEST")],
            file_size_mb=2.5,
            encoding_used="utf-8"
        )

        assert not validation.has_critical_errors  # Has valid rows
        assert validation.error_rate == 1.0  # 1 error out of 100 rows
        assert validation.file_size_mb == 2.5
        assert validation.encoding_used == "utf-8"

    def test_comprehensive_data_validation_numeric_only_rejection(self):
        """Test that numeric-only company names are rejected."""
        df = pd.DataFrame({
            "Company": ["Acme Inc", "12345", "Beta Corp"]
        })
        validation = validate_selected_columns(df, "Company", None)

        # Should have 2 valid rows, 1 error
        assert validation.valid_row_count == 2
        assert len(validation.row_errors) == 1
        
        # Check that the numeric-only error is properly classified
        error = validation.row_errors[0]
        assert error.error_type == "NUMERIC_ONLY_NAME"
        assert "numbers" in error.message.lower()

    def test_handles_unicode_and_special_characters(self):
        """Test handling of Unicode and special characters in company names."""
        df = pd.DataFrame({
            "Company": ["Café München", "Señor López & Co", "正常公司"]
        })
        validation = validate_selected_columns(df, "Company", None)

        # Unicode company names should be valid
        assert validation.valid_row_count == 3
        assert validation.is_valid
