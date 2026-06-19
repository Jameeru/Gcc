"""
Unit tests for SQLAlchemy database models and data entities.

Tests the User, ResearchResult, and ProcessingSession models including
constraints, relationships, and data validation.
Also tests the data transfer objects (DTOs) for validation logic.
"""

import pytest
import json
import pickle
from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, DateTime, CheckConstraint
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import func

# Import the data entities for testing
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from src.models.entities import CompanyRecord, ResearchResult, ProcessingSession, UserSession

# Create test-specific models that work with SQLite
TestBase = declarative_base()


class TestUser(TestBase):
    """Test version of User model compatible with SQLite."""
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    passcode = Column(String(255), unique=True, nullable=False)
    created_at = Column(DateTime, nullable=False, default=func.now())
    last_login = Column(DateTime, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)


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
    research_metadata = Column(Text, nullable=True)  # JSON stored as text
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now())
    
    __table_args__ = (
        CheckConstraint(
            'suitability_score IS NULL OR (suitability_score >= 1 AND suitability_score <= 10)',
            name='ck_research_results_suitability_score'
        ),
    )


class TestProcessingSession(TestBase):
    """Test version of ProcessingSession model compatible with SQLite."""
    __tablename__ = 'processing_sessions'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(255), nullable=False)
    total_companies = Column(Integer, nullable=False)
    processed_companies = Column(Integer, nullable=False, default=0)
    cache_hits = Column(Integer, nullable=False, default=0)
    errors = Column(Integer, nullable=False, default=0)
    status = Column(String(50), nullable=False, default='running')
    created_at = Column(DateTime, nullable=False, default=func.now())
    completed_at = Column(DateTime, nullable=True)
    
    @property
    def completion_percentage(self) -> float:
        """Calculate completion percentage for progress tracking."""
        if self.total_companies == 0:
            return 0.0
        return (self.processed_companies / self.total_companies) * 100.0
    
    @property
    def cache_hit_rate(self) -> float:
        """Calculate cache hit rate as percentage."""
        if self.processed_companies == 0:
            return 0.0
        return (self.cache_hits / self.processed_companies) * 100.0
    
    __table_args__ = (
        CheckConstraint('total_companies >= 0', name='ck_processing_sessions_total_companies'),
        CheckConstraint('processed_companies >= 0', name='ck_processing_sessions_processed_companies'),
        CheckConstraint('cache_hits >= 0', name='ck_processing_sessions_cache_hits'),
        CheckConstraint('errors >= 0', name='ck_processing_sessions_errors'),
        CheckConstraint(
            'processed_companies <= total_companies', 
            name='ck_processing_sessions_processed_le_total'
        ),
    )


