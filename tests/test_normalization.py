"""
Unit tests and property-based tests for the normalization module.

Tests the company name and domain normalization functions to ensure
consistent cache key generation across all edge cases and requirements.
"""

import pytest
from hypothesis import given, strategies as st, assume, settings, HealthCheck
import string
from src.core.normalization import (
    normalize_company_name,
    normalize_domain,
    normalize_company,
    create_company_record_with_normalization,
    validate_normalization_consistency,
    get_normalization_stats
)


class TestNormalizeCompanyName:
    """Test cases for normalize_company_name function."""
    
    def test_basic_normalization(self):
        """Test basic company name normalization."""
        assert normalize_company_name("Microsoft Corporation") == "microsoft"
        assert normalize_company_name("Apple Inc.") == "apple"
        assert normalize_company_name("Google LLC") == "google"
        
    def test_case_conversion(self):
        """Test that all cases are converted to lowercase."""
        assert normalize_company_name("MICROSOFT") == "microsoft"
        assert normalize_company_name("MiXeD CaSe CoMpAnY") == "mixedcase"
        assert normalize_company_name("lowercase inc") == "lowercase"
        
    def test_whitespace_handling(self):
        """Test whitespace removal and normalization."""
        assert normalize_company_name("  Microsoft  ") == "microsoft"
        assert normalize_company_name("Multi   Word    Company") == "multiword"
        assert normalize_company_name("\t\nApple\t\n") == "apple"
        
    def test_special_character_removal(self):
        """Test removal of special characters and punctuation."""
        assert normalize_company_name("AT&T Inc.") == "att"
        assert normalize_company_name("Johnson & Johnson") == "johnsonjohnson"
        assert normalize_company_name("Coca-Cola Company") == "cocacola"
        assert normalize_company_name("3M Company") == "3m"
        assert normalize_company_name("Procter & Gamble Co.") == "proctergamble"
        
    def test_suffix_removal(self):
        """Test removal of common company suffixes."""
        # Corporation variations
        assert normalize_company_name("Microsoft Corporation") == "microsoft"
        assert normalize_company_name("Microsoft Corp") == "microsoft"
        assert normalize_company_name("Microsoft Corp.") == "microsoft"
        
        # Incorporated variations
        assert normalize_company_name("Apple Incorporated") == "apple"
        assert normalize_company_name("Apple Inc") == "apple"
        assert normalize_company_name("Apple Inc.") == "apple"
        
        # Limited variations
        assert normalize_company_name("Unilever Limited") == "unilever"
        assert normalize_company_name("Unilever Ltd") == "unilever"
        assert normalize_company_name("Unilever Ltd.") == "unilever"
        
        # Company variations
        assert normalize_company_name("Ford Company") == "ford"
        assert normalize_company_name("Ford Co") == "ford"
        assert normalize_company_name("Ford Co.") == "ford"
        
        # Other common suffixes
        assert normalize_company_name("Oracle Technologies") == "oracle"
        assert normalize_company_name("IBM Services") == "ibm"
        assert normalize_company_name("Acme Solutions") == "acme"
        assert normalize_company_name("Global Holdings") == "global"
        
    def test_multiple_suffixes(self):
        """Test handling of multiple suffixes."""
        assert normalize_company_name("Tech Solutions Inc.") == "tech"
        assert normalize_company_name("Global Services Corporation") == "global"
        
    def test_suffix_in_middle_preserved(self):
        """Test that suffixes in the middle of names are preserved."""
        assert normalize_company_name("Corporation Bank") == "corporationbank"
        assert normalize_company_name("Company Store Inc.") == "companystore"
        
    def test_empty_input_raises_error(self):
        """Test that empty inputs raise ValueError."""
        with pytest.raises(ValueError, match="Company name cannot be empty"):
            normalize_company_name("")
            
        with pytest.raises(ValueError, match="Company name cannot be empty"):
            normalize_company_name("   ")
            
        with pytest.raises(ValueError, match="Company name cannot be empty"):
            normalize_company_name("\t\n")
    
    def test_none_input_raises_error(self):
        """Test that None input raises ValueError."""
        with pytest.raises(ValueError, match="Company name cannot be empty"):
            normalize_company_name(None)
    
    def test_special_characters_only_raises_error(self):
        """Test that names with only special characters raise error."""
        with pytest.raises(ValueError, match="no valid characters after normalization"):
            normalize_company_name("!@#$%^&*()")
            
        with pytest.raises(ValueError, match="no valid characters after normalization"):
            normalize_company_name("--- ... ___")


