"""
CSV upload and validation component for the GCC Research Intelligence Platform.

Renders the file upload widget, runs auto-detection of the Company Name /
Domain columns, falls back to manual selection when detection isn't
confident, validates the selected columns, and converts valid rows into
CompanyRecord objects ready for the research pipeline.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import pandas as pd
import streamlit as st

from ..core.normalization import normalize_company
from ..models.entities import CompanyRecord
from ..utils.config import get_config
from ..utils.logging import get_logger
from ..utils.validation import (
    ColumnDetectionResult,
    FileValidationResult,
    ValidationError,
    DataQualityIssue,
    detect_company_columns,
    read_csv_with_fallback_encoding,
    validate_file_extension,
    validate_file_size,
    validate_selected_columns,
    validate_csv_structure,
    get_validation_summary,
)

logger = get_logger(__name__)

# Streamlit session_state keys used by this component.
UPLOAD_DF_KEY = "gcc_upload_df"
UPLOAD_FILENAME_KEY = "gcc_upload_filename"
UPLOAD_RECORDS_KEY = "gcc_upload_records"
UPLOAD_NAME_COL_KEY = "gcc_upload_name_col"
UPLOAD_DOMAIN_COL_KEY = "gcc_upload_domain_col"


@dataclass
class UploadOutcome:
    """Result of a completed, validated upload ready for processing."""

    company_records: List[CompanyRecord]
    skipped_row_count: int
    total_row_count: int
    name_column: str
    domain_column: Optional[str]
    source_filename: str


def _build_company_records(
    df: pd.DataFrame,
    name_column: str,
    domain_column: Optional[str],
    validation: FileValidationResult,
) -> List[CompanyRecord]:
    """
    Convert valid rows of the uploaded DataFrame into CompanyRecord objects.

    Rows already flagged as invalid (empty company name) by
    ``validate_selected_columns`` are skipped. Rows whose company name
    happens to fail normalization for some other reason (e.g. only
    punctuation) are logged and skipped rather than crashing the whole
    upload, since one malformed row shouldn't block the rest of the batch.

    **Validates: Requirements 2.4, 2.5, 3.1, 3.2, 3.3, 3.4**
    """
    invalid_row_indices = {err.row_index for err in validation.row_errors}
    records: List[CompanyRecord] = []

    for idx, row in df.iterrows():
        if idx in invalid_row_indices:
            continue

        raw_name = str(row[name_column]).strip()
        raw_domain = None
        if domain_column is not None:
            domain_value = row[domain_column]
            if pd.notna(domain_value) and str(domain_value).strip():
                raw_domain = str(domain_value).strip()

        try:
            normalized_key = normalize_company(raw_name, raw_domain)
            record = CompanyRecord(
                name=raw_name,
                domain=raw_domain,
                normalized_key=normalized_key,
                row_index=int(idx),
            )
            records.append(record)
        except ValueError as exc:
            logger.warning(f"Skipping row {idx} during upload processing: {exc}")
            continue

    return records


def render_upload_widget() -> Optional[UploadOutcome]:
    """
    Render the full upload workflow: file picker, column detection/selection,
    validation, and CompanyRecord construction.

    Returns:
        UploadOutcome once the user has a fully validated set of company
        records ready for research, otherwise None (still mid-workflow).

    **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**
    """
    config = get_config()

    uploaded_file = st.file_uploader(
        "📁 Choose a CSV file or drag and drop",
        type=["csv"],
        help="Upload a CSV file containing company data for GCC research analysis. "
             "Drag and drop files directly or click to browse.",
        accept_multiple_files=False,
        key="csv_file_uploader",
        label_visibility="visible"
    )

    if uploaded_file is None:
        # Clear any stale state from a previous upload so old results don't
        # leak into a fresh session.
        for key in (UPLOAD_DF_KEY, UPLOAD_FILENAME_KEY, UPLOAD_RECORDS_KEY):
            st.session_state.pop(key, None)
        return None

    try:
        validate_file_extension(uploaded_file.name)
        validate_file_size(uploaded_file.size, max_size_mb=config.app.max_upload_size_mb)
    except ValidationError as exc:
        st.error(f"❌ **File Validation Failed**")
        st.error(f"• {exc}")
        if hasattr(exc, 'details') and exc.details:
            with st.expander("🔍 Error Details", expanded=False):
                for key, value in exc.details.items():
                    st.text(f"{key}: {value}")
        return None

    # Only re-parse the file when a new one is uploaded (Streamlit reruns
    # this function on every interaction, so cache the parsed DataFrame).
    if st.session_state.get(UPLOAD_FILENAME_KEY) != uploaded_file.name:
        try:
            df = read_csv_with_fallback_encoding(uploaded_file)
            
            # Perform structural validation
            structural_issues = validate_csv_structure(df)
            if structural_issues:
                st.warning("📋 **Data Structure Issues Detected:**")
                for issue in structural_issues:
                    st.warning(f"• {issue}")
                    
        except ValidationError as exc:
            st.error(f"❌ **File Reading Failed**")
            st.error(f"• {exc}")
            if hasattr(exc, 'details') and exc.details:
                with st.expander("🔍 Error Details", expanded=False):
                    for key, value in exc.details.items():
                        st.text(f"{key}: {value}")
            return None

        st.session_state[UPLOAD_DF_KEY] = df
        st.session_state[UPLOAD_FILENAME_KEY] = uploaded_file.name
        st.session_state.pop(UPLOAD_NAME_COL_KEY, None)
        st.session_state.pop(UPLOAD_DOMAIN_COL_KEY, None)
        logger.info(f"Parsed uploaded file '{uploaded_file.name}' with {len(df)} rows, {len(df.columns)} columns")

    df: pd.DataFrame = st.session_state[UPLOAD_DF_KEY]

    # Calculate and store file size info
    file_size_mb = uploaded_file.size / (1024 * 1024)
    
    st.success(f"✅ Loaded {len(df):,} rows, {len(df.columns)} columns from '{uploaded_file.name}' ({file_size_mb:.1f} MB)")
    with st.expander("🔍 Preview uploaded data", expanded=False):
        st.dataframe(df.head(10), use_container_width=True)
        
        # Show column info
        col_info = []
        for col in df.columns:
            non_null = df[col].notna().sum()
            col_info.append(f"{col}: {non_null}/{len(df)} values ({(non_null/len(df)*100):.1f}%)")
        st.caption("Column completeness: " + " | ".join(col_info[:5]))
        if len(df.columns) > 5:
            st.caption(f"... and {len(df.columns)-5} more columns")

    detection: ColumnDetectionResult = detect_company_columns(df)
    columns = list(df.columns)

    # Show auto-detection results
    if detection.name_column or detection.domain_column:
        st.info(
            f"🎯 **Auto-detection results:** "
            f"Name column: {detection.name_column or 'Not found'} "
            f"{'✓' if detection.name_confident else '?'}, "
            f"Domain column: {detection.domain_column or 'Not found'} "
            f"{'✓' if detection.domain_confident else '?'}"
        )

    st.markdown("#### 📋 Column Selection")
    
    # Add helpful instructions
    if not detection.name_confident:
        st.warning(
            "⚠️ **Manual selection required** - Please verify the column selections below. "
            "Auto-detection was not confident about the company name column."
        )
    elif detection.name_confident and detection.domain_confident:
        st.success(
            "✅ **Auto-detection successful** - Columns detected automatically. "
            "You can change the selections below if needed."
        )
    
    col1, col2 = st.columns(2)

    with col1:
        default_name = detection.name_column if detection.name_column in columns else columns[0]
        name_column = st.selectbox(
            "🏢 Company Name column",
            options=columns,
            index=columns.index(default_name),
            help="Select the column containing company names. This field is required.",
            key="gcc_name_column_select",
        )
        
        # Show sample values from selected column
        if name_column and not df[name_column].empty:
            sample_values = df[name_column].dropna().head(3).tolist()
            if sample_values:
                st.caption(f"Sample values: {', '.join(str(v) for v in sample_values)}")

    with col2:
        domain_options = ["(none)"] + columns
        default_domain = (
            detection.domain_column if detection.domain_column in columns else "(none)"
        )
        domain_choice = st.selectbox(
            "🌐 Company Domain column (optional)",
            options=domain_options,
            index=domain_options.index(default_domain),
            help="Select the column containing company websites/domains, if available. This field is optional.",
            key="gcc_domain_column_select",
        )
        domain_column = None if domain_choice == "(none)" else domain_choice
        
        # Show sample values from selected domain column
        if domain_column and not df[domain_column].empty:
            sample_values = df[domain_column].dropna().head(3).tolist()
            if sample_values:
                st.caption(f"Sample values: {', '.join(str(v) for v in sample_values)}")

    validation = validate_selected_columns(df, name_column, domain_column)
    
    # Store file size in validation result
    validation.file_size_mb = file_size_mb

    # Enhanced validation feedback with comprehensive error handling
    if validation.has_critical_errors:
        st.error("❌ **Critical Validation Errors**")
        for error in validation.errors:
            st.error(f"• {error}")
        return None

    # Show validation summary
    summary = get_validation_summary(validation)
    if validation.is_valid:
        if validation.warnings or validation.quality_issues:
            st.warning("⚠️ " + summary)
        else:
            st.success("✅ " + summary)
    
    # Display warnings
    if validation.warnings:
        st.warning("⚠️ **Data Quality Warnings:**")
        for warning in validation.warnings:
            st.warning(f"• {warning}")

    # Show row-level validation errors
    if validation.row_errors:
        error_count = len(validation.row_errors)
        valid_count = validation.valid_row_count
        total_count = validation.total_row_count
        
        if error_count == total_count:
            st.error(f"❌ **All rows have validation errors** - No valid companies found.")
            with st.expander(f"📋 View all {min(error_count, 20)} validation errors", expanded=True):
                for i, row_err in enumerate(validation.row_errors[:20]):
                    row_data = df.iloc[row_err.row_index]
                    name_value = row_data.get(name_column, "N/A")
                    domain_value = row_data.get(domain_column, "N/A") if domain_column else "N/A"
                    
                    st.text(f"Row {row_err.row_index + 1} [{row_err.error_type}]: {row_err.message}")
                    st.caption(f"   Data: '{name_value}' | '{domain_value}'")
                
                if error_count > 20:
                    st.text(f"... and {error_count - 20} more validation errors")
            return None
        else:
            st.info(
                f"📊 **Data Processing Summary:** {valid_count:,} valid companies found, "
                f"{error_count:,} rows will be skipped ({(valid_count/total_count*100):.1f}% success rate)"
            )
            
            with st.expander(f"📋 View {min(error_count, 10)} skipped rows", expanded=False):
                # Group errors by type for better display
                error_groups = {}
                for row_err in validation.row_errors:
                    if row_err.error_type not in error_groups:
                        error_groups[row_err.error_type] = []
                    error_groups[row_err.error_type].append(row_err)
                
                for error_type, errors in error_groups.items():
                    st.write(f"**{error_type.replace('_', ' ').title()}:** {len(errors)} rows")
                    for i, row_err in enumerate(errors[:3]):  # Show max 3 examples per type
                        row_data = df.iloc[row_err.row_index]
                        name_value = row_data.get(name_column, "N/A")
                        domain_value = row_data.get(domain_column, "N/A") if domain_column else "N/A"
                        st.caption(f"   Row {row_err.row_index + 1}: '{name_value}' | '{domain_value}' - {row_err.message}")
                    if len(errors) > 3:
                        st.caption(f"   ... and {len(errors) - 3} more similar errors")
                
                if error_count > 10:
                    st.text(f"Total: {error_count} rows will be skipped")

    # Show data quality issues  
    if validation.quality_issues:
        quality_count = len(validation.quality_issues)
        st.info(f"📋 **Data Quality Report:** {quality_count} potential issues identified")
        
        with st.expander(f"📋 View data quality concerns ({quality_count} items)", expanded=False):
            # Group quality issues by type
            issue_groups = {}
            for issue in validation.quality_issues:
                if issue.issue_type not in issue_groups:
                    issue_groups[issue.issue_type] = []
                issue_groups[issue.issue_type].append(issue)
            
            for issue_type, issues in issue_groups.items():
                severity_icon = "⚠️" if issues[0].severity == "warning" else "ℹ️"
                st.write(f"{severity_icon} **{issue_type.replace('_', ' ').title()}:** {len(issues)} occurrences")
                
                for i, issue in enumerate(issues[:2]):  # Show max 2 examples per type  
                    st.caption(f"   Row {issue.row_index + 1}: {issue.message}")
                if len(issues) > 2:
                    st.caption(f"   ... and {len(issues) - 2} more similar issues")
            
            st.caption("💡 These issues don't prevent processing but may affect research quality.")

    records = _build_company_records(df, name_column, domain_column, validation)
    st.session_state[UPLOAD_RECORDS_KEY] = records
    st.session_state[UPLOAD_NAME_COL_KEY] = name_column
    st.session_state[UPLOAD_DOMAIN_COL_KEY] = domain_column

    # Success message with statistics
    if records:
        st.success(
            f"🎉 **Ready to process {len(records)} companies!**"
        )
        
        # Show processing preview
        with st.expander("📊 Processing Preview", expanded=False):
            preview_df = pd.DataFrame([
                {
                    "Company Name": record.name[:50] + "..." if len(record.name) > 50 else record.name,
                    "Domain": record.domain or "(none)",
                    "Normalized Key": record.normalized_key
                }
                for record in records[:5]
            ])
            st.dataframe(preview_df, use_container_width=True)
            if len(records) > 5:
                st.caption(f"Showing first 5 of {len(records)} companies...")
    else:
        st.error("❌ No valid company records could be created from the uploaded data.")

    return UploadOutcome(
        company_records=records,
        skipped_row_count=len(validation.row_errors),
        total_row_count=validation.total_row_count,
        name_column=name_column,
        domain_column=domain_column,
        source_filename=uploaded_file.name,
    )
