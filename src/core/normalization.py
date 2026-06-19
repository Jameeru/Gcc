"""
Company name and domain normalization functions for the GCC Research Intelligence Platform.

This module provides standardization functions to create consistent cache keys
for deduplication across all users. Handles special characters, whitespace,
and case conversion according to Requirements 3.1, 3.2, 3.3, 3.4.
"""

import re
from typing import Optional


def normalize_company_name(name: str) -> str:
    """
    Normalize a company name for consistent cache key generation.
    
    Applies standardization rules to create consistent keys regardless
    of minor variations in formatting, capitalization, or punctuation.
    
    Args:
        name: The raw company name to normalize
        
    Returns:
        Normalized company name with special characters removed,
        whitespace collapsed, and converted to lowercase
        
    Raises:
        ValueError: If name is None, empty, or contains only whitespace
        
    Examples:
        >>> normalize_company_name("Microsoft Corporation")
        'microsoftcorporation'
        >>> normalize_company_name("  Apple Inc.  ")
        'appleinc'
        >>> normalize_company_name("AT&T Inc.")
        'attinc'
        >>> normalize_company_name("Coca-Cola Company")
        'cocacolacompany'
        
    **Validates: Requirements 3.1, 3.2, 3.4**
    """
    if not name or not name.strip():
        raise ValueError("Company name cannot be empty or whitespace")
    
    # Step 1: Convert to lowercase for case-insensitive matching
    normalized = name.lower()
    
    # Step 2: Remove common company suffixes and legal entity markers
    # This helps match "Microsoft" and "Microsoft Corporation" as the same company
    suffixes_to_remove = [
        'corporation', 'corp', 'incorporated', 'inc', 'company', 'co',
        'limited', 'ltd', 'llc', 'llp', 'lp', 'plc', 'sa', 'ag', 'gmbh',
        'enterprises', 'holdings', 'group', 'international', 'intl',
        'technologies', 'tech', 'systems', 'solutions', 'services',
        'associates', 'partners', 'ventures', 'industries', 'ind'
    ]
    
    # Remove suffixes only if they appear at the end (with optional punctuation)
    # Continue removing suffixes until no more can be removed
    # Sort suffixes by length (longest first) to handle overlapping suffixes correctly
    sorted_suffixes = sorted(suffixes_to_remove, key=len, reverse=True)
    
    # Keep removing suffixes until none are found
    changed = True
    while changed:
        changed = False
        for suffix in sorted_suffixes:
            # Pattern matches suffix at end with optional punctuation and whitespace
            pattern = rf'\b{re.escape(suffix)}[.,\s]*$'
            new_normalized = re.sub(pattern, '', normalized).strip()
            if new_normalized != normalized and new_normalized:  # Only accept if we still have content
                normalized = new_normalized
                changed = True
                break  # Start over with the longest suffixes first
    
    # Step 3: Remove all special characters and punctuation
    # Keep only alphanumeric characters and spaces
    normalized = re.sub(r'[^a-z0-9\s]', '', normalized)
    
    # Step 4: Collapse multiple whitespaces into single spaces
    normalized = re.sub(r'\s+', ' ', normalized)
    
    # Step 5: Remove all remaining whitespace to create a single token
    normalized = normalized.replace(' ', '')
    
    # Final validation - ensure we still have content
    if not normalized:
        raise ValueError("Company name contains no valid characters after normalization")
    
    return normalized


def normalize_domain(domain: Optional[str]) -> Optional[str]:
    """
    Normalize a company domain for consistent cache key generation.
    
    Handles missing domain data gracefully and standardizes domain format
    for consistent matching across variations.
    
    Args:
        domain: The raw domain to normalize (can be None)
        
    Returns:
        Normalized domain in lowercase without protocol prefixes,
        or None if domain is empty/invalid
        
    Examples:
        >>> normalize_domain("https://www.microsoft.com")
        'microsoft.com'
        >>> normalize_domain("APPLE.COM")
        'apple.com'
        >>> normalize_domain("http://subdomain.company.co.uk/")
        'subdomain.company.co.uk'
        >>> normalize_domain("")
        None
        >>> normalize_domain(None)
        None
        
    **Validates: Requirements 3.2, 3.3, 3.4**
    """
    # Handle missing domain data gracefully
    if not domain or not domain.strip():
        return None
    
    # Step 1: Convert to lowercase
    normalized = domain.lower().strip()
    
    # Step 2: Remove protocol prefixes (http://, https://, ftp://, etc.)
    normalized = re.sub(r'^[a-z]+://', '', normalized)
    
    # Step 3: Remove www. prefix if present
    normalized = re.sub(r'^www\.', '', normalized)
    
    # Step 4: Remove trailing path, query parameters, and fragments
    # Keep only the domain part
    normalized = re.sub(r'/.*$', '', normalized)
    normalized = re.sub(r'\?.*$', '', normalized)
    normalized = re.sub(r'#.*$', '', normalized)
    
    # Step 5: Remove trailing dots and whitespace
    normalized = normalized.rstrip('.')
    
    # Validate that we have a valid domain format
    # Must contain at least one dot and valid characters
    if not re.match(r'^[a-z0-9.-]+\.[a-z]{2,}$', normalized):
        return None
    
    return normalized