class TestNormalizeDomain:
    """Test cases for normalize_domain function."""
    
    def test_basic_domain_normalization(self):
        """Test basic domain normalization."""
        assert normalize_domain("microsoft.com") == "microsoft.com"
        assert normalize_domain("apple.com") == "apple.com"
        assert normalize_domain("google.co.uk") == "google.co.uk"
        
    def test_case_conversion(self):
        """Test domain case conversion to lowercase."""
        assert normalize_domain("MICROSOFT.COM") == "microsoft.com"
        assert normalize_domain("MiXeD.CaSe.CoM") == "mixed.case.com"
        
    def test_protocol_removal(self):
        """Test removal of protocol prefixes."""
        assert normalize_domain("https://microsoft.com") == "microsoft.com"
        assert normalize_domain("http://apple.com") == "apple.com"
        assert normalize_domain("ftp://files.example.com") == "files.example.com"
        
    def test_www_removal(self):
        """Test removal of www prefix."""
        assert normalize_domain("www.microsoft.com") == "microsoft.com"
        assert normalize_domain("https://www.apple.com") == "apple.com"
        
    def test_path_removal(self):
        """Test removal of paths and query parameters."""
        assert normalize_domain("microsoft.com/products") == "microsoft.com"
        assert normalize_domain("apple.com/iphone?color=black") == "apple.com"
        assert normalize_domain("google.com/search#results") == "google.com"
        
    def test_subdomain_preservation(self):
        """Test that subdomains are preserved."""
        assert normalize_domain("mail.google.com") == "mail.google.com"
        assert normalize_domain("developers.microsoft.com") == "developers.microsoft.com"
        
    def test_whitespace_handling(self):
        """Test whitespace removal."""
        assert normalize_domain("  microsoft.com  ") == "microsoft.com"
        assert normalize_domain("\tgoogle.com\n") == "google.com"
        
    def test_trailing_dots_removal(self):
        """Test removal of trailing dots."""
        assert normalize_domain("microsoft.com.") == "microsoft.com"
        assert normalize_domain("apple.com...") == "apple.com"
        
    def test_empty_domain_returns_none(self):
        """Test that empty domains return None."""
        assert normalize_domain("") is None
        assert normalize_domain("   ") is None
        assert normalize_domain("\t\n") is None
        
    def test_none_domain_returns_none(self):
        """Test that None domain returns None."""
        assert normalize_domain(None) is None
        
    def test_invalid_domain_returns_none(self):
        """Test that invalid domains return None."""
        assert normalize_domain("not-a-domain") is None
        assert normalize_domain("123.456.789") is None
        assert normalize_domain("localhost") is None


class TestNormalizeCompany:
    """Test cases for normalize_company function."""
    
    def test_name_and_domain_combination(self):
        """Test combining normalized name and domain."""
        result = normalize_company("Microsoft Corporation", "https://www.microsoft.com")
        assert result == "microsoft_microsoft.com"
        
        result = normalize_company("Apple Inc.", "APPLE.COM")
        assert result == "apple_apple.com"
        
    def test_name_only_no_domain(self):
        """Test normalization with name only."""
        assert normalize_company("Microsoft Corporation", None) == "microsoft"
        assert normalize_company("Apple Inc.", "") == "apple"
        assert normalize_company("Google LLC", "   ") == "google"
        
    def test_name_with_invalid_domain(self):
        """Test normalization when domain is invalid."""
        assert normalize_company("Microsoft", "invalid-domain") == "microsoft"
        assert normalize_company("Apple", "localhost") == "apple"
        
    def test_consistency_with_variations(self):
        """Test that equivalent company variations produce same keys."""
        # Same company, different name formats
        key1 = normalize_company("Microsoft Corporation", "microsoft.com")
        key2 = normalize_company("Microsoft Corp", "www.microsoft.com")
        key3 = normalize_company("MICROSOFT INC.", "https://microsoft.com/")
        
        assert key1 == key2 == key3 == "microsoft_microsoft.com"
        
        # Different domains for same company should be different
        key4 = normalize_company("Microsoft", "outlook.com")
        assert key4 != key1
        
    def test_special_characters_in_names(self):
        """Test handling special characters in company names."""
        assert normalize_company("AT&T Inc.", "att.com") == "att_att.com"
        assert normalize_company("Johnson & Johnson", "jnj.com") == "johnsonjohnson_jnj.com"
        
    def test_empty_name_raises_error(self):
        """Test that empty company name raises error."""
        with pytest.raises(ValueError):
            normalize_company("", "microsoft.com")


