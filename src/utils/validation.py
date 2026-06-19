"""
Input validation utilities for the GCC Research Intelligence Platform.

Provides comprehensive CSV/file validation, column auto-detection heuristics, 
data format validation, encoding support, and general input sanitization 
shared by the upload and UI components.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 14.1, 14.2**
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any

import pandas as pd

# Header keywords used for auto-detecting the company name / domain columns.
# Ordered roughly by specificity so the first match wins when several columns
# could plausibly qualify.
_NAME_COLUMN_KEYWORDS = [
    "company name",
    "company_name",
    "companyname",
    "organization name",
    "organisation name",
    "business name",
    "account name",
    "client name",
    "customer name",
    "firm name",
    "enterprise name",
    "corp name",
    "corporation name",
    "company",
    "organization", 
    "organisation",
    "business",
    "account",
    "client",
    "customer",
    "firm",
    "enterprise",
    "corp",
    "corporation",
    "entity",
    "vendor",
    "supplier",
    "name",
]

_DOMAIN_COLUMN_KEYWORDS = [
    "company domain",
    "company_domain",
    "companydomain",
    "domain name",
    "domain_name",
    "website url",
    "website_url",
    "web url",
    "web_url",
    "company website",
    "company_website",
    "business website", 
    "business_website",
    "homepage url",
    "homepage_url",
    "website",
    "web site",
    "web_site",
    "domain",
    "url",
    "site",
    "homepage",
    "web",
    "link",
]

MAX_FILE_SIZE_MB_DEFAULT = 50
SUPPORTED_ENCODINGS = ("utf-8", "utf-8-sig", "latin-1", "cp1252", "iso-8859-1")
SUPPORTED_FILE_EXTENSIONS = (".csv", ".txt")
MAX_COMPANY_NAME_LENGTH = 500
MAX_DOMAIN_LENGTH = 253  # RFC compliant domain name max length
MIN_ROWS_REQUIRED = 1
MAX_ROWS_ALLOWED = 50000

# Common data quality patterns
SUSPICIOUS_PATTERNS = {
    "test_data": [r"test", r"example", r"sample", r"dummy", r"fake"],
    "invalid_chars": [r"[^\w\s\-\.\,\'\&\(\)]", r"[\x00-\x1f\x7f-\x9f]"],  # Control characters
    "email_in_name": [r"@.*\.(com|org|net|edu|gov)"],
    "url_in_name": [r"https?://", r"www\."],
    "numeric_only": [r"^\d+$"],
}

# Domain validation patterns
DOMAIN_PATTERNS = {
    "valid": r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$",
    "ip_address": r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$",
    "suspicious": r"(localhost|127\.0\.0\.1|0\.0\.0\.0|example\.com|test\.com)"
}


class ValidationError(Exception):
    """Raised when uploaded data fails validation with a user-facing message."""

    def __init__(self, message: str, error_code: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.error_code = error_code or "VALIDATION_ERROR"
        self.details = details or {}


class DataQualityWarning(Exception):
    """Raised when data has quality issues but can still be processed."""

    def __init__(self, message: str, warning_type: str, affected_rows: List[int] = None):
        super().__init__(message)
        self.warning_type = warning_type
        self.affected_rows = affected_rows or []


@dataclass
class ColumnDetectionResult:
    """Result of attempting to auto-detect company name/domain columns."""

    name_column: Optional[str] = None
    domain_column: Optional[str] = None
    name_confident: bool = False
    domain_confident: bool = False

    @property
    def needs_manual_selection(self) -> bool:
        """True if the name column could not be confidently detected."""
        return not self.name_confident


@dataclass
class RowValidationError:
    """A single row-level validation failure, for surfacing specific errors."""

    row_index: int
    message: str
    error_type: str = "INVALID_DATA"
    column: Optional[str] = None
    value: Optional[str] = None


@dataclass
class DataQualityIssue:
    """A data quality concern that doesn't prevent processing but should be flagged."""

    row_index: int
    message: str
    issue_type: str
    column: str
    value: str
    severity: str = "warning"  # warning, info