def normalize_company(name: str, domain: Optional[str] = None) -> str:
    """
    Create a standardized cache key from company name and optional domain.
    
    This is the main normalization function that combines company name
    and domain normalization to create consistent cache keys for
    deduplication across all users.
    
    Args:
        name: The company name to normalize (required)
        domain: The company domain to normalize (optional)
        
    Returns:
        Standardized cache key combining normalized name and domain
        
    Raises:
        ValueError: If company name is invalid
        
    Examples:
        >>> normalize_company("Microsoft Corporation", "https://www.microsoft.com")
        'microsoft_microsoft.com'
        >>> normalize_company("Apple Inc.", "APPLE.COM")
        'apple_apple.com'
        >>> normalize_company("Google LLC", None)
        'google'
        >>> normalize_company("AT&T Inc.", "att.com")
        'att_att.com'
        
    **Validates: Requirements 3.1, 3.2, 3.3, 3.4**
    """
    # Normalize the company name (required)
    normalized_name = normalize_company_name(name)
    
    # Normalize the domain (optional)
    normalized_domain = normalize_domain(domain)
    
    # Create cache key
    if normalized_domain:
        # Combine name and domain with underscore separator
        cache_key = f"{normalized_name}_{normalized_domain}"
    else:
        # Use only the normalized name if no valid domain
        cache_key = normalized_name
    
    return cache_key


def create_company_record_with_normalization(
    name: str, 
    domain: Optional[str], 
    row_index: int
) -> 'CompanyRecord':
    """
    Create a CompanyRecord with automatic normalization.
    
    This is a convenience function that creates a CompanyRecord instance
    with the normalized_key automatically generated from the provided
    name and domain.
    
    Args:
        name: The company name
        domain: The company domain (optional)
        row_index: The row index from the CSV file
        
    Returns:
        CompanyRecord instance with normalized_key set
        
    Raises:
        ValueError: If company name is invalid
        
    Examples:
        >>> record = create_company_record_with_normalization(
        ...     "Microsoft Corp", "microsoft.com", 0
        ... )
        >>> record.normalized_key
        'microsoft_microsoft.com'
        
    **Validates: Requirements 3.1, 3.2, 3.3, 3.4**
    """
    # Import here to avoid circular imports
    import sys
    import os
    sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
    from src.models.entities import CompanyRecord
    
    # Generate normalized key
    normalized_key = normalize_company(name, domain)
    
    # Create and return the CompanyRecord
    return CompanyRecord(
        name=name,
        domain=domain,
        normalized_key=normalized_key,
        row_index=row_index
    )


# Validation functions for testing and debugging

def validate_normalization_consistency(test_cases: list) -> bool:
    """
    Validate that normalization produces consistent results for equivalent inputs.
    
    This function is primarily for testing to ensure that equivalent company
    variations produce the same normalized key.
    
    Args:
        test_cases: List of tuples containing equivalent (name, domain) pairs
        
    Returns:
        True if all equivalent cases produce the same normalized key
        
    **Validates: Requirements 3.4**
    """
    for case_group in test_cases:
        if not case_group:
            continue
            
        # Get the normalized key for the first case in the group
        first_case = case_group[0]
        expected_key = normalize_company(first_case[0], first_case[1])
        
        # Check that all other cases in the group produce the same key
        for name, domain in case_group[1:]:
            actual_key = normalize_company(name, domain)
            if actual_key != expected_key:
                return False
    
    return True


def get_normalization_stats(names_and_domains: list) -> dict:
    """
    Get statistics about normalization results for analysis.
    
    Useful for understanding the effectiveness of the normalization
    algorithm and identifying potential improvements.
    
    Args:
        names_and_domains: List of (name, domain) tuples to analyze
        
    Returns:
        Dictionary containing normalization statistics
        
    **Validates: Requirements 3.1, 3.2, 3.3, 3.4**
    """
    stats = {
        'total_processed': 0,
        'unique_keys': 0,
        'duplicate_keys': 0,
        'domain_present': 0,
        'domain_missing': 0,
        'normalization_errors': 0
    }
    
    normalized_keys = set()
    key_counts = {}
    
    for name, domain in names_and_domains:
        stats['total_processed'] += 1
        
        try:
            # Attempt normalization
            key = normalize_company(name, domain)
            
            # Track unique keys
            if key not in normalized_keys:
                normalized_keys.add(key)
                stats['unique_keys'] += 1
                key_counts[key] = 1
            else:
                key_counts[key] += 1
            
            # Track domain presence
            if domain and normalize_domain(domain):
                stats['domain_present'] += 1
            else:
                stats['domain_missing'] += 1
                
        except ValueError:
            stats['normalization_errors'] += 1
    
    # Calculate duplicate statistics
    stats['duplicate_keys'] = sum(1 for count in key_counts.values() if count > 1)
    
    return stats