class TestCreateCompanyRecordWithNormalization:
    """Test cases for create_company_record_with_normalization function."""
    
    def test_create_record_with_domain(self):
        """Test creating record with name and domain."""
        record = create_company_record_with_normalization(
            "Microsoft Corporation", "microsoft.com", 0
        )
        
        assert record.name == "Microsoft Corporation"
        assert record.domain == "microsoft.com"
        assert record.normalized_key == "microsoft_microsoft.com"
        assert record.row_index == 0
        
    def test_create_record_without_domain(self):
        """Test creating record with name only."""
        record = create_company_record_with_normalization(
            "Apple Inc.", None, 5
        )
        
        assert record.name == "Apple Inc."
        assert record.domain is None
        assert record.normalized_key == "apple"
        assert record.row_index == 5
        
    def test_create_record_with_invalid_domain(self):
        """Test creating record with invalid domain."""
        record = create_company_record_with_normalization(
            "Google LLC", "invalid", 10
        )
        
        assert record.name == "Google LLC"
        assert record.domain == "invalid"
        assert record.normalized_key == "google"
        assert record.row_index == 10


class TestValidateNormalizationConsistency:
    """Test cases for validate_normalization_consistency function."""
    
    def test_consistent_variations(self):
        """Test that equivalent variations are detected as consistent."""
        test_cases = [
            [
                ("Microsoft Corporation", "microsoft.com"),
                ("Microsoft Corp", "www.microsoft.com"),
                ("MICROSOFT INC.", "https://microsoft.com/")
            ],
            [
                ("Apple Inc.", "apple.com"),
                ("Apple Incorporated", "APPLE.COM"),
                ("APPLE", "https://www.apple.com/")
            ]
        ]
        
        assert validate_normalization_consistency(test_cases) is True
        
    def test_inconsistent_variations(self):
        """Test detection of inconsistent variations."""
        test_cases = [
            [
                ("Microsoft Corporation", "microsoft.com"),
                ("Apple Inc.", "apple.com")  # Different companies
            ]
        ]
        
        assert validate_normalization_consistency(test_cases) is False
        
    def test_empty_test_cases(self):
        """Test handling of empty test cases."""
        assert validate_normalization_consistency([]) is True
        assert validate_normalization_consistency([[]]) is True


class TestGetNormalizationStats:
    """Test cases for get_normalization_stats function."""
    
    def test_basic_stats(self):
        """Test basic statistics calculation."""
        test_data = [
            ("Microsoft Corporation", "microsoft.com"),
            ("Apple Inc.", "apple.com"),
            ("Google LLC", None),
            ("Microsoft Corp", "microsoft.com")  # Duplicate
        ]
        
        stats = get_normalization_stats(test_data)
        
        assert stats['total_processed'] == 4
        assert stats['unique_keys'] == 3  # microsoft, apple, google
        assert stats['duplicate_keys'] == 1  # microsoft appears twice
        assert stats['domain_present'] == 3
        assert stats['domain_missing'] == 1
        assert stats['normalization_errors'] == 0
        
    def test_normalization_errors(self):
        """Test handling of normalization errors in stats."""
        test_data = [
            ("", "microsoft.com"),  # Empty name should cause error
            ("Apple Inc.", "apple.com"),
        ]
        
        stats = get_normalization_stats(test_data)
        
        assert stats['total_processed'] == 2
        assert stats['normalization_errors'] == 1


