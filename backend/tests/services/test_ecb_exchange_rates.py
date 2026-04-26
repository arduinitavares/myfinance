"""Module for backend tests services test_ecb_exchange_rates."""

import asyncio
import importlib
import sys
import types
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace, TracebackType
from typing import TYPE_CHECKING, Never, cast

import pytest
from app.models.fx import FXDailyReferenceRate
from app.models.imports import (
    ImportSession,
    ImportStatementDraft,
    ImportTransactionDraft,
)
from app.models.transaction import Transaction, TransactionType
from app.services import fx_refresh_lock
from app.services.ecb_exchange_rates import (
    ECBExchangeRateService,
    FXConversionCoverageRequest,
    FXConversionCoverageStatus,
    FXRefreshResult,
)
from app.services.fx_refresh_scheduler import build_fx_refresh_scheduler
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    import httpx

EXPECTED_REFRESH_ROW_COUNT: int = 2
SCHEDULER_HOUR_FIELD_INDEX: int = 5
SCHEDULER_MINUTE_FIELD_INDEX: int = 6


class FakeSentenceTransformer:
    """Test double for the sentence-transformers dependency."""

    def encode(self, *_args: object, **_kwargs: object) -> list[float]:
        """Return a deterministic embedding."""
        return [0.0]


class FakeQdrantClient:
    """Test double for the Qdrant client dependency."""

    def recreate_collection(self, *_args: object, **_kwargs: object) -> None:
        """Pretend to recreate a vector collection."""
        return

    def upsert(self, *_args: object, **_kwargs: object) -> None:
        """Pretend to upsert vectors."""
        return

    def get_collection(self, *_args: object, **_kwargs: object) -> SimpleNamespace:
        """Return an empty collection summary."""
        return SimpleNamespace(points_count=0)

    def search_points(self, *_args: object, **_kwargs: object) -> list[object]:
        """Return no vector matches."""
        return []


class FakeVectorParams:
    """Test double for Qdrant vector params."""


class FakePointStruct:
    """Test double for Qdrant point structs."""


def _fetch_series_stub(
    series: dict[date, dict[str, Decimal]],
) -> Callable[[ECBExchangeRateService, date, date], dict[date, dict[str, Decimal]]]:
    def fetch_series(
        _self: ECBExchangeRateService,
        _start_date: date,
        _end_date: date,
    ) -> dict[date, dict[str, Decimal]]:
        return series

    return fetch_series


def _dependency_stub_modules() -> dict[str, types.ModuleType]:
    sentence_transformers_module = types.ModuleType("sentence_transformers")
    sentence_transformers_module.__dict__[
        "SentenceTransformer"
    ] = FakeSentenceTransformer

    pandas_module = types.ModuleType("pandas")
    pandas_module.__dict__["DataFrame"] = object
    pandas_module.__dict__["notna"] = lambda value: value is not None

    qdrant_module = types.ModuleType("qdrant_client")
    qdrant_module.__dict__["QdrantClient"] = FakeQdrantClient

    qdrant_http_module = types.ModuleType("qdrant_client.http")
    qdrant_http_models_module = types.ModuleType("qdrant_client.http.models")
    qdrant_http_models_module.__dict__["VectorParams"] = FakeVectorParams
    qdrant_http_models_module.__dict__["PointStruct"] = FakePointStruct
    qdrant_http_models_module.__dict__["Distance"] = SimpleNamespace(COSINE="cosine")
    qdrant_http_module.__dict__["models"] = qdrant_http_models_module

    return {
        "sentence_transformers": sentence_transformers_module,
        "pandas": pandas_module,
        "qdrant_client": qdrant_module,
        "qdrant_client.http": qdrant_http_module,
        "qdrant_client.http.models": qdrant_http_models_module,
    }


def _import_main_with_dependency_stubs(
    monkeypatch: pytest.MonkeyPatch,
) -> types.ModuleType:
    for module_name, module in _dependency_stub_modules().items():
        monkeypatch.setitem(sys.modules, module_name, module)

    for module_name in (
        "app.main",
        "app.routers.transactions",
        "app.routers.suggestions",
        "app.services.csv_import_service",
        "app.services.csv_parser",
        "app.services.classification_commit_service",
        "app.services.category_suggestion_service",
    ):
        sys.modules.pop(module_name, None)

    return importlib.import_module("app.main")


def _stored_rates(db_session: Session) -> list[FXDailyReferenceRate]:
    return (
        db_session.query(FXDailyReferenceRate)
        .order_by(FXDailyReferenceRate.rate_date, FXDailyReferenceRate.quoted_currency)
        .all()
    )


def test_earliest_covered_date_returns_none_for_empty_table(
    db_session: Session,
) -> None:
    """Verify earliest covered date returns none for empty table."""
    service = ECBExchangeRateService(db_session)

    assert service.earliest_covered_date() is None


