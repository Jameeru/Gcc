"""
Property-based tests for historical research results search/filtering.

This module implements:
  - Property 17: Historical Search Accuracy -- for any set of stored research
    results, searching/filtering by company name, domain, GCC presence, or
    suitability score range shall return exactly the results matching the
    given criteria (no false positives, no false negatives).
  - Property 18: Date Range Filtering -- for any set of stored research
    results, filtering by created_at start/end date shall return exactly the
    results whose created_at falls within the given (inclusive) range.

It also covers task 12.4's unit tests for pagination edge cases (limit/offset
correctness, total_count stability across pages) and ordering correctness.

**Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5**

Implementation note: `ResearchResult.research_metadata` (src/models/schemas.py)
uses `sqlalchemy.dialects.postgresql.JSONB`, a Postgres-only dialect type that
fails to compile DDL on SQLite (`CompileError: ... can't render element of
type JSONB` -- confirmed by hand before writing this file). Following the
precedent already established in tests/test_auth_properties.py (a local
`TestBase = declarative_base()` with a hand-rolled `TestUser` model), this
file defines a parallel `TestResearchResult` model that mirrors every column
of the real `ResearchResult` *except* `research_metadata`, and a
`TestResearchResultRepository` whose `search_results` method body is a
faithful copy of `src/models/repositories.py::ResearchResultRepository.
search_results` rebound to the test model, so it exercises the exact same
filtering/pagination/ordering logic against a real in-memory SQLite database.
"""

import os
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import pytest
from hypothesis import given, settings, strategies as st, HealthCheck

from sqlalchemy import (
    Boolean, Column, CheckConstraint, DateTime, Integer, String, Text,
    and_, asc, create_engine, desc, or_,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import func

TestBase = declarative_base()


class TestResearchResult(TestBase):
    """Mirrors src/models/schemas.py::ResearchResult, minus the JSONB column."""

    __tablename__ = "research_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    normalized_key = Column(String(255), unique=True, nullable=False, index=True)
    company_name = Column(String(255), nullable=False)
    company_domain = Column(String(255), nullable=True)

    gcc_presence = Column(Boolean, nullable=True)
    gcc_location = Column(String(255), nullable=True)
    suitability_score = Column(
        Integer,
        CheckConstraint("suitability_score >= 1 AND suitability_score <= 10"),
        nullable=True,
    )

    business_pain_points = Column(Text, nullable=True)
    expansion_indicators = Column(Text, nullable=True)
    hiring_signals = Column(Text, nullable=True)
    research_summary = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True)


class TestResearchResultRepository:
    """
    Faithful copy of ResearchResultRepository's relevant methods, rebound to
    TestResearchResult, so Property 17/18 and pagination behavior are tested
    against the real filtering/ordering/pagination logic on a real (SQLite)
    database engine.
    """

    def __init__(self, session):
        self.session = session

    def create_research_result(self, **kwargs) -> TestResearchResult:
        suitability_score = kwargs.get("suitability_score")
        if suitability_score is not None and not (1 <= suitability_score <= 10):
            raise ValueError("Suitability score must be between 1 and 10")
        result = TestResearchResult(**kwargs)
        self.session.add(result)
        self.session.flush()
        return result

    def search_results(self,
                        search_term: Optional[str] = None,
                        gcc_presence: Optional[bool] = None,
                        min_suitability_score: Optional[int] = None,
                        max_suitability_score: Optional[int] = None,
                        start_date: Optional[datetime] = None,
                        end_date: Optional[datetime] = None,
                        limit: Optional[int] = None,
                        offset: int = 0,
                        order_by: str = "created_at",
                        order_direction: str = "desc") -> Tuple[List[TestResearchResult], int]:
        query = self.session.query(TestResearchResult)

        conditions = []

        if search_term:
            search_pattern = f"%{search_term}%"
            conditions.append(
                or_(
                    TestResearchResult.company_name.ilike(search_pattern),
                    TestResearchResult.company_domain.ilike(search_pattern),
                )
            )

        if gcc_presence is not None:
            conditions.append(TestResearchResult.gcc_presence == gcc_presence)

        if min_suitability_score is not None:
            conditions.append(TestResearchResult.suitability_score >= min_suitability_score)

        if max_suitability_score is not None:
            conditions.append(TestResearchResult.suitability_score <= max_suitability_score)

        if start_date:
            conditions.append(TestResearchResult.created_at >= start_date)

        if end_date:
            conditions.append(TestResearchResult.created_at <= end_date)

        if conditions:
            query = query.filter(and_(*conditions))

        total_count = query.count()

        order_column = getattr(TestResearchResult, order_by, TestResearchResult.created_at)
        if order_direction.lower() == "desc":
            query = query.order_by(desc(order_column))
        else:
            query = query.order_by(asc(order_column))

        if offset > 0:
            query = query.offset(offset)
        if limit:
            query = query.limit(limit)

        return query.all(), total_count