class TestEndToEndScenarios:
    """Integration tests for complete normalization scenarios."""
    
    def test_real_world_company_names(self):
        """Test normalization with real-world company name variations."""
        # Test data with companies that should normalize to the same key
        equivalent_companies = [
            ("IBM Corporation", "ibm.com"),
            ("IBM Corp", "www.ibm.com"), 
            ("I.B.M. Inc.", "https://ibm.com/"),
        ]
        
        keys = [normalize_company(name, domain) for name, domain in equivalent_companies]
        assert len(set(keys)) == 1  # All should produce the same key
        
    def test_different_companies_different_keys(self):
        """Test that different companies produce different keys."""
        companies = [
            ("Microsoft Corporation", "microsoft.com"),
            ("Apple Inc.", "apple.com"),
            ("Google LLC", "google.com"),
            ("Amazon.com Inc.", "amazon.com"),
        ]
        
        keys = [normalize_company(name, domain) for name, domain in companies]
        assert len(set(keys)) == len(companies)  # All should be unique
        
    def test_csv_upload_simulation(self):
        """Test normalization as it would be used in CSV processing."""
        # Simulate CSV data with various formatting issues
        csv_data = [
            ("Microsoft Corporation", "https://www.microsoft.com", 0),
            ("  Apple Inc.  ", "APPLE.COM", 1),
            ("Google LLC", "", 2),
            ("Amazon.com, Inc.", "amazon.com/", 3),
            ("Tesla, Inc.", None, 4),
        ]
        
        records = []
        for name, domain, row_index in csv_data:
            record = create_company_record_with_normalization(name, domain, row_index)
            records.append(record)
        
        # Verify all records were created successfully
        assert len(records) == 5
        
        # Verify normalized keys are reasonable
        expected_keys = [
            "microsoft_microsoft.com",
            "apple_apple.com", 
            "google",
            "amazoncom_amazon.com",
            "tesla"
        ]
        
        actual_keys = [record.normalized_key for record in records]
        assert actual_keys == expected_keys
        
    def test_cache_deduplication_scenario(self):
        """Test the cache deduplication use case."""
        # Different users uploading slightly different versions of the same companies
        user1_data = [("Microsoft Corp", "microsoft.com"), ("Apple Inc", "apple.com")]
        user2_data = [("Microsoft Corporation", "www.microsoft.com"), ("Apple Incorporated", "https://apple.com")]
        
        user1_keys = [normalize_company(name, domain) for name, domain in user1_data]
        user2_keys = [normalize_company(name, domain) for name, domain in user2_data]
        
        # Should produce the same keys for cache hits
        assert user1_keys == user2_keys


# Hypothesis strategies for generating test data for property tests

@st.composite
def company_names(draw):
    """Generate valid company names for property testing."""
    # Base name components
    base_words = draw(st.lists(
        st.text(
            alphabet=string.ascii_letters + string.digits,
            min_size=1,
            max_size=15
        ).filter(lambda x: x.strip()),
        min_size=1,
        max_size=4
    ))
    
    # Optional suffixes that should normalize identically
    suffixes = [
        "", "Corp", "Corporation", "Inc", "Incorporated", "Company", "Co",
        "Ltd", "Limited", "LLC", "Technologies", "Tech", "Services", "Solutions"
    ]
    suffix = draw(st.sampled_from(suffixes))
    
    # Combine base name with optional suffix
    base_name = " ".join(base_words)
    if suffix:
        full_name = f"{base_name} {suffix}"
    else:
        full_name = base_name
    
    return full_name


@st.composite
def company_domains(draw):
    """Generate valid company domains for property testing."""
    # Generate base domain name
    domain_parts = draw(st.lists(
        st.text(
            alphabet=string.ascii_lowercase + string.digits,
            min_size=1,
            max_size=10
        ).filter(lambda x: x and not x.startswith('-') and not x.endswith('-')),
        min_size=1,
        max_size=3
    ))
    
    # Top-level domains
    tlds = ["com", "org", "net", "co.uk", "de", "fr", "jp", "in"]
    tld = draw(st.sampled_from(tlds))
    
    base_domain = ".".join(domain_parts) + "." + tld
    
    # Optional protocol and www prefix
    protocol = draw(st.sampled_from(["", "http://", "https://"]))
    www = draw(st.sampled_from(["", "www."]))
    
    return f"{protocol}{www}{base_domain}"


