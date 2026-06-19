"""
Unit tests for the export manager (CSV/Excel generation).

Tests cover column completeness, list-field flattening, filename
generation, and that no data is lost across the export pipeline.

**Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5**
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

import io
import re
from datetime import datetime, timezone

import pandas as pd
import pytest

from src.core.export_manager import (
    COLUMN_HEADERS,
    EXPORT_COLUMNS,
    export_to_csv_bytes,
    export_to_excel_bytes,
    generate_export_filename,
    rows_to_dataframe,
)


def _sample_row(**overrides):
    row = {
        "company_name": "Microsoft Corporation",
        "company_domain": "microsoft.com",
        "gcc_presence": True,
        "gcc_location": "Hyderabad, India",
        "suitability_score": 8,
        "business_pain_points": ["High operational costs", "Talent shortage"],
        "expansion_indicators": ["Recent funding"],
        "hiring_signals": ["Active job postings"],
        "research_summary": "Strong candidate with existing GCC presence.",
        "is_cached": False,
        "error": None,
        "created_at": datetime(2026, 6, 19, 12, 0, 0, tzinfo=timezone.utc),
    }
    row.update(overrides)
    return row


class TestRowsToDataframe:
    def test_includes_all_export_columns(self):
        df = rows_to_dataframe([_sample_row()])
        expected_headers = {COLUMN_HEADERS[col] for col in EXPORT_COLUMNS}
        assert set(df.columns) == expected_headers

    def test_list_fields_flattened_with_no_data_loss(self):
        df = rows_to_dataframe([_sample_row()])
        pain_points_col = COLUMN_HEADERS["business_pain_points"]
        value = df.iloc[0][pain_points_col]
        assert "High operational costs" in value
        assert "Talent shortage" in value
        assert "; " in value

    def test_missing_keys_filled_with_none(self):
        # A row missing several fields entirely (e.g. a failed-research row)
        # should still produce every column, not raise a KeyError.
        sparse_row = {"company_name": "Acme Inc", "error": "API timeout"}
        df = rows_to_dataframe([sparse_row])
        assert len(df.columns) == len(EXPORT_COLUMNS)
        assert df.iloc[0][COLUMN_HEADERS["error"]] == "API timeout"
        assert pd.isna(df.iloc[0][COLUMN_HEADERS["suitability_score"]])

    def test_empty_rows_produces_empty_dataframe_with_headers(self):
        df = rows_to_dataframe([])
        assert len(df) == 0
        assert len(df.columns) == len(EXPORT_COLUMNS)

    def test_multiple_rows_preserve_order(self):
        rows = [_sample_row(company_name="Alpha"), _sample_row(company_name="Beta")]
        df = rows_to_dataframe(rows)
        assert list(df[COLUMN_HEADERS["company_name"]]) == ["Alpha", "Beta"]


class TestGenerateExportFilename:
    def test_filename_format(self):
        filename = generate_export_filename("gcc_research_results", "csv")
        assert re.match(r"^gcc_research_results_\d{8}_\d{6}\.csv$", filename)

    def test_extension_dot_stripped(self):
        filename = generate_export_filename("base", ".xlsx")
        assert filename.endswith(".xlsx")
        assert ".." not in filename

    def test_different_bases_produce_different_prefixes(self):
        csv_name = generate_export_filename("gcc_research_history", "csv")
        assert csv_name.startswith("gcc_research_history_")


class TestExportToCsvBytes:
    def test_returns_bytes_with_bom(self):
        data = export_to_csv_bytes([_sample_row()])
        assert isinstance(data, bytes)
        assert data.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM

    def test_csv_roundtrip_preserves_company_name(self):
        rows = [_sample_row(company_name="Special & Co, Ltd.")]
        data = export_to_csv_bytes(rows)
        df = pd.read_csv(io.BytesIO(data), encoding="utf-8-sig")
        assert df.iloc[0][COLUMN_HEADERS["company_name"]] == "Special & Co, Ltd."

    def test_csv_handles_special_characters(self):
        rows = [_sample_row(research_summary="Contains éè and ü characters")]
        data = export_to_csv_bytes(rows)
        df = pd.read_csv(io.BytesIO(data), encoding="utf-8-sig")
        assert "éè" in df.iloc[0][COLUMN_HEADERS["research_summary"]]


class TestExportToExcelBytes:
    def test_returns_nonempty_bytes(self):
        data = export_to_excel_bytes([_sample_row()])
        assert isinstance(data, bytes)
        assert len(data) > 0

    def test_excel_roundtrip_preserves_all_rows(self):
        rows = [_sample_row(company_name="Alpha"), _sample_row(company_name="Beta")]
        data = export_to_excel_bytes(rows)
        df = pd.read_excel(io.BytesIO(data))
        assert len(df) == 2
        assert set(df[COLUMN_HEADERS["company_name"]]) == {"Alpha", "Beta"}

    def test_excel_custom_sheet_name(self):
        data = export_to_excel_bytes([_sample_row()], sheet_name="Custom Sheet")
        xls = pd.ExcelFile(io.BytesIO(data))
        assert "Custom Sheet" in xls.sheet_names

    def test_excel_empty_rows_does_not_crash(self):
        data = export_to_excel_bytes([])
        df = pd.read_excel(io.BytesIO(data))
        assert len(df) == 0
