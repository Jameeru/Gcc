"""
Performance / load regression tests (task 15.3).

These are not strict benchmarks (CI hardware varies); they're regression
guards against pathological algorithmic complexity -- e.g. an accidental
O(n^2) loop in column detection, or a missing index turning a search query
into a full table scan that scales badly. Each assertion uses a generous
time budget so the tests stay reliable on slow/shared CI runners while still
catching real regressions (which tend to be 10-100x slower, not 2x).

**Validates: Requirements 6.5, 9.1, 9.5**
"""

import io
import os
import sys
import time

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

import pytest

from tests.test_historical_search_properties import (
    TestResearchResultRepository,
    _make_session,
)
from datetime import datetime, timedelta, timezone

from src.utils.validation import (
    detect_company_columns,
    read_csv_with_fallback_encoding,
    validate_csv_structure,
)
from src.core.normalization import normalize_company


def _generate_large_csv(num_rows: int) -> bytes:
    lines = ["Company Name,Website"]
    for i in range(num_rows):
        lines.append(f"Company {i},company{i}.com")
    return ("\n".join(lines) + "\n").encode("utf-8")


class TestCsvUploadThroughput:
    """Task 15.3: CSV upload validation must scale roughly linearly."""

    def test_large_csv_validation_completes_within_budget(self):
        num_rows = 5000
        csv_bytes = _generate_large_csv(num_rows)

        start = time.perf_counter()
        df = read_csv_with_fallback_encoding(io.BytesIO(csv_bytes))
        structure_errors = validate_csv_structure(df)
        detection = detect_company_columns(df)
        elapsed = time.perf_counter() - start

        assert len(df) == num_rows
        assert structure_errors == []
        assert detection.name_column == "Company Name"
        assert elapsed < 10.0, \
            f"Validating a {num_rows}-row CSV took {elapsed:.2f}s, expected well under 10s"

    def test_normalization_throughput_for_large_batch(self):
        num_rows = 5000
        start = time.perf_counter()
        keys = [normalize_company(f"Company {i}", f"company{i}.com") for i in range(num_rows)]
        elapsed = time.perf_counter() - start

        assert len(set(keys)) == num_rows, "Each distinct company should normalize to a unique key"
        assert elapsed < 5.0, \
            f"Normalizing {num_rows} companies took {elapsed:.2f}s, expected well under 5s"


class TestHistoricalSearchPerformance:
    """Task 15.3: search_results must scale reasonably with table size."""

    def _seed_large_table(self, repo, n):
        base_date = datetime(2025, 1, 1, tzinfo=timezone.utc)
        for i in range(n):
            repo.create_research_result(
                normalized_key=f"key-{i}",
                company_name=f"Company {i:05d}",
                company_domain=f"company{i}.com",
                gcc_presence=(i % 3 == 0),
                suitability_score=(i % 10) + 1,
                created_at=base_date + timedelta(minutes=i),
            )
        repo.session.commit()

    def test_search_with_filters_on_large_table_completes_within_budget(self):
        session = _make_session()
        try:
            repo = TestResearchResultRepository(session)
            n = 2000
            self._seed_large_table(repo, n)

            start = time.perf_counter()
            results, total_count = repo.search_results(
                gcc_presence=True, min_suitability_score=5, limit=50, offset=0
            )
            elapsed = time.perf_counter() - start

            assert total_count > 0
            assert len(results) <= 50
            assert elapsed < 2.0, \
                f"Filtered search over {n} rows took {elapsed:.2f}s, expected well under 2s"
        finally:
            session.close()

    def test_pagination_through_large_table_completes_within_budget(self):
        session = _make_session()
        try:
            repo = TestResearchResultRepository(session)
            n = 2000
            self._seed_large_table(repo, n)

            start = time.perf_counter()
            offset = 0
            page_size = 100
            pages_visited = 0
            while True:
                results, total_count = repo.search_results(limit=page_size, offset=offset)
                if not results:
                    break
                pages_visited += 1
                offset += page_size
            elapsed = time.perf_counter() - start

            assert pages_visited == n // page_size
            assert elapsed < 5.0, \
                f"Paginating through {n} rows took {elapsed:.2f}s, expected well under 5s"
        finally:
            session.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