def test_earliest_covered_date_returns_minimum_rate_date(db_session: Session) -> None:
    """Verify earliest covered date returns minimum rate date."""
    db_session.add_all(
        [
            FXDailyReferenceRate(
                rate_date=date(2026, 4, 17),
                base_currency="EUR",
                quoted_currency="USD",
                units_per_base=Decimal("1.1100"),
                source_name="ECB_EXR",
                fetched_at=datetime(2026, 4, 17, 8, 30, 0, tzinfo=UTC),
                updated_at=datetime(2026, 4, 17, 8, 30, 0, tzinfo=UTC),
            ),
            FXDailyReferenceRate(
                rate_date=date(2026, 4, 15),
                base_currency="EUR",
                quoted_currency="USD",
                units_per_base=Decimal("1.1000"),
                source_name="ECB_EXR",
                fetched_at=datetime(2026, 4, 15, 8, 30, 0, tzinfo=UTC),
                updated_at=datetime(2026, 4, 15, 8, 30, 0, tzinfo=UTC),
            ),
            FXDailyReferenceRate(
                rate_date=date(2026, 4, 15),
                base_currency="EUR",
                quoted_currency="BRL",
                units_per_base=Decimal("6.0100"),
                source_name="ECB_EXR",
                fetched_at=datetime(2026, 4, 15, 8, 30, 0, tzinfo=UTC),
                updated_at=datetime(2026, 4, 15, 8, 30, 0, tzinfo=UTC),
            ),
            FXDailyReferenceRate(
                rate_date=date(2026, 4, 14),
                base_currency="USD",
                quoted_currency="EUR",
                units_per_base=Decimal("0.9000"),
                source_name="OTHER",
                fetched_at=datetime(2026, 4, 14, 8, 30, 0, tzinfo=UTC),
                updated_at=datetime(2026, 4, 14, 8, 30, 0, tzinfo=UTC),
            ),
        ]
    )
    db_session.commit()

    service = ECBExchangeRateService(db_session)

    assert service.earliest_covered_date() == date(2026, 4, 15)


def test_earliest_covered_date_ignores_partial_coverage_until_both_quotes_exist(
    db_session: Session,
) -> None:
    """Verify earliest covered date ignores partial coverage until both quotes exist."""
    db_session.add_all(
        [
            FXDailyReferenceRate(
                rate_date=date(2026, 4, 14),
                base_currency="EUR",
                quoted_currency="USD",
                units_per_base=Decimal("1.0900"),
                source_name="ECB_EXR",
                fetched_at=datetime(2026, 4, 14, 8, 30, 0, tzinfo=UTC),
                updated_at=datetime(2026, 4, 14, 8, 30, 0, tzinfo=UTC),
            ),
            FXDailyReferenceRate(
                rate_date=date(2026, 4, 15),
                base_currency="EUR",
                quoted_currency="USD",
                units_per_base=Decimal("1.1000"),
                source_name="ECB_EXR",
                fetched_at=datetime(2026, 4, 15, 8, 30, 0, tzinfo=UTC),
                updated_at=datetime(2026, 4, 15, 8, 30, 0, tzinfo=UTC),
            ),
            FXDailyReferenceRate(
                rate_date=date(2026, 4, 15),
                base_currency="EUR",
                quoted_currency="BRL",
                units_per_base=Decimal("6.0100"),
                source_name="ECB_EXR",
                fetched_at=datetime(2026, 4, 15, 8, 30, 0, tzinfo=UTC),
                updated_at=datetime(2026, 4, 15, 8, 30, 0, tzinfo=UTC),
            ),
        ]
    )
    db_session.commit()

    service = ECBExchangeRateService(db_session)

    assert service.earliest_covered_date() == date(2026, 4, 15)


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 4, 15), date(2026, 4, 15)),
        (date(2026, 4, 18), date(2026, 4, 17)),
        (date(2026, 4, 19), date(2026, 4, 17)),
        (date(2026, 4, 6), date(2026, 4, 2)),
        (date(2026, 1, 1), date(2025, 12, 31)),
    ],
)
def test_latest_publication_day_on_or_before_handles_weekends_and_closing_days(
    db_session: Session,
    day: date,
    expected: date,
) -> None:
    """Verify latest publication day on or before handles weekends and closing days."""
    service = ECBExchangeRateService(db_session)

    assert service.latest_publication_day_on_or_before(day) == expected


def test_get_xml_response_uses_configured_timeout_for_injected_http_client(
    db_session: Session,
) -> None:
    """Verify get xml response uses configured timeout for injected http client."""

    class FakeResponse:
        def __init__(self) -> None:
            self.raise_for_status_called = False

        def raise_for_status(self) -> None:
            self.raise_for_status_called = True

    class FakeHttpClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def get(self, url: str, **kwargs: object) -> FakeResponse:
            self.calls.append((url, kwargs))
            return FakeResponse()

    http_client = FakeHttpClient()
    service = ECBExchangeRateService(
        db_session,
        http_client=cast("httpx.Client", http_client),
        timeout=12.5,
    )

    response = service._get_xml_response("https://example.com/rates.xml")

    assert isinstance(response, FakeResponse)
    assert http_client.calls == [
        (
            "https://example.com/rates.xml",
            {"timeout": 12.5, "follow_redirects": True},
        )
    ]
    assert response.raise_for_status_called is True


