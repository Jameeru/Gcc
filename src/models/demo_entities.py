#!/usr/bin/env python3
"""
Demonstration script showing the DTOs in action.
This script showcases the main functionality and usage patterns.
"""

from datetime import datetime, timedelta
from entities import CompanyRecord, ResearchResult, ProcessingSession, UserSession


def demo_company_record():
    """Demonstrate CompanyRecord usage."""
    print("=== CompanyRecord Demo ===")
    
    # Create a company record from CSV data
    company = CompanyRecord(
        name="Microsoft Corporation",
        domain="microsoft.com",
        normalized_key="microsoftcorporation",
        row_index=42
    )
    
    print(f"Company: {company.name}")
    print(f"Domain: {company.domain}")
    print(f"Cache Key: {company.normalized_key}")
    print(f"CSV Row: {company.row_index}")
    print()


def demo_research_result():
    """Demonstrate ResearchResult usage."""
    print("=== ResearchResult Demo ===")
    
    # Create a research result from AI analysis
    result = ResearchResult(
        company_name="Microsoft Corporation",
        company_domain="microsoft.com",
        gcc_presence=True,
        gcc_location="Hyderabad, Bangalore",
        suitability_score=9,
        business_pain_points=[
            "High operational costs in developed markets",
            "Need for 24/7 support coverage",
            "Talent acquisition challenges"
        ],
        expansion_indicators=[
            "Growing cloud business in Asia",
            "Increased R&D investments",
            "New product launches"
        ],
        hiring_signals=[
            "500+ open positions in tech roles",
            "Active campus recruiting",
            "Engineering manager positions"
        ],
        research_summary="Microsoft is an excellent GCC candidate with existing presence in India. Strong technical requirements, significant growth trajectory, and active hiring patterns indicate high potential for GCC expansion or enhancement.",
        is_cached=False,
        created_at=datetime.utcnow()
    )
    
    print(f"Company: {result.company_name}")
    print(f"GCC Present: {result.gcc_presence}")
    print(f"Suitability Score: {result.suitability_score}/10")
    print(f"Pain Points: {len(result.business_pain_points)} identified")
    print(f"Expansion Indicators: {len(result.expansion_indicators)} found")
    print(f"Hiring Signals: {len(result.hiring_signals)} detected")
    print(f"Cached: {result.is_cached}")
    print(f"Summary: {result.research_summary[:100]}...")
    print()


def demo_processing_session():
    """Demonstrate ProcessingSession usage."""
    print("=== ProcessingSession Demo ===")
    
    # Create a processing session
    session = ProcessingSession(
        session_id="batch_20241201_143022",
        total_companies=250,
        processed_companies=75,
        cache_hits=30,
        errors=3,
        status="running",
        created_at=datetime.utcnow()
    )
    
    print(f"Session ID: {session.session_id}")
    print(f"Progress: {session.processed_companies}/{session.total_companies} ({session.progress_percentage:.1f}%)")
    print(f"Cache Hit Rate: {session.cache_hit_rate:.1f}%")
    print(f"Errors: {session.errors}")
    print(f"Status: {session.status}")
    print(f"Completed: {session.is_completed()}")
    print()
    
    # Simulate progress updates
    print("Simulating progress updates:")
    for processed in [100, 150, 200, 250]:
        session.processed_companies = min(processed, session.total_companies)
        session.cache_hits = int(session.processed_companies * 0.4)  # 40% cache hit rate
        
        if session.processed_companies == session.total_companies:
            session.status = "completed"
            session.completed_at = datetime.utcnow()
        
        print(f"  Progress: {session.progress_percentage:.1f}% | Cache Rate: {session.cache_hit_rate:.1f}% | Status: {session.status}")


def demo_user_session():
    """Demonstrate UserSession usage."""
    print("\n=== UserSession Demo ===")
    
    # Create a user session
    now = datetime.utcnow()
    session = UserSession(
        user_id=1001,
        session_token="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
        created_at=now,
        expires_at=now + timedelta(hours=8),  # 8-hour session
        is_active=True,
        last_activity=now
    )
    
    print(f"User ID: {session.user_id}")
    print(f"Session Token: {session.session_token[:20]}...")
    print(f"Created: {session.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Expires: {session.expires_at.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Active: {session.is_active}")
    print(f"Valid: {session.is_valid()}")
    print(f"Expired: {session.is_expired()}")
    print()
    
    # Simulate session expiry
    print("Simulating expired session:")
    expired_session = UserSession(
        user_id=1002,
        session_token="expired_token_123",
        created_at=now - timedelta(hours=25),
        expires_at=now - timedelta(hours=1),  # Expired 1 hour ago
        is_active=True
    )
    print(f"  Valid: {expired_session.is_valid()}")
    print(f"  Expired: {expired_session.is_expired()}")


def demo_error_handling():
    """Demonstrate error handling in DTOs."""
    print("\n=== Error Handling Demo ===")
    
    error_cases = [
        ("Empty company name", lambda: CompanyRecord("", "test.com", "key", 0)),
        ("Invalid suitability score", lambda: ResearchResult(
            "Test", None, False, None, 15, [], [], [], "summary", False, datetime.utcnow()
        )),
        ("Negative total companies", lambda: ProcessingSession("test", -5)),
        ("Empty session token", lambda: UserSession(
            123, "", datetime.utcnow(), datetime.utcnow() + timedelta(hours=1)
        ))
    ]
    
    for description, func in error_cases:
        try:
            func()
            print(f"❌ {description}: Should have raised an error!")
        except ValueError as e:
            print(f"✅ {description}: {e}")
        except Exception as e:
            print(f"⚠️  {description}: Unexpected error: {e}")


def main():
    """Run the demonstration."""
    print("🎯 GCC Research Intelligence Platform - Data Transfer Objects Demo")
    print("=" * 70)
    
    demo_company_record()
    demo_research_result()
    demo_processing_session()
    demo_user_session()
    demo_error_handling()
    
    print("\n✅ All DTOs demonstrated successfully!")
    print("\nThese DTOs provide:")
    print("• Type safety with comprehensive validation")
    print("• Clear data contracts between system components")
    print("• Robust error handling for invalid inputs")
    print("• Rich functionality for business logic operations")
    print("• Full compliance with requirements 5.3, 14.1, 14.2, 13.6")


if __name__ == "__main__":
    main()