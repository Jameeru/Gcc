# Company Normalization Module

## Overview

The normalization module provides standardization functions to create consistent cache keys for company data deduplication across all users. This is a critical component of the GCC Research Intelligence Platform that prevents duplicate AI research costs.

## Key Functions

### `normalize_company_name(name: str) -> str`

Normalizes a company name for consistent cache key generation.

**Features:**
- Converts to lowercase for case-insensitive matching
- Removes common company suffixes (Corp, Inc, LLC, etc.)
- Strips special characters and punctuation
- Collapses whitespace
- Handles various international business entity types

**Examples:**
```python
normalize_company_name("Microsoft Corporation") # -> "microsoft"
normalize_company_name("Apple Inc.") # -> "apple" 
normalize_company_name("AT&T Inc.") # -> "att"
```

### `normalize_domain(domain: Optional[str]) -> Optional[str]`

Normalizes a company domain for consistent cache key generation.

**Features:**
- Handles missing domain data gracefully (returns None)
- Removes protocol prefixes (http://, https://)
- Removes www. prefix
- Strips paths, query parameters, and fragments
- Converts to lowercase
- Validates domain format

**Examples:**
```python
normalize_domain("https://www.microsoft.com") # -> "microsoft.com"
normalize_domain("APPLE.COM") # -> "apple.com"
normalize_domain("") # -> None
```

### `normalize_company(name: str, domain: Optional[str] = None) -> str`

Main normalization function that creates standardized cache keys.

**Features:**
- Combines normalized name and domain with underscore separator
- Falls back to name-only key if domain is invalid/missing
- Ensures consistent keys for equivalent company variations

**Examples:**
```python
normalize_company("Microsoft Corporation", "microsoft.com") # -> "microsoft_microsoft.com"
normalize_company("Apple Inc.", None) # -> "apple"
```

### `create_company_record_with_normalization(...) -> CompanyRecord`

Convenience function that creates a CompanyRecord with automatic normalization.

## Validation Requirements

The module satisfies the following requirements:

- **3.1**: Creates standardized cache keys from company names and domains ✓
- **3.2**: Removes special characters, whitespace, and converts to lowercase ✓  
- **3.3**: Handles missing domain data gracefully ✓
- **3.4**: Generates consistent keys for equivalent company variations ✓

## Cache Deduplication Benefits

The normalization ensures these equivalent variations produce the same cache key:

```python
# All produce key: "microsoft_microsoft.com"
normalize_company("Microsoft Corporation", "microsoft.com")
normalize_company("Microsoft Corp", "www.microsoft.com") 
normalize_company("MICROSOFT INC.", "https://microsoft.com/")
```

This prevents duplicate AI research costs across all users.

## Error Handling

The module includes robust error handling:

- **Empty company names**: Raises `ValueError`
- **Whitespace-only names**: Raises `ValueError`
- **Names with only special characters**: Raises `ValueError`
- **Invalid domains**: Returns None gracefully

## Testing

Comprehensive test suite covers:
- 39 unit tests across all functions
- Edge cases and error conditions
- Real-world company name variations
- Cache deduplication scenarios
- End-to-end integration tests

Run tests with:
```bash
python3 -m pytest tests/test_normalization.py -v
```

## Usage Examples

See `demo_normalization.py` for complete usage examples including:
- Basic normalization workflows
- Cache deduplication scenarios
- CompanyRecord creation
- Edge case handling

## Integration

The normalization module integrates with:
- **CompanyRecord entities**: Automatic key generation
- **Research cache**: Consistent cache lookups
- **CSV upload processing**: Real-time normalization
- **Database storage**: Normalized keys as primary cache identifiers

This ensures the platform maintains data consistency and prevents duplicate research costs across all user interactions.