def _make_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    TestBase.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def _seed(repo: TestResearchResultRepository, companies: List[Dict[str, Any]]) -> None:
    for i, c in enumerate(companies):
        repo.create_research_result(
            normalized_key=f"key-{i}",
            company_name=c["company_name"],
            company_domain=c.get("company_domain"),
            gcc_presence=c.get("gcc_presence"),
            suitability_score=c.get("suitability_score"),
            created_at=c["created_at"],
        )
    repo.session.commit()


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_NAME_POOL = ["Acme Corp", "Globex Inc", "Initech", "Umbrella LLC", "Soylent Ltd",
              "Stark Industries", "Wayne Enterprises", "Wonka Co"]
_DOMAIN_POOL = ["acme.com", "globex.com", "initech.io", "umbrella.org", None]


@st.composite
def companies_list(draw, min_size=3, max_size=12):
    size = draw(st.integers(min_value=min_size, max_value=max_size))
    base_date = datetime(2025, 1, 1, tzinfo=timezone.utc)
    companies = []
    for i in range(size):
        name = draw(st.sampled_from(_NAME_POOL)) + f" {i}"
        domain = draw(st.sampled_from(_DOMAIN_POOL))
        gcc_presence = draw(st.booleans())
        score = draw(st.integers(min_value=1, max_value=10))
        day_offset = draw(st.integers(min_value=0, max_value=200))
        companies.append({
            "company_name": name,
            "company_domain": domain,
            "gcc_presence": gcc_presence,
            "suitability_score": score,
            "created_at": base_date + timedelta(days=day_offset),
        })
    return companies


class TestProperty17HistoricalSearchAccuracy:
    """Property 17: Historical Search Accuracy."""

    @given(companies_list())
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=25)
    def test_search_term_matches_name_or_domain_case_insensitively(self, companies):
        session = _make_session()
        try:
            repo = TestResearchResultRepository(session)
            _seed(repo, companies)

            term = companies[0]["company_name"].split()[0]
            results, total_count = repo.search_results(search_term=term)

            expected = [
                c for c in companies
                if term.lower() in c["company_name"].lower()
                or (c["company_domain"] and term.lower() in c["company_domain"].lower())
            ]

            assert total_count == len(expected), \
                f"Expected {len(expected)} matches for term {term!r}, got {total_count}"
            returned_names = {r.company_name for r in results}
            expected_names = {c["company_name"] for c in expected}
            assert returned_names == expected_names, \
                f"Search for {term!r} should return exactly {expected_names}, got {returned_names}"
        finally:
            session.close()

    @given(companies_list())
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=25)
    def test_gcc_presence_filter_accuracy(self, companies):
        session = _make_session()
        try:
            repo = TestResearchResultRepository(session)
            _seed(repo, companies)

            for flag in (True, False):
                results, total_count = repo.search_results(gcc_presence=flag)
                expected = [c for c in companies if c["gcc_presence"] == flag]
                assert total_count == len(expected), \
                    f"gcc_presence={flag} should match {len(expected)} rows, got {total_count}"
                assert all(r.gcc_presence == flag for r in results), \
                    "All returned rows must have the requested gcc_presence value"
        finally:
            session.close()

    @given(companies_list())
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=25)
    def test_suitability_score_range_filter_accuracy(self, companies):
        session = _make_session()
        try:
            repo = TestResearchResultRepository(session)
            _seed(repo, companies)

            min_score, max_score = 4, 7
            results, total_count = repo.search_results(
                min_suitability_score=min_score, max_suitability_score=max_score
            )
            expected = [c for c in companies if min_score <= c["suitability_score"] <= max_score]

            assert total_count == len(expected), \
                f"Score range [{min_score},{max_score}] should match {len(expected)}, got {total_count}"
            assert all(min_score <= r.suitability_score <= max_score for r in results), \
                "All returned rows must fall within the requested score range"
        finally:
            session.close()

    @given(companies_list())
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=25)
    def test_combined_filters_are_intersected_not_unioned(self, companies):
        """Multiple simultaneous filters should narrow results (AND semantics)."""
        session = _make_session()
        try:
            repo = TestResearchResultRepository(session)
            _seed(repo, companies)

            results, total_count = repo.search_results(
                gcc_presence=True, min_suitability_score=6
            )
            expected = [
                c for c in companies
                if c["gcc_presence"] is True and c["suitability_score"] >= 6
            ]
            assert total_count == len(expected)
            assert all(r.gcc_presence is True and r.suitability_score >= 6 for r in results)
        finally:
            session.close()