@st.composite
def equivalent_company_variations(draw):
    """Generate variations of the same company that should normalize identically."""
    # Start with a base company name
    base_words = draw(st.lists(
        st.text(
            alphabet=string.ascii_letters,
            min_size=2,
            max_size=10
        ).filter(lambda x: x.strip()),
        min_size=1,
        max_size=3
    ))
    
    base_name = " ".join(base_words)
    
    # Generate domain
    domain_name = draw(st.text(
        alphabet=string.ascii_lowercase,
        min_size=3,
        max_size=10
    )) + ".com"
    
    # Create equivalent variations
    variations = []
    
    # Variation 1: Base name with Corp suffix
    variations.append((f"{base_name} Corp", domain_name))
    
    # Variation 2: Base name with Corporation suffix  
    variations.append((f"{base_name} Corporation", f"www.{domain_name}"))
    
    # Variation 3: Base name with Inc suffix and https
    variations.append((f"{base_name} Inc", f"https://{domain_name}"))
    
    # Variation 4: All caps with different suffix
    variations.append((f"{base_name.upper()} INCORPORATED", f"https://www.{domain_name}/"))
    
    # Variation 5: Mixed case with whitespace
    variations.append((f"  {base_name.title()} Company  ", f"  {domain_name}  "))
    
    return variations