@dataclass
class FileValidationResult:
    """Comprehensive validation outcome for an uploaded CSV file."""

    is_valid: bool
    errors: List[str] = field(default_factory=list)
    row_errors: List[RowValidationError] = field(default_factory=list)
    quality_issues: List[DataQualityIssue] = field(default_factory=list)
    valid_row_count: int = 0
    total_row_count: int = 0
    encoding_used: Optional[str] = None
    file_size_mb: float = 0.0
    warnings: List[str] = field(default_factory=list)

    @property
    def has_critical_errors(self) -> bool:
        """True if there are errors that prevent processing."""
        return bool(self.errors) or self.valid_row_count == 0

    @property 
    def has_quality_issues(self) -> bool:
        """True if there are data quality concerns."""
        return bool(self.quality_issues)

    @property
    def error_rate(self) -> float:
        """Percentage of rows with validation errors."""
        if self.total_row_count == 0:
            return 0.0
        return (len(self.row_errors) / self.total_row_count) * 100

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of validation results."""
        return {
            "is_valid": self.is_valid,
            "total_rows": self.total_row_count,
            "valid_rows": self.valid_row_count,
            "invalid_rows": len(self.row_errors),
            "error_rate": self.error_rate,
            "quality_issues": len(self.quality_issues),
            "encoding": self.encoding_used,
            "file_size_mb": self.file_size_mb,
            "warnings": len(self.warnings)
        }


def _normalize_header(header: str) -> str:
    """Lowercase and collapse whitespace/punctuation in a column header for matching."""
    return re.sub(r"[\s_\-]+", " ", str(header).strip().lower())


# Single-word tokens that strongly signal "this header is about a domain/
# website", used to stop a generic name keyword (e.g. "company") from
# hijacking a header like "Company Website" via a weak word-token match --
# see the guard in detect_company_columns below.
_DOMAIN_SIGNAL_WORDS = {"website", "domain", "url", "site", "web", "link", "homepage"}


def detect_company_columns(df: pd.DataFrame) -> ColumnDetectionResult:
    """
    Auto-detect the Company Name and Domain columns in an uploaded DataFrame.

    Matches column headers against known keyword patterns. A match against a
    multi-word, specific pattern (e.g. "company name") is considered
    confident; a match only against a generic single word (e.g. "name") is
    returned but flagged as not confident so callers can prompt for manual
    confirmation, per Requirement 2.3.

    Args:
        df: The parsed CSV data.

    Returns:
        ColumnDetectionResult with detected columns and confidence flags.

    **Validates: Requirements 2.2, 2.3**
    """
    headers = {col: _normalize_header(col) for col in df.columns}

    result = ColumnDetectionResult()

    # Define confidence levels based on keyword specificity
    high_confidence_name_keywords = [
        "company name", "company_name", "companyname", 
        "organization name", "organisation name", "business name"
    ]
    
    high_confidence_domain_keywords = [
        "company domain", "company_domain", "companydomain",
        "domain name", "domain_name", "website url", "website_url", 
        "company website", "company_website"
    ]

    # Try to find name column
    for keyword in _NAME_COLUMN_KEYWORDS:
        for original, normalized in headers.items():
            tokens = normalized.split()
            is_exact = normalized == keyword
            is_token_match = keyword in tokens
            if not (is_exact or is_token_match):
                continue
            # Guard: a weak, single-word match (e.g. generic keyword
            # "company" matching one token of "Company Website") shouldn't
            # claim a header that also clearly signals "domain/website" --
            # that signal is more specific and should be left for the
            # domain-detection pass below instead. Exact full-header matches
            # are always trusted, since they're literally the configured
            # phrase rather than an incidental shared word.
            if is_token_match and not is_exact and any(tok in _DOMAIN_SIGNAL_WORDS for tok in tokens):
                continue
            result.name_column = original
            # High confidence for specific multi-word terms or exact "company" match
            result.name_confident = (
                keyword in high_confidence_name_keywords or
                keyword == "company" or
                len(keyword.split()) > 1
            )
            # Lower confidence for generic single words like "name"
            if keyword in ["name"] and len(headers) > 3:
                result.name_confident = False
            break
        if result.name_column:
            break

    # Try to find domain column
    for keyword in _DOMAIN_COLUMN_KEYWORDS:
        for original, normalized in headers.items():
            if original == result.name_column:
                continue
            if normalized == keyword or keyword in normalized.split():
                result.domain_column = original
                # High confidence for specific domain-related terms
                result.domain_confident = (
                    keyword in high_confidence_domain_keywords or
                    keyword in ["domain", "website", "url"] or
                    len(keyword.split()) > 1
                )
                break
        if result.domain_column:
            break

    return result


def validate_file_extension(filename: str, allowed: Tuple[str, ...] = SUPPORTED_FILE_EXTENSIONS) -> None:
    """
    Validate that a filename has an allowed extension.

    Args:
        filename: Name of the uploaded file
        allowed: Tuple of allowed extensions

    Raises:
        ValidationError: If the file extension is not supported.

    **Validates: Requirements 14.1, 14.2**
    """
    if not filename:
        raise ValidationError(
            "No filename provided",
            error_code="MISSING_FILENAME"
        )
        
    if not any(filename.lower().endswith(ext) for ext in allowed):
        raise ValidationError(
            f"Unsupported file type for '{filename}'. "
            f"Please upload a file with one of these extensions: {', '.join(allowed)}",
            error_code="INVALID_FILE_EXTENSION",
            details={"filename": filename, "allowed_extensions": allowed}
        )


def validate_file_size(size_bytes: int, max_size_mb: int = MAX_FILE_SIZE_MB_DEFAULT) -> None:
    """
    Validate that a file does not exceed the configured maximum size.

    Args:
        size_bytes: File size in bytes
        max_size_mb: Maximum allowed size in megabytes

    Raises:
        ValidationError: If the file is too large.

    **Validates: Requirements 14.1, 14.2**
    """
    if size_bytes <= 0:
        raise ValidationError(
            "File appears to be empty or corrupted",
            error_code="EMPTY_FILE"
        )
        
    max_bytes = max_size_mb * 1024 * 1024
    if size_bytes > max_bytes:
        actual_mb = size_bytes / (1024 * 1024)
        raise ValidationError(
            f"File is too large ({actual_mb:.1f} MB). "
            f"Maximum allowed size is {max_size_mb} MB. "
            f"Please reduce the file size or split into smaller files.",
            error_code="FILE_TOO_LARGE",
            details={"actual_size_mb": actual_mb, "max_size_mb": max_size_mb}
        )


def read_csv_with_fallback_encoding(file_obj) -> pd.DataFrame:
    """
    Read a CSV file, trying a sequence of common encodings with enhanced error handling.

    Streamlit's UploadedFile is a BytesIO-like object that can be re-read by
    seeking back to position 0 between attempts.

    Args:
        file_obj: File-like object to read from

    Returns:
        pandas DataFrame with the parsed CSV data

    Raises:
        ValidationError: If the file cannot be parsed with any supported encoding.

    **Validates: Requirements 2.5, 14.1, 14.2**
    """
    last_error: Optional[Exception] = None
    encoding_attempted = []
    
    for encoding in SUPPORTED_ENCODINGS:
        try:
            file_obj.seek(0)
            encoding_attempted.append(encoding)
            
            # Try to read with current encoding
            df = pd.read_csv(file_obj, encoding=encoding)
            
            # Validate basic structure
            if df.empty:
                raise ValidationError(
                    "The uploaded CSV file contains no data rows. Please ensure your file has data.",
                    error_code="EMPTY_DATA"
                )
                
            if len(df.columns) == 0:
                raise ValidationError(
                    "The uploaded CSV file has no columns. Please check the file format.",
                    error_code="NO_COLUMNS"
                )
                
            # Check for reasonable column count
            if len(df.columns) > 100:
                raise ValidationError(
                    f"CSV file has too many columns ({len(df.columns)}). "
                    f"Please ensure this is a properly formatted CSV file.",
                    error_code="TOO_MANY_COLUMNS"
                )
            
            # Check row count limits    
            if len(df) > MAX_ROWS_ALLOWED:
                raise ValidationError(
                    f"CSV file has too many rows ({len(df):,}). "
                    f"Maximum allowed is {MAX_ROWS_ALLOWED:,} rows. "
                    f"Please split your data into smaller files.",
                    error_code="TOO_MANY_ROWS",
                    details={"actual_rows": len(df), "max_rows": MAX_ROWS_ALLOWED}
                )
                
            # Success - add encoding info to dataframe metadata if possible
            if hasattr(df, 'attrs'):
                df.attrs['encoding_used'] = encoding
                
            return df
            
        except ValidationError:
            # Re-raise validation errors immediately
            raise
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
        except pd.errors.EmptyDataError:
            raise ValidationError(
                "The uploaded file appears to be empty or contains no readable data.",
                error_code="EMPTY_DATA"
            )
        except pd.errors.ParserError as exc:
            last_error = exc
            # Try next encoding for parser errors
            continue
        except Exception as exc:
            last_error = exc
            continue

    # If we get here, all encodings failed
    raise ValidationError(
        f"Unable to read the CSV file with any supported encoding ({', '.join(encoding_attempted)}). "
        f"The file may be corrupted, in a different format, or use an unsupported text encoding. "
        f"Please save the file as a UTF-8 encoded CSV and try again.",
        error_code="ENCODING_ERROR",
        details={"encodings_tried": encoding_attempted, "last_error": str(last_error)}
    )


def _validate_company_name(value: str, row_idx: int) -> Tuple[Optional[RowValidationError], List[DataQualityIssue]]:
    """
    Validate a single company name value with comprehensive checks.

    Args:
        value: The company name to validate
        row_idx: Row index for error reporting

    Returns:
        Tuple of (validation error if any, list of quality issues)

    **Validates: Requirements 2.4, 2.5, 14.2**
    """
    issues = []
    
    # Basic empty/null check
    if pd.isna(value) or not str(value).strip():
        return RowValidationError(
            row_index=row_idx,
            message="Company name is empty or missing",
            error_type="EMPTY_NAME",
            column="company_name",
            value=str(value) if value else "null"
        ), issues
    
    name = str(value).strip()
    
    # Length validation
    if len(name) > MAX_COMPANY_NAME_LENGTH:
        return RowValidationError(
            row_index=row_idx,
            message=f"Company name is too long ({len(name)} characters, max {MAX_COMPANY_NAME_LENGTH})",
            error_type="NAME_TOO_LONG",
            column="company_name",
            value=name[:50] + "..." if len(name) > 50 else name
        ), issues
    
    if len(name) < 2:
        return RowValidationError(
            row_index=row_idx,
            message="Company name is too short (minimum 2 characters)",
            error_type="NAME_TOO_SHORT", 
            column="company_name",
            value=name
        ), issues
    
    # Check for suspicious patterns
    name_lower = name.lower()
    
    # Test data detection
    for pattern in SUSPICIOUS_PATTERNS["test_data"]:
        if re.search(pattern, name_lower):
            issues.append(DataQualityIssue(
                row_index=row_idx,
                message=f"Company name appears to be test/example data: '{name}'",
                issue_type="TEST_DATA",
                column="company_name",
                value=name,
                severity="warning"
            ))
            
    # Invalid characters
    for pattern in SUSPICIOUS_PATTERNS["invalid_chars"]:
        if re.search(pattern, name):
            issues.append(DataQualityIssue(
                row_index=row_idx,
                message=f"Company name contains unusual characters: '{name}'",
                issue_type="INVALID_CHARS",
                column="company_name", 
                value=name,
                severity="warning"
            ))
    
    # Email in name field
    for pattern in SUSPICIOUS_PATTERNS["email_in_name"]:
        if re.search(pattern, name_lower):
            issues.append(DataQualityIssue(
                row_index=row_idx,
                message=f"Company name appears to contain an email address: '{name}'",
                issue_type="EMAIL_IN_NAME",
                column="company_name",
                value=name,
                severity="warning"
            ))
    
    # URL in name field  
    for pattern in SUSPICIOUS_PATTERNS["url_in_name"]:
        if re.search(pattern, name_lower):
            issues.append(DataQualityIssue(
                row_index=row_idx,
                message=f"Company name appears to contain a URL: '{name}'",
                issue_type="URL_IN_NAME", 
                column="company_name",
                value=name,
                severity="warning"
            ))
    
    # Numbers only
    for pattern in SUSPICIOUS_PATTERNS["numeric_only"]:
        if re.search(pattern, name.strip()):
            return RowValidationError(
                row_index=row_idx,
                message=f"Company name cannot be only numbers: '{name}'",
                error_type="NUMERIC_ONLY_NAME",
                column="company_name",
                value=name
            ), issues
    
    return None, issues


def _validate_domain(value: str, row_idx: int) -> Tuple[Optional[RowValidationError], List[DataQualityIssue]]:
    """
    Validate a single domain value with comprehensive checks.

    Args:
        value: The domain to validate  
        row_idx: Row index for error reporting

    Returns:
        Tuple of (validation error if any, list of quality issues)

    **Validates: Requirements 2.4, 2.5, 14.2**
    """
    issues = []
    
    # Domain is optional, so empty/null is acceptable
    if pd.isna(value) or not str(value).strip():
        return None, issues
        
    domain = str(value).strip().lower()
    
    # Remove common prefixes
    domain = re.sub(r'^https?://', '', domain)
    domain = re.sub(r'^www\.', '', domain)
    domain = domain.rstrip('/')
    
    if not domain:
        return None, issues
    
    # Length validation
    if len(domain) > MAX_DOMAIN_LENGTH:
        return RowValidationError(
            row_index=row_idx,
            message=f"Domain is too long ({len(domain)} characters, max {MAX_DOMAIN_LENGTH})",
            error_type="DOMAIN_TOO_LONG",
            column="domain",
            value=domain
        ), issues
    
    # Format validation
    if not re.match(DOMAIN_PATTERNS["valid"], domain):
        return RowValidationError(
            row_index=row_idx,
            message=f"Domain format is invalid: '{domain}'",
            error_type="INVALID_DOMAIN_FORMAT",
            column="domain", 
            value=domain
        ), issues
    
    # IP address check
    if re.match(DOMAIN_PATTERNS["ip_address"], domain):
        issues.append(DataQualityIssue(
            row_index=row_idx,
            message=f"Domain is an IP address rather than domain name: '{domain}'",
            issue_type="IP_ADDRESS_DOMAIN",
            column="domain",
            value=domain,
            severity="info"
        ))
    
    # Suspicious domains
    if re.search(DOMAIN_PATTERNS["suspicious"], domain):
        issues.append(DataQualityIssue(
            row_index=row_idx,
            message=f"Domain appears to be test/local data: '{domain}'",
            issue_type="SUSPICIOUS_DOMAIN",
            column="domain", 
            value=domain,
            severity="warning"
        ))
    
    return None, issues
def validate_selected_columns(
    df: pd.DataFrame,
    name_column: str,
    domain_column: Optional[str] = None,
) -> FileValidationResult:
    """
    Comprehensive validation of selected columns with detailed error reporting.

    Validates that selected columns contain usable data with specific error
    messages for different types of validation failures. Performs data quality
    checks and provides actionable feedback for data issues.

    Args:
        df: The parsed CSV data.
        name_column: Column to use as the company name.
        domain_column: Column to use as the company domain (optional).

    Returns:
        FileValidationResult with comprehensive validation details.

    **Validates: Requirements 2.4, 2.5, 14.1, 14.2**
    """
    errors: List[str] = []
    row_errors: List[RowValidationError] = []
    quality_issues: List[DataQualityIssue] = []
    warnings: List[str] = []
    
    # Basic column existence checks
    if name_column not in df.columns:
        errors.append(
            f"Selected company name column '{name_column}' was not found in the uploaded file. "
            f"Available columns: {', '.join(df.columns.tolist())}"
        )
        return FileValidationResult(
            is_valid=False, 
            errors=errors, 
            total_row_count=len(df),
            file_size_mb=0.0
        )

    if domain_column is not None and domain_column not in df.columns:
        errors.append(
            f"Selected domain column '{domain_column}' was not found in the uploaded file. "
            f"Available columns: {', '.join(df.columns.tolist())}"
        )
        return FileValidationResult(
            is_valid=False, 
            errors=errors, 
            total_row_count=len(df),
            file_size_mb=0.0
        )

    total_rows = len(df)
    if total_rows == 0:
        errors.append("The uploaded file contains no data rows to process.")
        return FileValidationResult(
            is_valid=False, 
            errors=errors, 
            total_row_count=0,
            file_size_mb=0.0
        )
    
    if total_rows < MIN_ROWS_REQUIRED:
        errors.append(
            f"File must contain at least {MIN_ROWS_REQUIRED} data row(s). "
            f"Found {total_rows} rows."
        )
        return FileValidationResult(
            is_valid=False, 
            errors=errors, 
            total_row_count=total_rows,
            file_size_mb=0.0
        )

    # Validate each row
    valid_count = 0
    
    for idx in range(total_rows):
        try:
            name_value = df.iloc[idx][name_column]
            
            # Validate company name
            name_error, name_issues = _validate_company_name(name_value, idx)
            if name_error:
                row_errors.append(name_error)
            else:
                valid_count += 1
                quality_issues.extend(name_issues)
            
            # Validate domain if column is selected
            if domain_column is not None:
                domain_value = df.iloc[idx][domain_column]
                domain_error, domain_issues = _validate_domain(domain_value, idx)
                if domain_error:
                    row_errors.append(domain_error)
                else:
                    quality_issues.extend(domain_issues)
                    
        except Exception as exc:
            row_errors.append(RowValidationError(
                row_index=idx,
                message=f"Unexpected error processing row: {str(exc)}",
                error_type="PROCESSING_ERROR",
                column="unknown", 
                value="unknown"
            ))

    # Generate warnings based on data quality
    if valid_count == 0:
        errors.append(
            f"No valid company records found in column '{name_column}'. "
            f"Please verify that the selected column contains proper company names."
        )
    
    # Warning for high error rate
    error_rate = (len(row_errors) / total_rows) * 100 if total_rows > 0 else 0
    if error_rate > 50:
        warnings.append(
            f"High error rate detected ({error_rate:.1f}% of rows have issues). "
            f"Please review your data quality."
        )
    
    # Warning for many quality issues
    if len(quality_issues) > total_rows * 0.3:
        warnings.append(
            f"Multiple data quality concerns detected in {len(quality_issues)} cases. "
            f"Results may need manual review."
        )

    return FileValidationResult(
        is_valid=len(errors) == 0,
        errors=errors,
        row_errors=row_errors,
        quality_issues=quality_issues,
        valid_row_count=valid_count,
        total_row_count=total_rows,
        encoding_used=getattr(df, 'attrs', {}).get('encoding_used'),
        file_size_mb=0.0,  # Will be set by caller if available
        warnings=warnings
    )


def sanitize_text(value: Optional[str], max_length: int = 1000) -> str:
    """
    Sanitize free-text input for safe storage and display.

    Strips control characters and truncates to a maximum length. Uses
    comprehensive Unicode normalization and security filtering.

    Args:
        value: Raw text value (may be None).
        max_length: Maximum allowed length after sanitization.

    Returns:
        A cleaned string, or an empty string if value was None/blank.

    **Validates: Requirements 14.1, 14.2**
    """
    if value is None:
        return ""
        
    text = str(value)
    
    # Unicode normalization (NFC form)
    text = unicodedata.normalize('NFC', text)
    
    # Remove control characters (keep tab/newline/CR and all printable/unicode text)
    text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", text)
    
    # Remove other potentially problematic Unicode categories
    text = ''.join(char for char in text 
                   if unicodedata.category(char) not in ['Cc', 'Cf', 'Cs', 'Co', 'Cn'])
    
    text = text.strip()
    return text[:max_length]


def validate_csv_structure(df: pd.DataFrame) -> List[str]:
    """
    Validate the overall structure and quality of a CSV DataFrame.
    
    Args:
        df: DataFrame to validate
        
    Returns:
        List of structural issues found
        
    **Validates: Requirements 2.4, 2.5, 14.2**
    """
    issues = []
    
    # Check for duplicate column names
    if len(df.columns) != len(set(df.columns)):
        duplicates = [col for col in df.columns if list(df.columns).count(col) > 1]
        issues.append(f"Duplicate column names found: {', '.join(set(duplicates))}")
    
    # Check for completely empty columns (handle duplicate columns carefully)
    empty_cols = []
    processed_cols = set()
    
    for col in df.columns:
        if col not in processed_cols:
            try:
                if df[col].isna().all():
                    empty_cols.append(col)
                processed_cols.add(col)
            except ValueError:
                # Handle duplicate column issue by checking if all values are null
                col_data = df.loc[:, col]  # This gets all columns with this name
                if hasattr(col_data, 'isna'):
                    if col_data.isna().all().all() if hasattr(col_data.isna().all(), 'all') else col_data.isna().all():
                        empty_cols.append(col)
                processed_cols.add(col)
    
    if empty_cols:
        issues.append(f"Completely empty columns found: {', '.join(empty_cols)}")
    
    # Check for columns with only whitespace (handle duplicates)
    whitespace_cols = []
    processed_cols = set()
    
    for col in df.columns:
        if col not in processed_cols:
            try:
                if df[col].dtype == 'object':  # String columns
                    col_data = df[col].dropna().astype(str).str.strip()
                    if len(col_data) > 0 and col_data.eq('').all():
                        whitespace_cols.append(col)
                processed_cols.add(col)
            except (ValueError, AttributeError):
                # Skip problematic columns
                processed_cols.add(col)
                
    if whitespace_cols:
        issues.append(f"Columns containing only whitespace: {', '.join(whitespace_cols)}")
    
    # Check for suspicious column names
    suspicious_names = [col for col in set(df.columns)  # Use set to avoid duplicates
                       if any(pattern in col.lower() for pattern in ['unnamed', 'column'])]
    if suspicious_names:
        issues.append(f"Potentially auto-generated column names: {', '.join(suspicious_names)}")
    
    return issues


def validate_data_completeness(df: pd.DataFrame, required_columns: List[str]) -> Dict[str, Any]:
    """
    Analyze data completeness across required columns.
    
    Args:
        df: DataFrame to analyze
        required_columns: List of column names that should have data
        
    Returns:
        Dictionary with completeness statistics
        
    **Validates: Requirements 2.4, 2.5**
    """
    stats = {
        'total_rows': len(df),
        'column_completeness': {},
        'overall_completeness': 0.0,
        'rows_with_all_required': 0
    }
    
    for col in required_columns:
        if col in df.columns:
            non_null_count = df[col].notna().sum()
            non_empty_count = df[col].dropna().astype(str).str.strip().ne('').sum()
            
            stats['column_completeness'][col] = {
                'non_null': non_null_count,
                'non_empty': non_empty_count,
                'null_rate': (len(df) - non_null_count) / len(df) * 100,
                'empty_rate': (len(df) - non_empty_count) / len(df) * 100
            }
    
    # Count rows with all required data
    if required_columns:
        mask = pd.Series([True] * len(df))
        for col in required_columns:
            if col in df.columns:
                mask &= df[col].notna() & (df[col].astype(str).str.strip() != '')
        stats['rows_with_all_required'] = mask.sum()
        stats['overall_completeness'] = (stats['rows_with_all_required'] / len(df)) * 100
    
    return stats


def get_validation_summary(result: FileValidationResult) -> str:
    """
    Generate a human-readable summary of validation results.
    
    Args:
        result: FileValidationResult to summarize
        
    Returns:
        Formatted summary string
        
    **Validates: Requirements 14.1**
    """
    if not result.is_valid:
        return f"❌ Validation failed with {len(result.errors)} critical error(s)"
    
    summary_parts = [
        f"✅ Validation passed for {result.valid_row_count}/{result.total_row_count} rows"
    ]
    
    if result.row_errors:
        summary_parts.append(f"⚠️ {len(result.row_errors)} rows skipped due to data issues")
    
    if result.quality_issues:
        summary_parts.append(f"📋 {len(result.quality_issues)} data quality concerns noted")
    
    if result.warnings:
        summary_parts.append(f"⚠️ {len(result.warnings)} warning(s)")
    
    if result.encoding_used:
        summary_parts.append(f"📄 Encoding: {result.encoding_used}")
    
    return " | ".join(summary_parts)
