"""
Demonstration of the company normalization functions.

This module shows how the normalization functions work with real-world examples
and demonstrates the cache deduplication capabilities.
"""

from normalization import (
    normalize_company_name,
    normalize_domain,
    normalize_company,
    create_company_record_with_normalization
)


def demo_company_name_normalization():
    """Demonstrate company name normalization with various inputs."""
    print("=== Company Name Normalization Demo ===\n")
    
    test_names = [
        "Microsoft Corporation",
        "Apple Inc.",
        "Google LLC", 
        "AT&T Inc.",
        "Johnson & Johnson",
        "Coca-Cola Company",
        "  IBM Corp  ",
        "AMAZON.COM, INC.",
        "Tesla, Inc.",
        "Procter & Gamble Co."
    ]
    
    for name in test_names:
        normalized = normalize_company_name(name)
        print(f"'{name}' -> '{normalized}'")
    
    print()


def demo_domain_normalization():
    """Demonstrate domain normalization with various inputs."""
    print("=== Domain Normalization Demo ===\n")
    
    test_domains = [
        "https://www.microsoft.com",
        "APPLE.COM",
        "http://google.com/search",
        "www.amazon.com/products?category=books",
        "tesla.com.",
        "ibm.com",
        None,
        "",
        "invalid-domain",
        "subdomain.company.co.uk"
    ]
    
    for domain in test_domains:
        normalized = normalize_domain(domain)
        print(f"'{domain}' -> '{normalized}'")
    
    print()


def demo_full_normalization():
    """Demonstrate full company normalization combining name and domain."""
    print("=== Full Company Normalization Demo ===\n")
    
    test_companies = [
        ("Microsoft Corporation", "https://www.microsoft.com"),
        ("Apple Inc.", "APPLE.COM"),
        ("Google LLC", None),
        ("AT&T Inc.", "att.com"),
        ("Tesla, Inc.", "tesla.com"),
        ("IBM Corp", ""),
        ("Amazon.com, Inc.", "amazon.com/"),
    ]
    
    for name, domain in test_companies:
        normalized_key = normalize_company(name, domain)
        print(f"Company: '{name}', Domain: '{domain}' -> Key: '{normalized_key}'")
    
    print()


def demo_cache_deduplication():
    """Demonstrate cache deduplication scenario."""
    print("=== Cache Deduplication Demo ===\n")
    
    # Simulate different users uploading variations of the same companies
    user1_uploads = [
        ("Microsoft Corp", "microsoft.com"),
        ("Apple Inc", "apple.com"),
        ("Google LLC", "google.com")
    ]
    
    user2_uploads = [
        ("Microsoft Corporation", "www.microsoft.com"),
        ("Apple Incorporated", "https://apple.com"),
        ("Google Inc.", "https://www.google.com/")
    ]
    
    print("User 1 uploads:")
    user1_keys = []
    for name, domain in user1_uploads:
        key = normalize_company(name, domain)
        user1_keys.append(key)
        print(f"  '{name}' + '{domain}' -> '{key}'")
    
    print("\nUser 2 uploads:")
    user2_keys = []
    for name, domain in user2_uploads:
        key = normalize_company(name, domain)
        user2_keys.append(key)
        print(f"  '{name}' + '{domain}' -> '{key}'")
    
    print("\nCache hits detected:")
    for i, (key1, key2) in enumerate(zip(user1_keys, user2_keys)):
        if key1 == key2:
            print(f"  Company {i+1}: CACHE HIT - '{key1}' matches")
        else:
            print(f"  Company {i+1}: No match - '{key1}' vs '{key2}'")
    
    print()


def demo_company_record_creation():
    """Demonstrate CompanyRecord creation with normalization."""
    print("=== CompanyRecord Creation Demo ===\n")
    
    csv_data = [
        ("Microsoft Corporation", "https://www.microsoft.com", 0),
        ("  Apple Inc.  ", "APPLE.COM", 1),
        ("Google LLC", "", 2),
        ("Tesla, Inc.", None, 3),
    ]
    
    print("Creating CompanyRecord objects from CSV data:")
    records = []
    
    for name, domain, row_index in csv_data:
        record = create_company_record_with_normalization(name, domain, row_index)
        records.append(record)
        
        print(f"Row {row_index}:")
        print(f"  Original: name='{name}', domain='{domain}'")
        print(f"  Record: name='{record.name}', domain='{record.domain}'")
        print(f"  Cache key: '{record.normalized_key}'")
        print()
    
    return records


def demo_edge_cases():
    """Demonstrate handling of edge cases and error conditions."""
    print("=== Edge Cases and Error Handling Demo ===\n")
    
    print("Testing edge cases:")
    
    # Valid edge cases
    edge_cases = [
        ("3M Company", "3m.com"),
        ("A.P. Møller-Mærsk A/S", "maersk.com"),
        ("Berkshire Hathaway Inc.", "berkshirehathaway.com"),
        ("Royal Dutch Shell plc", "shell.com")
    ]
    
    for name, domain in edge_cases:
        try:
            key = normalize_company(name, domain)
            print(f"  '{name}' -> '{key}' ✓")
        except Exception as e:
            print(f"  '{name}' -> ERROR: {e} ✗")
    
    print("\nTesting error conditions:")
    
    # Error conditions
    error_cases = [
        ("", "microsoft.com"),  # Empty name
        ("   ", "apple.com"),   # Whitespace-only name
        ("!@#$%", "test.com"),  # Special characters only
    ]
    
    for name, domain in error_cases:
        try:
            key = normalize_company(name, domain)
            print(f"  '{name}' -> '{key}' (unexpected success)")
        except ValueError as e:
            print(f"  '{name}' -> ERROR: {e} ✓")
    
    print()


if __name__ == "__main__":
    """Run all normalization demos."""
    print("GCC Research Intelligence Platform - Normalization Demo")
    print("=" * 60)
    print()
    
    demo_company_name_normalization()
    demo_domain_normalization() 
    demo_full_normalization()
    demo_cache_deduplication()
    demo_company_record_creation()
    demo_edge_cases()
    
    print("Demo completed successfully!")
    print("\nKey benefits of normalization:")
    print("✓ Consistent cache keys prevent duplicate AI research costs")
    print("✓ Handles various input formats and edge cases gracefully")
    print("✓ Robust error handling for invalid inputs")
    print("✓ Optimized for real-world company name variations")