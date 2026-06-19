# Data Transfer Objects (DTOs) and Entity Classes

This module contains the core data structures for the GCC Research Intelligence Platform, implemented as validated dataclasses with comprehensive type safety and business logic validation.

## Overview

The DTOs provide:
- **Type Safety**: Full type hints and runtime validation
- **Data Integrity**: Comprehensive validation rules for all fields
- **Business Logic**: Built-in methods for common operations
- **Error Handling**: Clear, descriptive error messages for invalid data
- **Requirements Compliance**: Validates requirements 5.3, 14.1, 14.2, 13.6

## Classes

### CompanyRecord

Represents a company record extracted from CSV uploads.

**Key Features:**
- Validates company name is not empty
- Ensures normalized keys for cache consistency  
- Tracks original CSV row position
- Prevents negative row indexes

**Usage:**
```python
company = CompanyRecord(
    name="Microsoft Corporation",
    domain="microsoft.com", 
    normalized_key="microsoftcorporation",
    row_index=42
)
```

### ResearchResult

Contains the complete AI research analysis for a company.

**Key Features:**
- Validates suitability score range (1-10)
- Ensures required fields are not empty
- Handles optional location and domain data
- Converts None lists to empty lists

**Usage:**
```python
result = ResearchResult(
    company_name="Microsoft Corporation",
    gcc_presence=True,
    suitability_score=9,
    business_pain_points=["High costs", "Talent shortage"],
    expansion_indicators=["Growth", "New markets"],
    hiring_signals=["Job postings", "Campus recruiting"],
    research_summary="Excellent GCC candidate...",
    is_cached=False,
    created_at=datetime.utcnow()
)
```

### ProcessingSession

Tracks batch processing operations with real-time metrics.

**Key Features:**
- Calculates progress and cache hit rate percentages
- Validates processing counts don't exceed totals
- Detects completion status
- Provides session metadata

**Usage:**
```python
session = ProcessingSession(
    session_id="batch_20241201_143022",
    total_companies=100,
    processed_companies=25,
    cache_hits=10,
    status="running"
)

print(f"Progress: {session.progress_percentage}%")
print(f"Cache rate: {session.cache_hit_rate}%")
```

### UserSession

Manages authentication and session state.

**Key Features:**
- Validates session tokens and user IDs
- Detects expired sessions automatically
- Tracks session activity timestamps
- Ensures proper expiration logic

**Usage:**
```python
session = UserSession(
    user_id=123,
    session_token="secure-token-abc",
    created_at=datetime.utcnow(),
    expires_at=datetime.utcnow() + timedelta(hours=8)
)

if session.is_valid():
    # User has access to platform
    pass
```

## Validation Rules

### CompanyRecord Validation
- `name`: Must not be empty or whitespace-only
- `normalized_key`: Must not be empty  
- `row_index`: Must be non-negative

### ResearchResult Validation
- `suitability_score`: Must be between 1 and 10 (inclusive)
- `company_name`: Must not be empty
- `research_summary`: Must not be empty
- Lists: Converted from None to empty lists automatically

### ProcessingSession Validation
- `total_companies`: Must be non-negative
- `processed_companies`: Must not exceed total_companies
- `status`: Must be one of: 'running', 'stopped', 'completed', 'error'
- `session_id`: Must not be empty

### UserSession Validation
- `user_id`: Must be positive
- `session_token`: Must not be empty
- `expires_at`: Must be after `created_at`

## Testing

The DTOs include comprehensive validation tests:

```bash
# Run validation tests
cd src/models
python3 validate_entities.py

# Run demonstration
python3 demo_entities.py
```

## Requirements Mapping

- **Requirement 5.3**: AI Research Engine JSON format validation
- **Requirement 13.6**: Comprehensive type hints and docstrings  
- **Requirement 14.1**: Comprehensive error handling for all user interactions
- **Requirement 14.2**: Input validation before processing

## Error Handling

All DTOs provide clear, actionable error messages:

```python
try:
    company = CompanyRecord("", "test.com", "key", 0)
except ValueError as e:
    print(e)  # "Company name cannot be empty"

try:
    result = ResearchResult(..., suitability_score=15, ...)
except ValueError as e:
    print(e)  # "Suitability score must be between 1 and 10"
```

## Integration

These DTOs serve as the foundation for:
- Database operations (ORM mapping)
- API request/response handling
- Cache key generation
- Progress tracking systems
- Authentication workflows

They provide type-safe contracts between all system components while ensuring data integrity through comprehensive validation.