def test_get_xml_response_uses_configured_timeout_for_default_http_client(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify get xml response uses configured timeout for default http client."""
    init_kwargs: dict[str, object] = {}
    get_kwargs: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            init_kwargs.update(kwargs)

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: TracebackType | None,
        ) -> bool:
            return False

        def get(self, url: str, **kwargs: object) -> FakeResponse:
            get_kwargs["url"] = url
            get_kwargs.update(kwargs)
            return FakeResponse()

    monkeypatch.setattr("app.services.ecb_exchange_rates.httpx.Client", FakeClient)

    service = ECBExchangeRateService(db_session, timeout=7.25)
    response = service._get_xml_response("https://example.com/rates.xml")

    assert isinstance(response, FakeResponse)
    assert init_kwargs == {"timeout": 7.25, "follow_redirects": True}
    assert get_kwargs == {
        "url": "https://example.com/rates.xml",
        "timeout": 7.25,
        "follow_redirects": True,
    }


def test_historical_seed_coverage_requires_boundary_coverage(
    db_session: Session,
) -> None:
    """Verify seed coverage requires both boundary quotes."""
    db_session.add(
        Transaction(
            account_number="BE10000000000001",
            transaction_date=date(2026, 4, 16),
            amount=-42.50,
            currency="EUR",
            description="quote coverage boundary transaction",
            transaction_type=TransactionType.EXPENSE,
            source_bank="ing",
        )
    )
    db_session.commit()

    service = ECBExchangeRateService(
        db_session,
        now_provider=lambda: datetime(2026, 4, 17, 8, 30, 0, tzinfo=UTC),
    )
    db_session.add_all(
        [
            FXDailyReferenceRate(
                rate_date=date(2026, 4, 16),
                base_currency="EUR",
                quoted_currency="USD",
                units_per_base=Decimal("1.1100"),
                source_name="ECB_EXR",
                fetched_at=datetime(2026, 4, 16, 8, 30, 0, tzinfo=UTC),
                updated_at=datetime(2026, 4, 16, 8, 30, 0, tzinfo=UTC),
            ),
            FXDailyReferenceRate(
                rate_date=date(2026, 4, 16),
                base_currency="EUR",
                quoted_currency="BRL",
                units_per_base=Decimal("6.0100"),
                source_name="ECB_EXR",
                fetched_at=datetime(2026, 4, 16, 8, 30, 0, tzinfo=UTC),
                updated_at=datetime(2026, 4, 16, 8, 30, 0, tzinfo=UTC),
            ),
        ]
    )
    db_session.commit()

    assert service.has_historical_seed_coverage(today=date(2026, 4, 17)) is False

    db_session.add(
        FXDailyReferenceRate(
            rate_date=date(2026, 4, 17),
            base_currency="EUR",
            quoted_currency="USD",
            units_per_base=Decimal("1.0500"),
            source_name="ECB_EXR",
            fetched_at=datetime(2026, 4, 17, 8, 30, 0, tzinfo=UTC),
            updated_at=datetime(2026, 4, 17, 8, 30, 0, tzinfo=UTC),
        )
    )
    db_session.commit()

    assert service.has_historical_seed_coverage(today=date(2026, 4, 17)) is False

    db_session.add(
        FXDailyReferenceRate(
            rate_date=date(2026, 4, 17),
            base_currency="EUR",
            quoted_currency="BRL",
            units_per_base=Decimal("5.5000"),
            source_name="ECB_EXR",
            fetched_at=datetime(2026, 4, 17, 8, 30, 0, tzinfo=UTC),
            updated_at=datetime(2026, 4, 17, 8, 30, 0, tzinfo=UTC),
        )
    )
    db_session.commit()

    assert service.has_historical_seed_coverage(today=date(2026, 4, 17)) is True


def test_has_historical_seed_coverage_detects_mid_history_gap_between_boundaries(
    db_session: Session,
) -> None:
    """Verify seed coverage detects mid history gaps."""
    db_session.add(
        Transaction(
            account_number="BE10000000000001",
            transaction_date=date(2026, 4, 14),
            amount=-42.50,
            currency="EUR",
            description="historical coverage boundary transaction",
            transaction_type=TransactionType.EXPENSE,
            source_bank="ing",
        )
    )
    db_session.commit()

    service = ECBExchangeRateService(
        db_session,
        now_provider=lambda: datetime(2026, 4, 17, 8, 30, 0, tzinfo=UTC),
    )
    db_session.add_all(
        [
            FXDailyReferenceRate(
                rate_date=rate_date,
                base_currency="EUR",
                quoted_currency=quoted_currency,
                units_per_base=Decimal("1.1100")
                if quoted_currency == "USD"
                else Decimal("6.0100"),
                source_name="ECB_EXR",
                fetched_at=datetime(2026, 4, 17, 8, 30, 0, tzinfo=UTC),
                updated_at=datetime(2026, 4, 17, 8, 30, 0, tzinfo=UTC),
            )
            for rate_date in (date(2026, 4, 14), date(2026, 4, 16), date(2026, 4, 17))
            for quoted_currency in ("USD", "BRL")
        ]
    )
    db_session.commit()

    assert service.has_historical_seed_coverage(today=date(2026, 4, 17)) is False

    db_session.add_all(
        [
            FXDailyReferenceRate(
                rate_date=date(2026, 4, 15),
                base_currency="EUR",
                quoted_currency=quoted_currency,
                units_per_base=Decimal("1.1200")
                if quoted_currency == "USD"
                else Decimal("6.0200"),
                source_name="ECB_EXR",
                fetched_at=datetime(2026, 4, 17, 9, 0, 0, tzinfo=UTC),
                updated_at=datetime(2026, 4, 17, 9, 0, 0, tzinfo=UTC),
            )
            for quoted_currency in ("USD", "BRL")
        ]
    )
    db_session.commit()

    assert service.has_historical_seed_coverage(today=date(2026, 4, 17)) is True


def test_seed_historical_rates_uses_last_five_years_when_no_transactions(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify seed historical rates uses last five years when no transactions."""
    today = date(2026, 4, 17)
    monkeypatch.setattr(
        ECBExchangeRateService,
        "_fetch_series",
        _fetch_series_stub({
            date(2021, 4, 16): {"USD": Decimal("1.0500"), "BRL": Decimal("5.5000")},
            date(2021, 4, 17): {"USD": Decimal("1.0600"), "BRL": Decimal("5.6000")},
            date(2026, 4, 17): {"USD": Decimal("1.1700"), "BRL": Decimal("6.2000")},
        }),
    )

    service = ECBExchangeRateService(
        db_session,
        now_provider=lambda: datetime(2026, 4, 17, 8, 30, 0, tzinfo=UTC),
    )

    result = service.seed_historical_rates(today=today)

    assert result.start_date == date(2021, 4, 17)
    assert result.end_date == today
    assert {
        (row.rate_date, row.quoted_currency) for row in _stored_rates(db_session)
    } == {
        (date(2021, 4, 17), "BRL"),
        (date(2021, 4, 17), "USD"),
        (date(2026, 4, 17), "BRL"),
        (date(2026, 4, 17), "USD"),
    }


def test_seed_historical_rates_uses_earliest_transaction_date_when_present(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify seed historical rates uses earliest transaction date when present."""
    db_session.add(
        Transaction(
            account_number="BE10000000000001",
            transaction_date=date(2024, 2, 14),
            amount=-42.50,
            currency="EUR",
            description="seed boundary transaction",
            transaction_type=TransactionType.EXPENSE,
            source_bank="ing",
        )
    )
    db_session.commit()

    monkeypatch.setattr(
        ECBExchangeRateService,
        "_fetch_series",
        _fetch_series_stub({
            date(2024, 2, 13): {"USD": Decimal("1.0200"), "BRL": Decimal("5.3000")},
            date(2024, 2, 14): {"USD": Decimal("1.0300"), "BRL": Decimal("5.4000")},
            date(2026, 4, 17): {"USD": Decimal("1.1700"), "BRL": Decimal("6.2000")},
        }),
    )

    service = ECBExchangeRateService(
        db_session,
        now_provider=lambda: datetime(2026, 4, 17, 8, 30, 0, tzinfo=UTC),
    )

    result = service.seed_historical_rates(today=date(2026, 4, 17))

    assert result.start_date == date(2024, 2, 14)
    assert {
        (row.rate_date, row.quoted_currency) for row in _stored_rates(db_session)
    } == {
        (date(2024, 2, 14), "BRL"),
        (date(2024, 2, 14), "USD"),
        (date(2026, 4, 17), "BRL"),
        (date(2026, 4, 17), "USD"),
    }


def _store_import_draft_for_fx_seed(
    db_session: Session,
    *,
    transaction_date: date,
) -> None:
    session = ImportSession(
        file_name="nexo.csv",
        file_hash=f"hash-{transaction_date.isoformat()}",
        mime_type="text/csv",
        status="awaiting_review",
        strategy_key="nexo_csv",
    )
    db_session.add(session)
    db_session.flush()

    statement = ImportStatementDraft(
        import_session_id=session.id,
        attempt_number=1,
        overall_confidence=1.0,
        review_status="awaiting_review",
    )
    db_session.add(statement)
    db_session.flush()

    draft = ImportTransactionDraft(
        import_statement_draft_id=statement.id,
        transaction_date=transaction_date,
        source_description="Nexo card purchase",
        signed_amount=-12.34,
        currency="xUSD",
        source_locator="csv:r2:NXT1001",
        edit_source="deterministic_extracted",
    )
    db_session.add(draft)
    db_session.commit()


def test_historical_seed_start_date_uses_import_draft_when_no_committed_transactions(
    db_session: Session,
) -> None:
    """Verify seed date uses import draft without committed transactions."""
    _store_import_draft_for_fx_seed(db_session, transaction_date=date(2026, 1, 1))

    service = ECBExchangeRateService(db_session)

    assert service._historical_seed_start_date(date(2026, 4, 26)) == date(2026, 1, 1)


def test_historical_seed_start_date_uses_earliest_of_committed_and_draft_dates(
    db_session: Session,
) -> None:
    """Verify historical seed start date uses earliest of committed and draft dates."""
    db_session.add(
        Transaction(
            account_number="BE00",
            transaction_date=date(2026, 2, 1),
            amount=-10.0,
            currency="EUR",
            description="Committed transaction",
            transaction_type=TransactionType.EXPENSE,
            source_bank="Manual",
        )
    )
    db_session.commit()
    _store_import_draft_for_fx_seed(db_session, transaction_date=date(2026, 1, 1))

    service = ECBExchangeRateService(db_session)

    assert service._historical_seed_start_date(date(2026, 4, 26)) == date(2026, 1, 1)


def test_refresh_range_upserts_existing_rows_without_duplicates(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify refresh range upserts existing rows without duplicates."""
    first_run_at = datetime(2026, 4, 17, 8, 30, 0, tzinfo=UTC)
    second_run_at = datetime(2026, 4, 17, 9, 45, 0, tzinfo=UTC)

    service = ECBExchangeRateService(db_session, now_provider=lambda: first_run_at)
    monkeypatch.setattr(
        ECBExchangeRateService,
        "_fetch_series",
        _fetch_series_stub({
            date(2026, 4, 16): {"USD": Decimal("1.1100"), "BRL": Decimal("6.0100")},
        }),
    )

    first_result = service.refresh_range(date(2026, 4, 16), date(2026, 4, 16))
    first_rows = _stored_rates(db_session)
    first_updated_at = {row.quoted_currency: row.updated_at for row in first_rows}

    monkeypatch.setattr(
        ECBExchangeRateService,
        "_fetch_series",
        _fetch_series_stub({
            date(2026, 4, 16): {"USD": Decimal("1.2100"), "BRL": Decimal("6.1100")},
        }),
    )
    service = ECBExchangeRateService(db_session, now_provider=lambda: second_run_at)
    second_result = service.refresh_range(date(2026, 4, 16), date(2026, 4, 16))

    db_session.expire_all()
    rows = _stored_rates(db_session)

    assert first_result.inserted_or_updated_rows == EXPECTED_REFRESH_ROW_COUNT
    assert second_result.inserted_or_updated_rows == EXPECTED_REFRESH_ROW_COUNT
    assert len(rows) == EXPECTED_REFRESH_ROW_COUNT
    assert {row.quoted_currency: row.units_per_base for row in rows} == {
        "BRL": Decimal("6.11000000"),
        "USD": Decimal("1.21000000"),
    }
    assert {row.quoted_currency: row.fetched_at for row in rows} == {
        "BRL": second_run_at,
        "USD": second_run_at,
    }
    assert all(row.updated_at >= first_updated_at[row.quoted_currency] for row in rows)


def test_refresh_range_skips_unchanged_rows_without_timestamp_churn(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify refresh range skips unchanged rows without timestamp churn."""
    first_run_at = datetime(2026, 4, 17, 8, 30, 0, tzinfo=UTC)
    second_run_at = datetime(2026, 4, 17, 9, 45, 0, tzinfo=UTC)
    sample_series = {
        date(2026, 4, 16): {"USD": Decimal("1.1100"), "BRL": Decimal("6.0100")},
    }

    monkeypatch.setattr(
        ECBExchangeRateService,
        "_fetch_series",
        _fetch_series_stub(sample_series),
    )

    first_service = ECBExchangeRateService(
        db_session, now_provider=lambda: first_run_at
    )
    first_result = first_service.refresh_range(date(2026, 4, 16), date(2026, 4, 16))

    first_rows = _stored_rates(db_session)
    first_timestamps = {
        row.quoted_currency: (row.fetched_at, row.updated_at) for row in first_rows
    }

    second_service = ECBExchangeRateService(
        db_session, now_provider=lambda: second_run_at
    )
    second_result = second_service.refresh_range(date(2026, 4, 16), date(2026, 4, 16))

    db_session.expire_all()
    rows = _stored_rates(db_session)

    assert first_result.inserted_or_updated_rows == EXPECTED_REFRESH_ROW_COUNT
    assert second_result.inserted_or_updated_rows == 0
    assert {
        row.quoted_currency: (row.fetched_at, row.updated_at) for row in rows
    } == first_timestamps


def test_catch_up_recent_days_ignores_weekend_gaps(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify catch up recent days ignores weekend gaps."""
    today = date(2026, 2, 20)
    start_date = date(2026, 1, 7)
    service = ECBExchangeRateService(
        db_session,
        now_provider=lambda: datetime(2026, 2, 20, 2, 0, 0, tzinfo=UTC),
    )
    series = {}
    current_date = start_date
    while current_date <= today:
        if service._is_ecb_publication_day(current_date):
            series[current_date] = {"USD": Decimal("1.1300"), "BRL": Decimal("6.4400")}
        current_date = date.fromordinal(current_date.toordinal() + 1)

    monkeypatch.setattr(
        ECBExchangeRateService,
        "_fetch_series",
        _fetch_series_stub(series),
    )

    result = service.catch_up_recent_days(today=today, window_days=45)

    assert result.start_date == start_date
    assert result.end_date == today
    assert result.inserted_or_updated_rows == len(series) * 2
    assert (date(2026, 2, 14), "USD") in result.missing_publication_days
    assert (date(2026, 2, 14), "BRL") in result.missing_publication_days
    assert (date(2026, 2, 15), "USD") in result.missing_publication_days
    assert (date(2026, 2, 15), "BRL") in result.missing_publication_days
    assert result.missing_working_days == []


def test_refresh_range_reports_working_day_gap_for_missing_supported_quote(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify refresh range reports working day gap for missing supported quote."""
    monkeypatch.setattr(
        ECBExchangeRateService,
        "_fetch_series",
        _fetch_series_stub({
            date(2026, 4, 16): {"USD": Decimal("1.1100")},
        }),
    )

    result = ECBExchangeRateService(
        db_session,
        now_provider=lambda: datetime(2026, 4, 16, 8, 30, 0, tzinfo=UTC),
    ).refresh_range(date(2026, 4, 16), date(2026, 4, 16))

    assert result.inserted_or_updated_rows == 1
    assert result.missing_publication_days == []
    assert result.missing_working_days == [(date(2026, 4, 16), "BRL")]


def test_build_fx_refresh_scheduler_registers_daily_utc_job() -> None:
    """Verify build fx refresh scheduler registers daily utc job."""
    scheduler = build_fx_refresh_scheduler(lambda: None)

    try:
        job = scheduler.get_job("fx-daily-refresh")

        assert job is not None
        assert str(scheduler.timezone) == "UTC"
        assert str(job.trigger.timezone) == "UTC"
        assert str(job.trigger.fields[SCHEDULER_HOUR_FIELD_INDEX]) == "2"
        assert str(job.trigger.fields[SCHEDULER_MINUTE_FIELD_INDEX]) == "0"
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)


def test_startup_refresh_seeds_history_before_recent_catch_up_when_fx_table_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify startup refresh seeds history before recent catch up."""
    main_module = _import_main_with_dependency_stubs(monkeypatch)

    calls = []

    @contextmanager
    def fake_acquired_lock() -> Iterator[bool]:
        yield True

    class FakeSessionContext:
        def __enter__(self) -> object:
            return object()

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: TracebackType | None,
        ) -> bool:
            return False

    class FakeService:
        def __init__(self, _db: object) -> None:
            calls.append("init")

        def has_historical_seed_coverage(self) -> bool:
            calls.append("has_historical_seed_coverage")
            return False

        def seed_historical_rates(self) -> FXRefreshResult:
            calls.append("seed_historical_rates")
            return FXRefreshResult(
                start_date=date(2021, 4, 17),
                end_date=date(2026, 4, 17),
                inserted_or_updated_rows=10,
                missing_publication_days=[],
                missing_working_days=[],
            )

        def catch_up_recent_days(self, *, window_days: int) -> FXRefreshResult:
            calls.append(("catch_up_recent_days", window_days))
            return FXRefreshResult(
                start_date=date(2026, 3, 4),
                end_date=date(2026, 4, 17),
                inserted_or_updated_rows=2,
                missing_publication_days=[],
                missing_working_days=[],
            )

    monkeypatch.setattr(main_module, "_fx_refresh_lock", fake_acquired_lock)
    monkeypatch.setattr(main_module, "SessionLocal", FakeSessionContext)
    monkeypatch.setattr(main_module, "ECBExchangeRateService", FakeService)
    monkeypatch.setattr(
        main_module,
        "settings",
        SimpleNamespace(
            fx_startup_catchup_days=45,
            fx_refresh_hour_utc=2,
            fx_refresh_minute_utc=0,
        ),
    )

    main_module._run_startup_fx_refresh()

    assert calls == [
        "init",
        "has_historical_seed_coverage",
        "seed_historical_rates",
        ("catch_up_recent_days", 45),
    ]


def test_startup_refresh_skips_when_fx_lock_is_busy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify startup refresh skips when fx lock is busy."""
    main_module = _import_main_with_dependency_stubs(monkeypatch)

    calls = []

    @contextmanager
    def fake_busy_lock() -> Iterator[bool]:
        yield False

    class FakeSessionContext:
        def __enter__(self) -> object:
            calls.append("session_entered")
            return object()

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: TracebackType | None,
        ) -> bool:
            return False

    class FakeService:
        def __init__(self, _db: object) -> None:
            calls.append("service_init")

    monkeypatch.setattr(main_module, "_fx_refresh_lock", fake_busy_lock)
    monkeypatch.setattr(main_module, "SessionLocal", FakeSessionContext)
    monkeypatch.setattr(main_module, "ECBExchangeRateService", FakeService)

    main_module._run_startup_fx_refresh()

    assert calls == []


def test_lifespan_starts_startup_refresh_in_background(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify lifespan starts startup refresh in background."""
    main_module = _import_main_with_dependency_stubs(monkeypatch)

    calls = []

    def fake_startup_refresh() -> None:
        calls.append("refresh_ran_inline")

    class FakeThread:
        def __init__(
            self,
            *,
            target: Callable[[], None],
            name: str | None = None,
            daemon: bool | None = None,
        ) -> None:
            calls.append(("thread_init", target, name, daemon))

        def start(self) -> None:
            calls.append("thread_start")

    class FakeScheduler:
        def __init__(self) -> None:
            self.running = False

        def start(self) -> None:
            self.running = True
            calls.append("scheduler_start")

        def shutdown(self, wait: bool = False) -> None:
            self.running = False
            calls.append(("scheduler_shutdown", wait))

    def fake_scheduler_builder(*_args: object, **_kwargs: object) -> FakeScheduler:
        return FakeScheduler()

    monkeypatch.setattr(main_module, "_run_startup_fx_refresh", fake_startup_refresh)
    monkeypatch.setattr(main_module.threading, "Thread", FakeThread)
    monkeypatch.setattr(
        main_module,
        "build_fx_refresh_scheduler",
        fake_scheduler_builder,
    )

    async def exercise_lifespan() -> None:
        async with main_module.lifespan(main_module.app):
            assert "refresh_ran_inline" not in calls
            assert "thread_start" in calls

    asyncio.run(exercise_lifespan())

    assert calls[0][0] == "thread_init"
    assert calls[0][1] is fake_startup_refresh
    assert calls[0][2] == "fx-startup-refresh"
    assert calls[0][3] is True


def test_check_conversion_coverage_uses_supported_alias_and_prior_rate(
    db_session: Session,
) -> None:
    """Verify check conversion coverage uses supported alias and prior rate."""
    db_session.add(
        FXDailyReferenceRate(
            rate_date=date(2025, 12, 31),
            base_currency="EUR",
            quoted_currency="USD",
            units_per_base=Decimal("1.2500"),
            source_name="ECB_EXR",
            fetched_at=datetime(2026, 1, 2, 8, 30, 0, tzinfo=UTC),
            updated_at=datetime(2026, 1, 2, 8, 30, 0, tzinfo=UTC),
        )
    )
    db_session.commit()

    service = ECBExchangeRateService(db_session)

    result = service.check_conversion_coverage(
        [
            FXConversionCoverageRequest(
                raw_currency="xUSD",
                reporting_currency="EUR",
                transaction_date=date(2026, 1, 1),
            )
        ]
    )

    assert result.status == FXConversionCoverageStatus.ALREADY_COVERED
    assert result.required_quotes == ("USD",)
    assert result.missing_dates == ()


def test_check_conversion_coverage_treats_identity_as_covered_without_rows(
    db_session: Session,
) -> None:
    """Verify check conversion coverage treats identity as covered without rows."""
    service = ECBExchangeRateService(db_session)

    result = service.check_conversion_coverage(
        [
            FXConversionCoverageRequest(
                raw_currency="xUSD",
                reporting_currency="USD",
                transaction_date=date(2026, 1, 1),
            )
        ]
    )

    assert result.status == FXConversionCoverageStatus.ALREADY_COVERED
    assert result.required_quotes == ()
    assert result.missing_dates == ()


def test_check_conversion_coverage_short_circuits_unsupported_currency(
    db_session: Session,
) -> None:
    """Verify check conversion coverage short circuits unsupported currency."""
    service = ECBExchangeRateService(db_session)

    result = service.check_conversion_coverage(
        [
            FXConversionCoverageRequest(
                raw_currency="NEXO",
                reporting_currency="EUR",
                transaction_date=date(2026, 1, 1),
            )
        ]
    )

    assert result.status == FXConversionCoverageStatus.UNSUPPORTED
    assert result.required_quotes == ()
    assert result.missing_dates == ()


def test_check_conversion_coverage_ignores_unsupported_when_supported_pair_needs_fetch(
    db_session: Session,
) -> None:
    """Verify unsupported input does not hide supported missing FX."""
    service = ECBExchangeRateService(db_session)

    result = service.check_conversion_coverage(
        [
            FXConversionCoverageRequest(
                raw_currency="NEXO",
                reporting_currency="EUR",
                transaction_date=date(2026, 1, 2),
            ),
            FXConversionCoverageRequest(
                raw_currency="xUSD",
                reporting_currency="EUR",
                transaction_date=date(2026, 1, 1),
            ),
        ]
    )

    assert result.status == FXConversionCoverageStatus.MISSING
    assert result.required_quotes == ("USD",)
    assert result.missing_dates == (date(2026, 1, 1),)


def test_check_conversion_coverage_reports_missing_date_for_supported_pair(
    db_session: Session,
) -> None:
    """Verify check conversion coverage reports missing date for supported pair."""
    service = ECBExchangeRateService(db_session)

    result = service.check_conversion_coverage(
        [
            FXConversionCoverageRequest(
                raw_currency="xUSD",
                reporting_currency="EUR",
                transaction_date=date(2026, 1, 1),
            )
        ]
    )

    assert result.status == FXConversionCoverageStatus.MISSING
    assert result.required_quotes == ("USD",)
    assert result.missing_dates == (date(2026, 1, 1),)


def test_ensure_conversion_coverage_fetches_missing_range_with_lookback(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify ensure conversion coverage fetches missing range with lookback."""
    service = ECBExchangeRateService(db_session)
    refresh_calls: list[tuple[date, date]] = []

    def fake_refresh_range(start_date: date, end_date: date) -> FXRefreshResult:
        refresh_calls.append((start_date, end_date))
        db_session.add(
            FXDailyReferenceRate(
                rate_date=date(2025, 12, 31),
                base_currency="EUR",
                quoted_currency="USD",
                units_per_base=Decimal("1.2500"),
                source_name="ECB_EXR",
                fetched_at=datetime(2026, 1, 2, 8, 30, 0, tzinfo=UTC),
                updated_at=datetime(2026, 1, 2, 8, 30, 0, tzinfo=UTC),
            )
        )
        db_session.commit()
        return FXRefreshResult(
            start_date=start_date,
            end_date=end_date,
            inserted_or_updated_rows=1,
            missing_publication_days=[],
            missing_working_days=[],
        )

    monkeypatch.setattr(service, "refresh_range", fake_refresh_range)

    result = service.ensure_conversion_coverage(
        [
            FXConversionCoverageRequest(
                raw_currency="xUSD",
                reporting_currency="EUR",
                transaction_date=date(2026, 1, 1),
            )
        ],
        lock_timeout_seconds=0.0,
    )

    assert result.status == FXConversionCoverageStatus.FETCHED_AND_COVERED
    assert result.start_date == date(2025, 12, 22)
    assert result.end_date == date(2026, 1, 1)
    assert refresh_calls == [(date(2025, 12, 22), date(2026, 1, 1))]


def test_ensure_conversion_coverage_rechecks_after_lock_before_fetching(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify ensure conversion coverage rechecks after lock before fetching."""
    service = ECBExchangeRateService(db_session)
    refresh_calls: list[tuple[date, date]] = []

    @contextmanager
    def fake_lock(*_args: object, **_kwargs: object) -> Iterator[bool]:
        db_session.add(
            FXDailyReferenceRate(
                rate_date=date(2025, 12, 31),
                base_currency="EUR",
                quoted_currency="USD",
                units_per_base=Decimal("1.2500"),
                source_name="ECB_EXR",
                fetched_at=datetime(2026, 1, 2, 8, 30, 0, tzinfo=UTC),
                updated_at=datetime(2026, 1, 2, 8, 30, 0, tzinfo=UTC),
            )
        )
        db_session.commit()
        yield True

    monkeypatch.setattr(
        "app.services.ecb_exchange_rates.acquire_fx_refresh_lock", fake_lock
    )
    monkeypatch.setattr(
        service,
        "refresh_range",
        lambda start_date, end_date: refresh_calls.append((start_date, end_date)),
    )

    result = service.ensure_conversion_coverage(
        [
            FXConversionCoverageRequest(
                raw_currency="xUSD",
                reporting_currency="EUR",
                transaction_date=date(2026, 1, 1),
            )
        ],
        lock_timeout_seconds=0.0,
    )

    assert result.status == FXConversionCoverageStatus.ALREADY_COVERED
    assert refresh_calls == []


def test_ensure_conversion_coverage_returns_lock_timeout_without_fetch(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify ensure conversion coverage returns lock timeout without fetch."""
    service = ECBExchangeRateService(db_session)
    refresh_calls: list[tuple[date, date]] = []

    @contextmanager
    def fake_lock(*_args: object, **_kwargs: object) -> Iterator[bool]:
        yield False

    monkeypatch.setattr(
        "app.services.ecb_exchange_rates.acquire_fx_refresh_lock", fake_lock
    )
    monkeypatch.setattr(
        service,
        "refresh_range",
        lambda start_date, end_date: refresh_calls.append((start_date, end_date)),
    )

    result = service.ensure_conversion_coverage(
        [
            FXConversionCoverageRequest(
                raw_currency="xUSD",
                reporting_currency="EUR",
                transaction_date=date(2026, 1, 1),
            )
        ],
        lock_timeout_seconds=0.0,
    )

    assert result.status == FXConversionCoverageStatus.LOCK_TIMEOUT
    assert result.missing_dates == (date(2026, 1, 1),)
    assert refresh_calls == []


def test_ensure_conversion_coverage_returns_fetch_failure_without_raising(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify ensure conversion coverage returns fetch failure without raising."""
    service = ECBExchangeRateService(db_session)

    def fake_refresh_range(_start_date: date, _end_date: date) -> Never:
        msg = "ECB unavailable"
        raise RuntimeError(msg)

    monkeypatch.setattr(service, "refresh_range", fake_refresh_range)

    result = service.ensure_conversion_coverage(
        [
            FXConversionCoverageRequest(
                raw_currency="xUSD",
                reporting_currency="EUR",
                transaction_date=date(2026, 1, 1),
            )
        ],
        lock_timeout_seconds=0.0,
    )

    assert result.status == FXConversionCoverageStatus.FETCH_FAILED
    assert result.error == "ECB unavailable"
    assert result.missing_dates == (date(2026, 1, 1),)


def test_fx_refresh_lock_bounds_sleep_to_remaining_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify fx refresh lock bounds sleep to remaining timeout."""
    current_time = 0.0
    sleep_calls: list[float] = []

    class FakeFcntl:
        LOCK_EX = 1
        LOCK_NB = 2
        LOCK_UN = 4

        def flock(self, _file_number: int, _operation: int) -> Never:
            raise BlockingIOError

    def fake_monotonic() -> float:
        return current_time

    def fake_sleep(seconds: float) -> None:
        nonlocal current_time
        sleep_calls.append(seconds)
        current_time += seconds

    monkeypatch.setattr(fx_refresh_lock, "fcntl", FakeFcntl())
    monkeypatch.setattr(fx_refresh_lock.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(fx_refresh_lock.time, "sleep", fake_sleep)

    with fx_refresh_lock.acquire_fx_refresh_lock(
        str(tmp_path / "test.db"),
        timeout_seconds=0.25,
        poll_seconds=0.2,
    ) as acquired:
        assert acquired is False

    assert sleep_calls == pytest.approx([0.2, 0.05])


def test_fx_refresh_lock_uses_positive_sleep_for_non_positive_poll(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify fx refresh lock uses positive sleep for non positive poll."""
    current_time = 0.0
    sleep_calls: list[float] = []

    class FakeFcntl:
        LOCK_EX = 1
        LOCK_NB = 2
        LOCK_UN = 4

        def flock(self, _file_number: int, _operation: int) -> Never:
            raise BlockingIOError

    def fake_monotonic() -> float:
        return current_time

    def fake_sleep(seconds: float) -> None:
        nonlocal current_time
        assert seconds > 0
        sleep_calls.append(seconds)
        current_time += seconds

    monkeypatch.setattr(fx_refresh_lock, "fcntl", FakeFcntl())
    monkeypatch.setattr(fx_refresh_lock.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(fx_refresh_lock.time, "sleep", fake_sleep)

    with fx_refresh_lock.acquire_fx_refresh_lock(
        str(tmp_path / "test.db"),
        timeout_seconds=0.005,
        poll_seconds=0.0,
    ) as acquired:
        assert acquired is False

    assert sleep_calls == pytest.approx([0.005])