class TestNormalizationProperties:
    """Property-based tests for normalization consistency."""
    
    @given(company_names(), company_domains())
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=1000)
    def test_property_6_normalization_consistency(self, company_name, company_domain):
        """
        **Validates: Requirements 3.1, 3.4**
        
        Property 6: Normalization Consistency
        For any company name and domain combination, the normalization engine 
        shall always produce the same standardized cache key when given identical inputs.
        
        This property ensures that:
        1. Multiple calls with identical inputs produce identical outputs
        2. The normalization function is deterministic and reproducible
        3. Cache key generation is consistent across all users and sessions
        """
        # Filter out invalid inputs that would raise exceptions
        try:
            # First normalization call
            key1 = normalize_company(company_name, company_domain)
            
            # Second normalization call with identical inputs
            key2 = normalize_company(company_name, company_domain)
            
            # Third normalization call with identical inputs
            key3 = normalize_company(company_name, company_domain)
            
            # All calls should produce identical results
            assert key1 == key2 == key3, (
                f"Normalization inconsistency detected:\n"
                f"Input: name='{company_name}', domain='{company_domain}'\n"
                f"Call 1 result: '{key1}'\n"
                f"Call 2 result: '{key2}'\n" 
                f"Call 3 result: '{key3}'\n"
                f"All calls should produce identical cache keys"
            )
            
            # Verify the key is a valid string
            assert isinstance(key1, str), "Cache key must be a string"
            assert key1, "Cache key must not be empty"
            
            # Verify key contains only lowercase alphanumeric and underscore
            assert all(c.islower() or c.isdigit() or c == '_' or c == '.' for c in key1), (
                f"Cache key contains invalid characters: '{key1}'"
            )
            
        except ValueError:
            # Skip test cases that result in invalid inputs (empty names, etc.)
            assume(False)
    
    @given(equivalent_company_variations())
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=1000)
    def test_property_6_equivalent_variations_consistency(self, company_variations):
        """
        **Validates: Requirements 3.1, 3.4**
        
        Property 6: Normalization Consistency (Equivalent Variations)
        For any set of equivalent company name and domain variations (different formatting 
        of the same company), the normalization engine shall produce identical cache keys.
        
        This ensures that companies with different legal entity suffixes, case variations,
        whitespace differences, and protocol variations are recognized as the same entity.
        """
        try:
            # Normalize all variations
            cache_keys = []
            for company_name, company_domain in company_variations:
                key = normalize_company(company_name, company_domain)
                cache_keys.append(key)
            
            # All variations should produce the same cache key
            unique_keys = set(cache_keys)
            assert len(unique_keys) == 1, (
                f"Equivalent company variations produced different cache keys:\n" +
                "\n".join([
                    f"  '{name}' + '{domain}' -> '{key}'"
                    for (name, domain), key in zip(company_variations, cache_keys)
                ]) +
                f"\nExpected all variations to produce the same cache key, but got {len(unique_keys)} unique keys: {unique_keys}"
            )
            
            # Verify the normalized key is valid
            normalized_key = cache_keys[0]
            assert isinstance(normalized_key, str), "Cache key must be a string"
            assert normalized_key, "Cache key must not be empty"
            
        except ValueError:
            # Skip test cases that result in invalid inputs
            assume(False)
    
    @given(st.text(min_size=1, max_size=50, alphabet=string.ascii_letters))
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=1000)
    def test_property_6_name_only_consistency(self, company_name):
        """
        **Validates: Requirements 3.1, 3.4**
        
        Property 6: Normalization Consistency (Name Only)
        For any company name without domain, normalization should be consistent
        and produce the same result across multiple calls.
        """
        # Test with no domain
        try:
            key1 = normalize_company(company_name, None)
            key2 = normalize_company(company_name, "")
            key3 = normalize_company(company_name, "   ")
        except ValueError:
            # Some generated names (e.g. a bare legal suffix like "llc") have
            # no valid characters left after suffix stripping/normalization,
            # which normalize_company correctly rejects -- not a consistency
            # failure, so skip these inputs like the sibling property tests do.
            assume(False)
            return

        # All should produce the same result since invalid domains are treated as None
        assert key1 == key2 == key3, (
            f"Name-only normalization inconsistency:\n"
            f"Name: '{company_name}'\n"
            f"With None: '{key1}'\n"
            f"With empty string: '{key2}'\n"
            f"With whitespace: '{key3}'\n"
        )
    
    @given(st.text(min_size=1, max_size=20, alphabet=string.ascii_lowercase))
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=1000)
    def test_property_6_domain_only_consistency(self, domain_label):
        """
        **Validates: Requirements 3.1, 3.4**

        Property 6: Normalization Consistency (Domain Variations)
        For any domain with different protocol and www prefixes, normalization
        should produce consistent results.
        """
        # Build the domain label directly (rather than generating a full
        # string and filtering for "contains a dot with a 2+ char TLD"),
        # which guarantees every generated example is valid and avoids
        # Hypothesis's filter_too_much health check from excessive rejection.
        company_name = "TestCompany"
        base_domain = f"{domain_label}.com"
        
        # Test various domain formats
        domain_variations = [
            base_domain,
            f"www.{base_domain}",
            f"http://{base_domain}",
            f"https://{base_domain}",
            f"https://www.{base_domain}",
            f"https://www.{base_domain}/",
            f"  {base_domain}  ",
            base_domain.upper(),
        ]
        
        cache_keys = []
        for domain in domain_variations:
            try:
                key = normalize_company(company_name, domain)
                cache_keys.append(key)
            except ValueError:
                # Skip invalid domains
                continue
        
        if cache_keys:  # Only test if we have valid results
            unique_keys = set(cache_keys)
            assert len(unique_keys) == 1, (
                f"Domain format variations produced different cache keys:\n" +
                "\n".join([
                    f"  '{domain}' -> '{key}'" 
                    for domain, key in zip(domain_variations, cache_keys)
                    if key is not None
                ])
            )
    
    @given(st.lists(
        st.tuples(
            st.text(min_size=1, max_size=20, alphabet=string.ascii_letters),
            st.one_of(
                st.none(),
                st.text(min_size=3, max_size=20, alphabet=string.ascii_lowercase + ".")
                  .filter(lambda x: "." in x and len(x.split(".")[-1]) >= 2)
            )
        ),
        min_size=1,
        max_size=10
    ))
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=2000)
    def test_property_6_batch_consistency(self, company_list):
        """
        **Validates: Requirements 3.1, 3.4**
        
        Property 6: Normalization Consistency (Batch Processing)
        For any batch of companies processed multiple times, the normalization 
        results should be identical across all processing runs.
        """
        # First batch processing
        first_run_keys = []
        for name, domain in company_list:
            try:
                key = normalize_company(name, domain)
                first_run_keys.append(key)
            except ValueError:
                first_run_keys.append(None)  # Mark invalid entries
        
        # Second batch processing
        second_run_keys = []
        for name, domain in company_list:
            try:
                key = normalize_company(name, domain)
                second_run_keys.append(key)
            except ValueError:
                second_run_keys.append(None)  # Mark invalid entries
        
        # Results should be identical
        assert first_run_keys == second_run_keys, (
            f"Batch processing produced inconsistent results:\n"
            f"First run:  {first_run_keys}\n"
            f"Second run: {second_run_keys}\n"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])