@pytest.fixture
def engine():
    """Create in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    TestBase.metadata.create_all(engine)
    return engine


@pytest.fixture
def session(engine):
    """Create database session for testing."""
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


class TestUserModel:
    """Test cases for User model."""
    
    def test_create_user(self, session):
        """Test creating a new user."""
        user = TestUser(passcode="test_passcode_123")
        session.add(user)
        session.commit()
        
        assert user.id is not None
        assert user.passcode == "test_passcode_123"
        assert user.is_active is True
        assert user.created_at is not None
        assert user.last_login is None
    
    def test_user_unique_passcode_constraint(self, session):
        """Test that passcode must be unique."""
        user1 = TestUser(passcode="duplicate_passcode")
        user2 = TestUser(passcode="duplicate_passcode")
        
        session.add(user1)
        session.commit()
        
        session.add(user2)
        with pytest.raises(IntegrityError):
            session.commit()


class TestResearchResultModel:
    """Test cases for ResearchResult model."""
    
    def test_create_research_result(self, session):
        """Test creating a new research result."""
        result = TestResearchResult(
            normalized_key="testcorp_test.com",
            company_name="TestCorp",
            company_domain="test.com",
            gcc_presence=True,
            gcc_location="Bangalore, India",
            suitability_score=8,
            business_pain_points="High development costs",
            expansion_indicators="Recent funding",
            hiring_signals="100+ open positions",
            research_summary="Strong GCC candidate"
        )
        
        session.add(result)
        session.commit()
        
        assert result.id is not None
        assert result.normalized_key == "testcorp_test.com"
        assert result.suitability_score == 8
        assert result.created_at is not None
        assert result.updated_at is not None
    
    def test_suitability_score_constraint(self, session):
        """Test suitability score constraint (1-10)."""
        # Valid score
        result1 = TestResearchResult(
            normalized_key="valid_score",
            company_name="ValidCorp",
            suitability_score=5
        )
        session.add(result1)
        session.commit()  # Should succeed
        
        # Invalid score - too low
        result2 = TestResearchResult(
            normalized_key="invalid_low",
            company_name="InvalidLow",
            suitability_score=0
        )
        session.add(result2)
        with pytest.raises(IntegrityError):
            session.commit()
        
        session.rollback()
        
        # Invalid score - too high
        result3 = TestResearchResult(
            normalized_key="invalid_high",
            company_name="InvalidHigh",
            suitability_score=11
        )
        session.add(result3)
        with pytest.raises(IntegrityError):
            session.commit()
    
    def test_unique_normalized_key_constraint(self, session):
        """Test that normalized_key must be unique."""
        result1 = TestResearchResult(
            normalized_key="duplicate_key",
            company_name="Company1"
        )
        result2 = TestResearchResult(
            normalized_key="duplicate_key",
            company_name="Company2"
        )
        
        session.add(result1)
        session.commit()
        
        session.add(result2)
        with pytest.raises(IntegrityError):
            session.commit()


class TestProcessingSessionModel:
    """Test cases for ProcessingSession model."""
    
    def test_create_processing_session(self, session):
        """Test creating a new processing session."""
        ps = TestProcessingSession(
            session_id="test_session_123",
            total_companies=100,
            processed_companies=25,
            cache_hits=10,
            errors=1,
            status="running"
        )
        
        session.add(ps)
        session.commit()
        
        assert ps.id is not None
        assert ps.session_id == "test_session_123"
        assert ps.total_companies == 100
        assert ps.processed_companies == 25
        assert ps.completion_percentage == 25.0
        assert ps.cache_hit_rate == 40.0  # 10/25 * 100
        assert ps.status == "running"
        assert ps.created_at is not None
        assert ps.completed_at is None
    
    def test_processing_session_constraints(self, session):
        """Test processing session constraints."""
        # Valid session
        ps1 = TestProcessingSession(
            session_id="valid_session",
            total_companies=10,
            processed_companies=5
        )
        session.add(ps1)
        session.commit()  # Should succeed
        
        # Invalid: processed > total
        ps2 = TestProcessingSession(
            session_id="invalid_session",
            total_companies=10,
            processed_companies=15
        )
        session.add(ps2)
        with pytest.raises(IntegrityError):
            session.commit()


class TestModelProperties:
    """Test model properties and computed fields."""
    
    def test_processing_session_completion_percentage(self, session):
        """Test completion percentage calculation."""
        ps = TestProcessingSession(
            session_id="percentage_test",
            total_companies=0,
            processed_companies=0
        )
        assert ps.completion_percentage == 0.0
        
        ps.total_companies = 100
        ps.processed_companies = 25
        assert ps.completion_percentage == 25.0
        
        ps.processed_companies = 100
        assert ps.completion_percentage == 100.0
    
    def test_processing_session_cache_hit_rate(self, session):
        """Test cache hit rate calculation."""
        ps = TestProcessingSession(
            session_id="cache_test",
            total_companies=100,
            processed_companies=0,
            cache_hits=0
        )
        assert ps.cache_hit_rate == 0.0
        
        ps.processed_companies = 50
        ps.cache_hits = 25
        assert ps.cache_hit_rate == 50.0
        
        ps.cache_hits = 50
        assert ps.cache_hit_rate == 100.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ===================================================================
# DATA ENTITY VALIDATION TESTS
# ===================================================================

class TestCompanyRecordValidation:
    """
    Unit tests for CompanyRecord data validation.
    
    Tests the validation logic for company record data including
    empty names, normalized keys, and row indices.
    
    **Validates: Requirements 5.3, 14.4**
    """
    
    def test_valid_company_record_creation(self):
        """Test creating a valid CompanyRecord."""
        record = CompanyRecord(
            name="Test Company Inc.",
            domain="testcompany.com",
            normalized_key="testcompanyinc_testcompany.com",
            row_index=0
        )
        
        assert record.name == "Test Company Inc."
        assert record.domain == "testcompany.com"
        assert record.normalized_key == "testcompanyinc_testcompany.com"
        assert record.row_index == 0
    
    def test_company_record_with_empty_name_raises_error(self):
        """Test that CompanyRecord with empty name raises ValueError."""
        with pytest.raises(ValueError, match="Company name cannot be empty"):
            CompanyRecord(
                name="",
                domain="testcompany.com",
                normalized_key="testcompany.com",
                row_index=0
            )
    
    def test_company_record_with_whitespace_only_name_raises_error(self):
        """Test that CompanyRecord with whitespace-only name raises ValueError."""
        with pytest.raises(ValueError, match="Company name cannot be empty"):
            CompanyRecord(
                name="   \t\n  ",
                domain="testcompany.com",
                normalized_key="testcompany.com",
                row_index=0
            )
    
    def test_company_record_with_none_name_raises_error(self):
        """Test that CompanyRecord with None name raises ValueError."""
        with pytest.raises(ValueError, match="Company name cannot be empty"):
            CompanyRecord(
                name=None,
                domain="testcompany.com",
                normalized_key="testcompany.com",
                row_index=0
            )
    
    def test_company_record_with_empty_normalized_key_raises_error(self):
        """Test that CompanyRecord with empty normalized_key raises ValueError."""
        with pytest.raises(ValueError, match="Normalized key cannot be empty"):
            CompanyRecord(
                name="Test Company",
                domain="testcompany.com",
                normalized_key="",
                row_index=0
            )
    
    def test_company_record_with_negative_row_index_raises_error(self):
        """Test that CompanyRecord with negative row_index raises ValueError."""
        with pytest.raises(ValueError, match="Row index must be non-negative"):
            CompanyRecord(
                name="Test Company",
                domain="testcompany.com",
                normalized_key="testcompany_testcompany.com",
                row_index=-1
            )
    
    def test_company_record_with_none_domain_is_valid(self):
        """Test that CompanyRecord with None domain is valid."""
        record = CompanyRecord(
            name="Test Company",
            domain=None,
            normalized_key="testcompany",
            row_index=0
        )
        
        assert record.name == "Test Company"
        assert record.domain is None
        assert record.normalized_key == "testcompany"
        assert record.row_index == 0
    
    def test_company_record_serialization_deserialization(self):
        """Test CompanyRecord can be serialized and deserialized."""
        original_record = CompanyRecord(
            name="Test Company Inc.",
            domain="testcompany.com",
            normalized_key="testcompanyinc_testcompany.com",
            row_index=5
        )
        
        # Test pickle serialization/deserialization
        pickled_data = pickle.dumps(original_record)
        deserialized_record = pickle.loads(pickled_data)
        
        assert deserialized_record.name == original_record.name
        assert deserialized_record.domain == original_record.domain
        assert deserialized_record.normalized_key == original_record.normalized_key
        assert deserialized_record.row_index == original_record.row_index


class TestResearchResultValidation:
    """
    Unit tests for ResearchResult data validation.
    
    Tests the validation logic for research result data including
    suitability score boundaries, required fields, and data integrity.
    
    **Validates: Requirements 5.3, 14.4**
    """
    
    def test_valid_research_result_creation(self):
        """Test creating a valid ResearchResult."""
        result = ResearchResult(
            company_name="Test Company Inc.",
            company_domain="testcompany.com",
            gcc_presence=True,
            gcc_location="Bangalore, India",
            suitability_score=8,
            business_pain_points=["High development costs", "Talent shortage"],
            expansion_indicators=["Recent funding round", "New market entry"],
            hiring_signals=["100+ open positions", "Growing engineering team"],
            research_summary="Strong candidate for GCC establishment with existing India presence",
            is_cached=False,
            created_at=datetime.utcnow()
        )
        
        assert result.company_name == "Test Company Inc."
        assert result.suitability_score == 8
        assert result.gcc_presence is True
        assert len(result.business_pain_points) == 2
    
    def test_research_result_suitability_score_boundaries(self):
        """Test ResearchResult suitability score boundary validation."""
        base_data = {
            "company_name": "Test Company",
            "company_domain": "test.com",
            "gcc_presence": False,
            "gcc_location": None,
            "business_pain_points": [],
            "expansion_indicators": [],
            "hiring_signals": [],
            "research_summary": "Test summary",
            "is_cached": False,
            "created_at": datetime.utcnow()
        }
        
        # Test valid scores (1-10)
        for score in range(1, 11):
            result = ResearchResult(suitability_score=score, **base_data)
            assert result.suitability_score == score
        
        # Test invalid scores (below 1)
        with pytest.raises(ValueError, match="Suitability score must be between 1 and 10"):
            ResearchResult(suitability_score=0, **base_data)
        
        with pytest.raises(ValueError, match="Suitability score must be between 1 and 10"):
            ResearchResult(suitability_score=-5, **base_data)
        
        # Test invalid scores (above 10)
        with pytest.raises(ValueError, match="Suitability score must be between 1 and 10"):
            ResearchResult(suitability_score=11, **base_data)
        
        with pytest.raises(ValueError, match="Suitability score must be between 1 and 10"):
            ResearchResult(suitability_score=100, **base_data)
    
    def test_research_result_with_empty_company_name_raises_error(self):
        """Test that ResearchResult with empty company name raises ValueError."""
        with pytest.raises(ValueError, match="Company name cannot be empty"):
            ResearchResult(
                company_name="",
                company_domain="test.com",
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
    
    def test_research_result_with_empty_research_summary_raises_error(self):
        """Test that ResearchResult with empty research summary raises ValueError."""
        with pytest.raises(ValueError, match="Research summary cannot be empty"):
            ResearchResult(
                company_name="Test Company",
                company_domain="test.com",
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
    
    def test_research_result_with_none_lists_converts_to_empty_lists(self):
        """Test that ResearchResult converts None list fields to empty lists."""
        result = ResearchResult(
            company_name="Test Company",
            company_domain="test.com",
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
    
    def test_research_result_serialization_deserialization(self):
        """Test ResearchResult can be serialized and deserialized."""
        original_result = ResearchResult(
            company_name="Test Company Inc.",
            company_domain="testcompany.com",
            gcc_presence=True,
            gcc_location="Bangalore, India",
            suitability_score=8,
            business_pain_points=["High costs", "Talent shortage"],
            expansion_indicators=["Funding", "Growth"],
            hiring_signals=["Open positions"],
            research_summary="Strong GCC candidate",
            is_cached=False,
            created_at=datetime(2024, 1, 15, 10, 30, 0)
        )
        
        # Test pickle serialization/deserialization
        pickled_data = pickle.dumps(original_result)
        deserialized_result = pickle.loads(pickled_data)
        
        assert deserialized_result.company_name == original_result.company_name
        assert deserialized_result.suitability_score == original_result.suitability_score
        assert deserialized_result.business_pain_points == original_result.business_pain_points
        assert deserialized_result.created_at == original_result.created_at
    
    def test_research_result_json_serialization_compatibility(self):
        """Test ResearchResult fields are JSON serializable."""
        result = ResearchResult(
            company_name="Test Company Inc.",
            company_domain="testcompany.com",
            gcc_presence=True,
            gcc_location="Bangalore, India",
            suitability_score=8,
            business_pain_points=["High development costs"],
            expansion_indicators=["Recent funding"],
            hiring_signals=["100+ positions"],
            research_summary="Strong GCC candidate",
            is_cached=False,
            created_at=datetime(2024, 1, 15, 10, 30, 0)
        )
        
        # Test that we can convert to dict and serialize key fields
        result_dict = {
            "company_name": result.company_name,
            "company_domain": result.company_domain,
            "gcc_presence": result.gcc_presence,
            "gcc_location": result.gcc_location,
            "suitability_score": result.suitability_score,
            "business_pain_points": result.business_pain_points,
            "expansion_indicators": result.expansion_indicators,
            "hiring_signals": result.hiring_signals,
            "research_summary": result.research_summary,
            "is_cached": result.is_cached,
            "created_at": result.created_at.isoformat()
        }
        
        # Should not raise an exception
        json_str = json.dumps(result_dict)
        parsed_dict = json.loads(json_str)
        
        assert parsed_dict["company_name"] == result.company_name
        assert parsed_dict["suitability_score"] == result.suitability_score
        assert parsed_dict["gcc_presence"] == result.gcc_presence


class TestProcessingSessionValidation:
    """
    Unit tests for ProcessingSession data validation.
    
    Tests the validation logic for processing session data including
    count constraints and progress calculations.
    
    **Validates: Requirements 6.2, 6.5**
    """
    
    def test_valid_processing_session_creation(self):
        """Test creating a valid ProcessingSession."""
        session = ProcessingSession(
            session_id="test_session_123",
            total_companies=100,
            processed_companies=25,
            cache_hits=10,
            errors=2,
            status="running"
        )
        
        assert session.session_id == "test_session_123"
        assert session.total_companies == 100
        assert session.processed_companies == 25
        assert session.progress_percentage == 25.0
        assert session.cache_hit_rate == 40.0  # 10/25 * 100
    
    def test_processing_session_count_validation(self):
        """Test ProcessingSession count validation constraints."""
        # Valid session
        session = ProcessingSession(
            session_id="valid_session",
            total_companies=10,
            processed_companies=5,
            cache_hits=2,
            errors=1
        )
        assert session.processed_companies == 5
        
        # Invalid: negative total_companies
        with pytest.raises(ValueError, match="Total companies must be non-negative"):
            ProcessingSession(
                session_id="invalid_session",
                total_companies=-1,
                processed_companies=0
            )
        
        # Invalid: negative processed_companies
        with pytest.raises(ValueError, match="Processed companies must be non-negative"):
            ProcessingSession(
                session_id="invalid_session",
                total_companies=10,
                processed_companies=-1
            )
        
        # Invalid: processed > total
        with pytest.raises(ValueError, match="Processed companies cannot exceed total companies"):
            ProcessingSession(
                session_id="invalid_session",
                total_companies=10,
                processed_companies=15
            )
    
    def test_processing_session_status_validation(self):
        """Test ProcessingSession status validation."""
        valid_statuses = ['running', 'stopped', 'completed', 'error']
        
        # Test valid statuses
        for status in valid_statuses:
            session = ProcessingSession(
                session_id=f"test_{status}",
                total_companies=10,
                status=status
            )
            assert session.status == status
        
        # Test invalid status
        with pytest.raises(ValueError, match="Status must be one of"):
            ProcessingSession(
                session_id="invalid_status",
                total_companies=10,
                status="invalid_status"
            )
    
    def test_processing_session_progress_calculations(self):
        """Test ProcessingSession progress and cache rate calculations."""
        # Test zero companies case
        session = ProcessingSession(
            session_id="zero_companies",
            total_companies=0,
            processed_companies=0
        )
        assert session.progress_percentage == 100.0
        assert session.cache_hit_rate == 0.0
        
        # Test partial progress
        session = ProcessingSession(
            session_id="partial_progress",
            total_companies=100,
            processed_companies=30,
            cache_hits=15
        )
        assert session.progress_percentage == 30.0
        assert session.cache_hit_rate == 50.0
        
        # Test completed session
        session = ProcessingSession(
            session_id="completed",
            total_companies=50,
            processed_companies=50,
            cache_hits=20
        )
        assert session.progress_percentage == 100.0
        assert session.cache_hit_rate == 40.0
    
    def test_processing_session_completion_status(self):
        """Test ProcessingSession completion status methods."""
        # Running session
        running_session = ProcessingSession(
            session_id="running",
            total_companies=10,
            status="running"
        )
        assert not running_session.is_completed()
        
        # Completed sessions
        for status in ['completed', 'stopped', 'error']:
            session = ProcessingSession(
                session_id=f"test_{status}",
                total_companies=10,
                status=status
            )
            assert session.is_completed()


class TestUserSessionValidation:
    """
    Unit tests for UserSession data validation.
    
    Tests the validation logic for user session data including
    token validation and expiration handling.
    
    **Validates: Requirements 1.1, 1.4, 1.5**
    """
    
    def test_valid_user_session_creation(self):
        """Test creating a valid UserSession."""
        created_at = datetime.utcnow()
        expires_at = datetime.utcnow().replace(hour=23, minute=59, second=59)
        
        session = UserSession(
            user_id=1,
            session_token="secure_token_123",
            created_at=created_at,
            expires_at=expires_at
        )
        
        assert session.user_id == 1
        assert session.session_token == "secure_token_123"
        assert session.is_active is True
        assert session.last_activity == created_at
    
    def test_user_session_token_validation(self):
        """Test UserSession token validation."""
        created_at = datetime.utcnow()
        expires_at = datetime.utcnow().replace(hour=23, minute=59, second=59)
        
        # Valid token
        session = UserSession(
            user_id=1,
            session_token="valid_token",
            created_at=created_at,
            expires_at=expires_at
        )
        assert session.session_token == "valid_token"
        
        # Empty token
        with pytest.raises(ValueError, match="Session token cannot be empty"):
            UserSession(
                user_id=1,
                session_token="",
                created_at=created_at,
                expires_at=expires_at
            )
        
        # Whitespace-only token
        with pytest.raises(ValueError, match="Session token cannot be empty"):
            UserSession(
                user_id=1,
                session_token="   ",
                created_at=created_at,
                expires_at=expires_at
            )
    
    def test_user_session_time_validation(self):
        """Test UserSession time validation."""
        created_at = datetime.utcnow()
        
        # Valid expiration (after creation)
        expires_at = created_at.replace(hour=23, minute=59, second=59)
        session = UserSession(
            user_id=1,
            session_token="valid_token",
            created_at=created_at,
            expires_at=expires_at
        )
        assert session.expires_at > session.created_at
        
        # Invalid expiration (before creation)
        invalid_expires_at = created_at.replace(hour=0, minute=0, second=0)
        with pytest.raises(ValueError, match="Expiration time must be after creation time"):
            UserSession(
                user_id=1,
                session_token="valid_token",
                created_at=created_at,
                expires_at=invalid_expires_at
            )
    
    def test_user_session_expiration_checking(self):
        """Test UserSession expiration checking methods."""
        # Create session that expires in the future
        created_at = datetime.utcnow()
        future_expires = created_at.replace(year=created_at.year + 1)
        
        future_session = UserSession(
            user_id=1,
            session_token="future_token",
            created_at=created_at,
            expires_at=future_expires
        )
        
        assert not future_session.is_expired()
        assert future_session.is_valid()
        
        # Create session that expired in the past
        past_expires = created_at.replace(year=created_at.year - 1)
        
        past_session = UserSession(
            user_id=1,
            session_token="past_token",
            created_at=created_at.replace(year=created_at.year - 2),
            expires_at=past_expires
        )
        
        assert past_session.is_expired()
        assert not past_session.is_valid()
        
        # Create inactive session
        inactive_session = UserSession(
            user_id=1,
            session_token="inactive_token",
            created_at=created_at,
            expires_at=future_expires,
            is_active=False
        )
        
        assert not inactive_session.is_expired()
        assert not inactive_session.is_valid()  # inactive even though not expired