#!/usr/bin/env python3
"""
Manual validation script for DTOs to test functionality without pytest.
"""

import sys
from datetime import datetime, timedelta
from entities import CompanyRecord, ResearchResult, ProcessingSession, UserSession


def test_company_record():
    """Test CompanyRecord validation."""
    print("Testing CompanyRecord...")
    
    # Valid case
    try:
        record = CompanyRecord(
            name="Test Company",
            domain="test.com",
            normalized_key="testcompany",
            row_index=0
        )
        print("✓ Valid CompanyRecord created successfully")
    except Exception as e:
        print(f"✗ Failed to create valid CompanyRecord: {e}")
        return False
    
    # Empty name case
    try:
        CompanyRecord(
            name="",
            domain="test.com", 
            normalized_key="testcompany",
            row_index=0
        )
        print("✗ Empty name should have raised ValueError")
        return False
    except ValueError as e:
        if "Company name cannot be empty" in str(e):
            print("✓ Empty name validation works")
        else:
            print(f"✗ Wrong error for empty name: {e}")
            return False
    
    # Negative row index
    try:
        CompanyRecord(
            name="Test Company",
            domain="test.com",
            normalized_key="testcompany", 
            row_index=-1
        )
        print("✗ Negative row index should have raised ValueError")
        return False
    except ValueError as e:
        if "Row index must be non-negative" in str(e):
            print("✓ Negative row index validation works")
        else:
            print(f"✗ Wrong error for negative row index: {e}")
            return False
    
    return True


def test_research_result():
    """Test ResearchResult validation."""
    print("\nTesting ResearchResult...")
    
    # Valid case
    try:
        result = ResearchResult(
            company_name="Test Company",
            company_domain="test.com",
            gcc_presence=True,
            gcc_location="Bangalore", 
            suitability_score=8,
            business_pain_points=["High costs"],
            expansion_indicators=["Growth"],
            hiring_signals=["Job postings"],
            research_summary="Good candidate",
            is_cached=False,
            created_at=datetime.utcnow()
        )
        print("✓ Valid ResearchResult created successfully")
    except Exception as e:
        print(f"✗ Failed to create valid ResearchResult: {e}")
        return False
    
    # Invalid score below minimum
    try:
        ResearchResult(
            company_name="Test Company",
            company_domain=None,
            gcc_presence=False,
            gcc_location=None,
            suitability_score=0,
            business_pain_points=[],
            expansion_indicators=[],
            hiring_signals=[],
            research_summary="Test",
            is_cached=False,
            created_at=datetime.utcnow()
        )
        print("✗ Score 0 should have raised ValueError")
        return False
    except ValueError as e:
        if "Suitability score must be between 1 and 10" in str(e):
            print("✓ Score validation (below minimum) works")
        else:
            print(f"✗ Wrong error for score 0: {e}")
            return False
    
    # Invalid score above maximum
    try:
        ResearchResult(
            company_name="Test Company",
            company_domain=None,
            gcc_presence=False,
            gcc_location=None,
            suitability_score=11,
            business_pain_points=[],
            expansion_indicators=[],
            hiring_signals=[],
            research_summary="Test",
            is_cached=False,
            created_at=datetime.utcnow()
        )
        print("✗ Score 11 should have raised ValueError")
        return False
    except ValueError as e:
        if "Suitability score must be between 1 and 10" in str(e):
            print("✓ Score validation (above maximum) works")
        else:
            print(f"✗ Wrong error for score 11: {e}")
            return False
    
    # Test boundary values
    for score in [1, 10]:
        try:
            ResearchResult(
                company_name="Test Company",
                company_domain=None,
                gcc_presence=False,
                gcc_location=None,
                suitability_score=score,
                business_pain_points=[],
                expansion_indicators=[],
                hiring_signals=[],
                research_summary="Test",
                is_cached=False,
                created_at=datetime.utcnow()
            )
            print(f"✓ Boundary score {score} is valid")
        except Exception as e:
            print(f"✗ Boundary score {score} failed: {e}")
            return False
    
    return True


def test_processing_session():
    """Test ProcessingSession validation."""
    print("\nTesting ProcessingSession...")
    
    # Valid case
    try:
        session = ProcessingSession(
            session_id="test-123",
            total_companies=100,
            processed_companies=25,
            cache_hits=10,
            errors=2
        )
        print("✓ Valid ProcessingSession created successfully")
        print(f"  Progress: {session.progress_percentage}%")
        print(f"  Cache hit rate: {session.cache_hit_rate}%")
        print(f"  Is completed: {session.is_completed()}")
    except Exception as e:
        print(f"✗ Failed to create valid ProcessingSession: {e}")
        return False
    
    # Negative total companies
    try:
        ProcessingSession(
            session_id="test-123",
            total_companies=-1
        )
        print("✗ Negative total companies should have raised ValueError")
        return False
    except ValueError as e:
        if "Total companies must be non-negative" in str(e):
            print("✓ Negative total companies validation works")
        else:
            print(f"✗ Wrong error for negative total: {e}")
            return False
    
    # Processed exceeds total
    try:
        ProcessingSession(
            session_id="test-123", 
            total_companies=10,
            processed_companies=15
        )
        print("✗ Processed > total should have raised ValueError")
        return False
    except ValueError as e:
        if "Processed companies cannot exceed total companies" in str(e):
            print("✓ Processed > total validation works")
        else:
            print(f"✗ Wrong error for processed > total: {e}")
            return False
    
    return True


def test_user_session():
    """Test UserSession validation."""
    print("\nTesting UserSession...")
    
    # Valid case
    try:
        now = datetime.utcnow()
        expires = now + timedelta(hours=24)
        session = UserSession(
            user_id=123,
            session_token="secure-token-abc",
            created_at=now,
            expires_at=expires
        )
        print("✓ Valid UserSession created successfully")
        print(f"  Is valid: {session.is_valid()}")
        print(f"  Is expired: {session.is_expired()}")
    except Exception as e:
        print(f"✗ Failed to create valid UserSession: {e}")
        return False
    
    # Empty session token
    try:
        now = datetime.utcnow()
        expires = now + timedelta(hours=24)
        UserSession(
            user_id=123,
            session_token="",
            created_at=now,
            expires_at=expires
        )
        print("✗ Empty session token should have raised ValueError")
        return False
    except ValueError as e:
        if "Session token cannot be empty" in str(e):
            print("✓ Empty session token validation works")
        else:
            print(f"✗ Wrong error for empty token: {e}")
            return False
    
    # Test expired session
    try:
        now = datetime.utcnow()
        past = now - timedelta(hours=1)
        session = UserSession(
            user_id=123,
            session_token="token",
            created_at=past,
            expires_at=now - timedelta(minutes=1)  # Expired 1 minute ago
        )
        if session.is_expired() and not session.is_valid():
            print("✓ Expired session detection works")
        else:
            print("✗ Expired session not detected correctly")
            return False
    except Exception as e:
        print(f"✗ Failed to test expired session: {e}")
        return False
    
    return True


def main():
    """Run all validation tests."""
    print("=== DTO Validation Tests ===")
    
    tests = [
        test_company_record,
        test_research_result, 
        test_processing_session,
        test_user_session
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        if test():
            passed += 1
        else:
            print("❌ Test failed!")
    
    print(f"\n=== Results: {passed}/{total} tests passed ===")
    
    if passed == total:
        print("🎉 All DTO validation tests passed!")
        return True
    else:
        print("❌ Some tests failed!")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)