"""
Unit tests for data transfer objects (DTOs) and entity classes.

This module tests the validation logic and behavior of all DTOs
to ensure data integrity and proper error handling.
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

import pytest
from datetime import datetime, timedelta
from typing import List

from src.models.entities import CompanyRecord, ResearchResult, ProcessingSession, UserSession


class TestCompanyRecord:
    """Test cases for CompanyRecord DTO validation."""

    def test_valid_company_record(self):
        """Test creation of a valid company record."""
        record = CompanyRecord(
            name="Test Company",
            domain="test.com",
            normalized_key="testcompany",
            row_index=0
        )
        assert record.name == "Test Company"
        assert record.domain == "test.com"
        assert record.normalized_key == "testcompany"
        assert record.row_index == 0

    def test_empty_name_raises_error(self):
        """Test that empty company name raises ValueError."""
        with pytest.raises(ValueError, match="Company name cannot be empty"):
            CompanyRecord(
                name="",
                domain="test.com",
                normalized_key="testcompany",
                row_index=0
            )

    def test_whitespace_name_raises_error(self):
        """Test that whitespace-only company name raises ValueError."""
        with pytest.raises(ValueError, match="Company name cannot be empty"):
            CompanyRecord(
                name="   ",
                domain="test.com",
                normalized_key="testcompany",
                row_index=0
            )

    def test_none_domain_allowed(self):
        """Test that None domain is allowed."""
        record = CompanyRecord(
            name="Test Company",
            domain=None,
            normalized_key="testcompany",
            row_index=0
        )
        assert record.domain is None

    def test_empty_normalized_key_raises_error(self):
        """Test that empty normalized key raises ValueError."""
        with pytest.raises(ValueError, match="Normalized key cannot be empty"):
            CompanyRecord(
                name="Test Company",
                domain="test.com",
                normalized_key="",
                row_index=0
            )

    def test_negative_row_index_raises_error(self):
        """Test that negative row index raises ValueError."""
        with pytest.raises(ValueError, match="Row index must be non-negative"):
            CompanyRecord(
                name="Test Company",
                domain="test.com",
                normalized_key="testcompany",
                row_index=-1
            )


class TestResearchResult:
    """Test cases for ResearchResult DTO validation."""

    def test_valid_research_result(self):
        """Test creation of a valid research result."""
        result = ResearchResult(
            company_name="Test Company",
            company_domain="test.com",
            gcc_presence=True,
            gcc_location="Bangalore",
            suitability_score=8,
            business_pain_points=["High costs", "Talent shortage"],
            expansion_indicators=["Growing revenue", "New markets"],
            hiring_signals=["Active job postings"],
            research_summary="Strong GCC candidate with existing presence",
            is_cached=False,
            created_at=datetime.utcnow()
        )
        assert result.suitability_score == 8
        assert result.gcc_presence is True
        assert len(result.business_pain_points) == 2

    def test_score_boundary_validation(self):
        """Test suitability score boundary validation."""
        # Test minimum valid score
        result = ResearchResult(
            company_name="Test Company",
            company_domain=None,
            gcc_presence=False,
            gcc_location=None,
            suitability_score=1,
            business_pain_points=[],
            expansion_indicators=[],
            hiring_signals=[],
            research_summary="Test summary",
            is_cached=False,
            created_at=datetime.utcnow()
        )
        assert result.suitability_score == 1

        # Test maximum valid score
        result = ResearchResult(
            company_name="Test Company",
            company_domain=None,
            gcc_presence=False,
            gcc_location=None,
            suitability_score=10,
            business_pain_points=[],
            expansion_indicators=[],
            hiring_signals=[],
            research_summary="Test summary",
            is_cached=False,
            created_at=datetime.utcnow()
        )
        assert result.suitability_score == 10

    def test_invalid_score_below_minimum(self):
        """Test that score below 1 raises ValueError."""
        with pytest.raises(ValueError, match="Suitability score must be between 1 and 10"):
            ResearchResult(
                company_name="Test Company",
                company_domain=None,
                gcc_presence=False,
                gcc_location=None,
                suitability_score=0,
                business_pain_points=[],
                expansion_indicators=[],
                hiring_signals=[],
                research_summary="Test summary",
                is_cached=False,
                created_at=datetime.utcnow()
            )

    def test_invalid_score_above_maximum(self):
        """Test that score above 10 raises ValueError."""
        with pytest.raises(ValueError, match="Suitability score must be between 1 and 10"):
            ResearchResult(
                company_name="Test Company",
                company_domain=None,
                gcc_presence=False,
                gcc_location=None,
                suitability_score=11,
                business_pain_points=[],
                expansion_indicators=[],
                hiring_signals=[],
                research_summary="Test summary",
                is_cached=False,
                created_at=datetime.utcnow()
            )

    def test_empty_company_name_raises_error(self):
        """Test that empty company name raises ValueError."""
        with pytest.raises(ValueError, match="Company name cannot be empty"):
            ResearchResult(
                company_name="",
                company_domain=None,
                gcc_presence=False,
                gcc_location=None,
                suitability_score=5,
                business_pain_points=[],
                expansion_indicators=[],
                hiring_signals=[],
                research_summary="Test summary",
                is_cached=False,
                created_at=datetime.utcnow()
            )

    def test_empty_research_summary_raises_error(self):
        """Test that empty research summary raises ValueError."""
        with pytest.raises(ValueError, match="Research summary cannot be empty"):
            ResearchResult(
                company_name="Test Company",
                company_domain=None,
                gcc_presence=False,
                gcc_location=None,
                suitability_score=5,
                business_pain_points=[],
                expansion_indicators=[],
                hiring_signals=[],
                research_summary="",
                is_cached=False,
                created_at=datetime.utcnow()
            )

    def test_none_lists_converted_to_empty(self):
        """Test that None lists are converted to empty lists."""
        result = ResearchResult(
            company_name="Test Company",
            company_domain=None,
            gcc_presence=False,
            gcc_location=None,
            suitability_score=5,
            business_pain_points=None,
            expansion_indicators=None,
            hiring_signals=None,
            research_summary="Test summary",
            is_cached=False,
            created_at=datetime.utcnow()
        )
        assert result.business_pain_points == []
        assert result.expansion_indicators == []
        assert result.hiring_signals == []


class TestProcessingSession:
    """Test cases for ProcessingSession DTO validation."""

    def test_valid_processing_session(self):
        """Test creation of a valid processing session."""
        session = ProcessingSession(
            session_id="test-session-123",
            total_companies=100,
            processed_companies=25,
            cache_hits=10,
            errors=2,
            status="running"
        )
        assert session.session_id == "test-session-123"
        assert session.total_companies == 100
        assert session.processed_companies == 25
        assert session.progress_percentage == 25.0
        assert session.cache_hit_rate == 40.0
        assert not session.is_completed()

    def test_default_values(self):
        """Test default values are set correctly."""
        session = ProcessingSession(
            session_id="test-session",
            total_companies=10
        )
        assert session.processed_companies == 0
        assert session.cache_hits == 0
        assert session.errors == 0
        assert session.status == "running"
        assert session.created_at is not None
        assert session.completed_at is None

    def test_negative_total_companies_raises_error(self):
        """Test that negative total companies raises ValueError."""
        with pytest.raises(ValueError, match="Total companies must be non-negative"):
            ProcessingSession(
                session_id="test-session",
                total_companies=-1
            )

    def test_processed_exceeds_total_raises_error(self):
        """Test that processed exceeding total raises ValueError."""
        with pytest.raises(ValueError, match="Processed companies cannot exceed total companies"):
            ProcessingSession(
                session_id="test-session",
                total_companies=10,
                processed_companies=15
            )

    def test_invalid_status_raises_error(self):
        """Test that invalid status raises ValueError."""
        with pytest.raises(ValueError, match="Status must be one of"):
            ProcessingSession(
                session_id="test-session",
                total_companies=10,
                status="invalid_status"
            )

    def test_empty_session_id_raises_error(self):
        """Test that empty session ID raises ValueError."""
        with pytest.raises(ValueError, match="Session ID cannot be empty"):
            ProcessingSession(
                session_id="",
                total_companies=10
            )

    def test_completion_status_detection(self):
        """Test is_completed method for various statuses."""
        # Running session
        session = ProcessingSession(
            session_id="test-session",
            total_companies=10,
            status="running"
        )
        assert not session.is_completed()

        # Completed session
        session.status = "completed"
        assert session.is_completed()

        # Stopped session
        session.status = "stopped"
        assert session.is_completed()

        # Error session
        session.status = "error"
        assert session.is_completed()

    def test_progress_calculation_edge_cases(self):
        """Test progress calculation with edge cases."""
        # Zero total companies
        session = ProcessingSession(
            session_id="test-session",
            total_companies=0
        )
        assert session.progress_percentage == 100.0

        # Zero processed companies
        session = ProcessingSession(
            session_id="test-session",
            total_companies=10,
            processed_companies=0
        )
        assert session.cache_hit_rate == 0.0


class TestUserSession:
    """Test cases for UserSession DTO validation."""

    def test_valid_user_session(self):
        """Test creation of a valid user session."""
        now = datetime.utcnow()
        expires = now + timedelta(hours=24)

        session = UserSession(
            user_id=123,
            session_token="secure-token-abc123",
            created_at=now,
            expires_at=expires
        )
        assert session.user_id == 123
        assert session.session_token == "secure-token-abc123"
        assert session.is_active is True
        assert session.last_activity == now
        assert session.is_valid()
        assert not session.is_expired()

    def test_empty_session_token_raises_error(self):
        """Test that empty session token raises ValueError."""
        now = datetime.utcnow()
        expires = now + timedelta(hours=24)

        with pytest.raises(ValueError, match="Session token cannot be empty"):
            UserSession(
                user_id=123,
                session_token="",
                created_at=now,
                expires_at=expires
            )

    def test_invalid_user_id_raises_error(self):
        """Test that invalid user ID raises ValueError."""
        now = datetime.utcnow()
        expires = now + timedelta(hours=24)

        with pytest.raises(ValueError, match="User ID must be positive"):
            UserSession(
                user_id=0,
                session_token="secure-token",
                created_at=now,
                expires_at=expires
            )

    def test_invalid_expiration_raises_error(self):
        """Test that expiration before creation raises ValueError."""
        now = datetime.utcnow()
        past = now - timedelta(hours=1)

        with pytest.raises(ValueError, match="Expiration time must be after creation time"):
            UserSession(
                user_id=123,
                session_token="secure-token",
                created_at=now,
                expires_at=past
            )

    def test_expired_session(self):
        """Test expired session detection."""
        now = datetime.utcnow()
        past = now - timedelta(hours=1)

        session = UserSession(
            user_id=123,
            session_token="secure-token",
            created_at=past,
            expires_at=now - timedelta(minutes=1)  # Expired 1 minute ago
        )
        assert session.is_expired()
        assert not session.is_valid()

    def test_inactive_session(self):
        """Test inactive session detection."""
        now = datetime.utcnow()
        expires = now + timedelta(hours=24)

        session = UserSession(
            user_id=123,
            session_token="secure-token",
            created_at=now,
            expires_at=expires,
            is_active=False
        )
        assert not session.is_expired()
        assert not session.is_valid()  # Invalid because inactive
