"""
Export manager for the GCC Research Intelligence Platform.

Generates CSV and Excel exports of research results with proper formatting,
special-character preservation, and no data loss across any selected field.

Operates on plain row dictionaries rather than any specific entity type, so
it can be reused for both freshly-processed batch results and historical
search results without coupling to either caller's internal data model.

**Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5**
"""

from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any, Dict, List

import pandas as pd


def _strip_timezone(value: Any) -> Any:
    """
    Convert a timezone-aware datetime to a naive UTC datetime.

    Excel (via xlsxwriter/openpyxl) cannot represent timezone-aware
    datetimes and raises a ValueError if one reaches `to_excel`, so any
    tz-aware `created_at`/`updated_at` value (which is what production
    always produces, since the DB stores UTC-aware timestamps) must be
    normalized before it lands in the export DataFrame.
    """
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value

EXPORT_COLUMNS = [
    "company_name",
    "company_domain",
    "gcc_presence",
    "gcc_location",
    "suitability_score",
    "business_pain_points",
    "expansion_indicators",
    "hiring_signals",
    "research_summary",
    "is_cached",
    "error",
    "created_at",
]

COLUMN_HEADERS = {
    "company_name": "Company Name",
    "company_domain": "Company Domain",
    "gcc_presence": "GCC Presence",
    "gcc_location": "GCC Location",
    "suitability_score": "Suitability Score",
    "business_pain_points": "Business Pain Points",
    "expansion_indicators": "Expansion Indicators",
    "hiring_signals": "Hiring Signals",
    "research_summary": "Research Summary",
    "is_cached": "From Cache",
    "error": "Error",
    "created_at": "Researched At",
}


def rows_to_dataframe(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    """
    Convert a list of result row dicts into a DataFrame with a stable,
    complete column set and human-readable headers, ready for export.

    List-valued fields (pain points, indicators, signals) are joined with
    "; " so they survive flattening into CSV/Excel without losing data.

    **Validates: Requirements 8.1, 8.2, 8.3, 8.4**
    """
    normalized_rows = []
    for row in rows:
        normalized = {}
        for col in EXPORT_COLUMNS:
            value = row.get(col)
            if isinstance(value, list):
                value = "; ".join(str(v) for v in value)
            else:
                value = _strip_timezone(value)
            normalized[col] = value
        normalized_rows.append(normalized)

    df = pd.DataFrame(normalized_rows, columns=EXPORT_COLUMNS)
    df = df.rename(columns=COLUMN_HEADERS)
    return df


def generate_export_filename(base: str, extension: str) -> str:
    """
    Build a timestamped export filename, e.g. 'gcc_research_results_20260619_153000.csv'.

    **Validates: Requirements 8.5**
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    extension = extension.lstrip(".")
    return f"{base}_{timestamp}.{extension}"


def export_to_csv_bytes(rows: List[Dict[str, Any]]) -> bytes:
    """
    Export rows to CSV bytes (UTF-8 with BOM for Excel compatibility with
    special characters).

    **Validates: Requirements 8.1, 8.3**
    """
    df = rows_to_dataframe(rows)
    return df.to_csv(index=False).encode("utf-8-sig")


def export_to_excel_bytes(rows: List[Dict[str, Any]], sheet_name: str = "Research Results") -> bytes:
    """
    Export rows to a formatted Excel (.xlsx) file: bold header row, frozen
    header, and auto-sized columns for readability.

    **Validates: Requirements 8.2, 8.4**
    """
    df = rows_to_dataframe(rows)

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
        workbook = writer.book
        worksheet = writer.sheets[sheet_name]

        header_format = workbook.add_format(
            {"bold": True, "bg_color": "#D9E1F2", "border": 1, "text_wrap": True}
        )
        for col_idx, column_name in enumerate(df.columns):
            worksheet.write(0, col_idx, column_name, header_format)

            # Auto-size columns based on content, capped to keep the sheet usable.
            max_content_len = df[column_name].astype(str).map(len).max() if len(df) else 0
            width = min(max(max_content_len, len(column_name)) + 2, 60)
            worksheet.set_column(col_idx, col_idx, width)

        worksheet.freeze_panes(1, 0)

    return buffer.getvalue()