class TestProperty18DateRangeFiltering:
    """Property 18: Date Range Filtering."""

    @given(companies_list())
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=25)
    def test_start_date_filter_is_inclusive_and_accurate(self, companies):
        session = _make_session()
        try:
            repo = TestResearchResultRepository(session)
            _seed(repo, companies)

            cutoff = sorted(c["created_at"] for c in companies)[len(companies) // 2]
            results, total_count = repo.search_results(start_date=cutoff)
            expected = [c for c in companies if c["created_at"] >= cutoff]

            assert total_count == len(expected), \
                f"start_date={cutoff} should include {len(expected)} rows, got {total_count}"
            # SQLite returns naive datetimes regardless of how they were stored,
            # so compare on a tz-naive basis -- this is a SQLite storage quirk,
            # not a behavior under test.
            naive_cutoff = cutoff.replace(tzinfo=None)
            assert all(r.created_at >= naive_cutoff for r in results)
        finally:
            session.close()

    @given(companies_list())
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=25)
    def test_end_date_filter_is_inclusive_and_accurate(self, companies):
        session = _make_session()
        try:
            repo = TestResearchResultRepository(session)
            _seed(repo, companies)

            cutoff = sorted(c["created_at"] for c in companies)[len(companies) // 2]
            results, total_count = repo.search_results(end_date=cutoff)
            expected = [c for c in companies if c["created_at"] <= cutoff]

            assert total_count == len(expected), \
                f"end_date={cutoff} should include {len(expected)} rows, got {total_count}"
            naive_cutoff = cutoff.replace(tzinfo=None)
            assert all(r.created_at <= naive_cutoff for r in results)
        finally:
            session.close()

    @given(companies_list(min_size=5, max_size=15))
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=25)
    def test_start_and_end_date_together_define_a_window(self, companies):
        session = _make_session()
        try:
            repo = TestResearchResultRepository(session)
            _seed(repo, companies)

            dates = sorted(c["created_at"] for c in companies)
            start = dates[len(dates) // 4]
            end = dates[(3 * len(dates)) // 4]
            if start > end:
                start, end = end, start

            results, total_count = repo.search_results(start_date=start, end_date=end)
            expected = [c for c in companies if start <= c["created_at"] <= end]

            assert total_count == len(expected)
            naive_start, naive_end = start.replace(tzinfo=None), end.replace(tzinfo=None)
            assert all(naive_start <= r.created_at <= naive_end for r in results)
        finally:
            session.close()

    def test_no_results_outside_range_returned(self):
        """Regression guard: a row clearly outside the window must never appear."""
        session = _make_session()
        try:
            repo = TestResearchResultRepository(session)
            companies = [
                {"company_name": "Old Co", "company_domain": "old.com", "gcc_presence": True,
                 "suitability_score": 5, "created_at": datetime(2020, 1, 1, tzinfo=timezone.utc)},
                {"company_name": "New Co", "company_domain": "new.com", "gcc_presence": True,
                 "suitability_score": 5, "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc)},
            ]
            _seed(repo, companies)

            results, total_count = repo.search_results(
                start_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
                end_date=datetime(2025, 12, 31, tzinfo=timezone.utc),
            )
            assert total_count == 0
            assert results == []
        finally:
            session.close()


class TestTask12_4PaginationAndOrdering:
    """Task 12.4: unit tests for pagination edge cases and ordering correctness."""

    def _seeded_repo(self, n=23):
        session = _make_session()
        repo = TestResearchResultRepository(session)
        base_date = datetime(2025, 1, 1, tzinfo=timezone.utc)
        companies = [
            {
                "company_name": f"Company {i:02d}",
                "company_domain": f"company{i}.com",
                "gcc_presence": i % 2 == 0,
                "suitability_score": (i % 10) + 1,
                "created_at": base_date + timedelta(days=i),
            }
            for i in range(n)
        ]
        _seed(repo, companies)
        return repo, n

    def test_total_count_is_stable_across_pages(self):
        repo, n = self._seeded_repo(23)
        try:
            page_size = 5
            seen_ids = set()
            offset = 0
            counts = []
            while True:
                results, total_count = repo.search_results(limit=page_size, offset=offset)
                counts.append(total_count)
                if not results:
                    break
                seen_ids.update(r.id for r in results)
                offset += page_size

            assert all(c == n for c in counts), \
                f"total_count should equal {n} on every page, got {counts}"
            assert len(seen_ids) == n, \
                f"Paginating through all pages should visit every row exactly once, got {len(seen_ids)}"
        finally:
            repo.session.close()

    def test_limit_caps_page_size_and_offset_skips_correctly(self):
        repo, n = self._seeded_repo(23)
        try:
            first_page, _ = repo.search_results(limit=10, offset=0, order_by="company_name", order_direction="asc")
            second_page, _ = repo.search_results(limit=10, offset=10, order_by="company_name", order_direction="asc")
            third_page, _ = repo.search_results(limit=10, offset=20, order_by="company_name", order_direction="asc")

            assert len(first_page) == 10
            assert len(second_page) == 10
            assert len(third_page) == 3  # 23 - 20

            first_names = [r.company_name for r in first_page]
            second_names = [r.company_name for r in second_page]
            assert set(first_names).isdisjoint(set(second_names)), \
                "Consecutive pages must not overlap"
        finally:
            repo.session.close()

    def test_offset_beyond_total_returns_empty_but_correct_count(self):
        repo, n = self._seeded_repo(5)
        try:
            results, total_count = repo.search_results(limit=10, offset=100)
            assert results == []
            assert total_count == n, "total_count should reflect all matching rows, not the empty page"
        finally:
            repo.session.close()

    def test_ordering_by_suitability_score_ascending_and_descending(self):
        repo, n = self._seeded_repo(15)
        try:
            asc_results, _ = repo.search_results(order_by="suitability_score", order_direction="asc")
            desc_results, _ = repo.search_results(order_by="suitability_score", order_direction="desc")

            asc_scores = [r.suitability_score for r in asc_results]
            desc_scores = [r.suitability_score for r in desc_results]

            assert asc_scores == sorted(asc_scores), "asc ordering should be non-decreasing"
            assert desc_scores == sorted(desc_scores, reverse=True), "desc ordering should be non-increasing"
        finally:
            repo.session.close()

    def test_ordering_by_created_at_default_is_descending(self):
        repo, n = self._seeded_repo(10)
        try:
            results, _ = repo.search_results()  # defaults: order_by=created_at, desc
            dates = [r.created_at for r in results]
            assert dates == sorted(dates, reverse=True), \
                "Default ordering should be most-recent-first"
        finally:
            repo.session.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
