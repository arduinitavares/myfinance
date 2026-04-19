import asyncio
import importlib
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from contextlib import contextmanager
import sys
import types

import pytest

from app.models.fx import FXDailyReferenceRate
from app.models.transaction import Transaction, TransactionType
from app.services.ecb_exchange_rates import ECBExchangeRateService
from app.services.ecb_exchange_rates import FXRefreshResult
from app.services.fx_refresh_scheduler import build_fx_refresh_scheduler


def _import_main_with_dependency_stubs(monkeypatch):
    class FakeSentenceTransformer:
        def __init__(self, *args, **kwargs):
            pass

        def encode(self, *args, **kwargs):
            return [0.0]

    class FakeQdrantClient:
        def __init__(self, *args, **kwargs):
            pass

        def recreate_collection(self, *args, **kwargs):
            return None

        def upsert(self, *args, **kwargs):
            return None

        def get_collection(self, *args, **kwargs):
            return SimpleNamespace(points_count=0)

        def search_points(self, *args, **kwargs):
            return []

    class FakeVectorParams:
        def __init__(self, *args, **kwargs):
            pass

    class FakePointStruct:
        def __init__(self, *args, **kwargs):
            pass

    sentence_transformers_module = types.ModuleType("sentence_transformers")
    sentence_transformers_module.SentenceTransformer = FakeSentenceTransformer

    pandas_module = types.ModuleType("pandas")
    pandas_module.DataFrame = object
    pandas_module.notna = lambda value: value is not None

    qdrant_module = types.ModuleType("qdrant_client")
    qdrant_module.QdrantClient = FakeQdrantClient

    qdrant_http_module = types.ModuleType("qdrant_client.http")
    qdrant_http_models_module = types.ModuleType("qdrant_client.http.models")
    qdrant_http_models_module.VectorParams = FakeVectorParams
    qdrant_http_models_module.PointStruct = FakePointStruct
    qdrant_http_models_module.Distance = SimpleNamespace(COSINE="cosine")
    qdrant_http_module.models = qdrant_http_models_module

    monkeypatch.setitem(sys.modules, "sentence_transformers", sentence_transformers_module)
    monkeypatch.setitem(sys.modules, "pandas", pandas_module)
    monkeypatch.setitem(sys.modules, "qdrant_client", qdrant_module)
    monkeypatch.setitem(sys.modules, "qdrant_client.http", qdrant_http_module)
    monkeypatch.setitem(sys.modules, "qdrant_client.http.models", qdrant_http_models_module)

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


def _stored_rates(db_session):
    return (
        db_session.query(FXDailyReferenceRate)
        .order_by(FXDailyReferenceRate.rate_date, FXDailyReferenceRate.quoted_currency)
        .all()
    )


def test_earliest_covered_date_returns_none_for_empty_table(db_session):
    service = ECBExchangeRateService(db_session)

    assert service.earliest_covered_date() is None


def test_earliest_covered_date_returns_minimum_rate_date(db_session):
    db_session.add_all(
        [
            FXDailyReferenceRate(
                rate_date=date(2026, 4, 17),
                base_currency="EUR",
                quoted_currency="USD",
                units_per_base=Decimal("1.1100"),
                source_name="ECB_EXR",
                fetched_at=datetime(2026, 4, 17, 8, 30, 0),
                updated_at=datetime(2026, 4, 17, 8, 30, 0),
            ),
            FXDailyReferenceRate(
                rate_date=date(2026, 4, 15),
                base_currency="EUR",
                quoted_currency="USD",
                units_per_base=Decimal("1.1000"),
                source_name="ECB_EXR",
                fetched_at=datetime(2026, 4, 15, 8, 30, 0),
                updated_at=datetime(2026, 4, 15, 8, 30, 0),
            ),
            FXDailyReferenceRate(
                rate_date=date(2026, 4, 15),
                base_currency="EUR",
                quoted_currency="BRL",
                units_per_base=Decimal("6.0100"),
                source_name="ECB_EXR",
                fetched_at=datetime(2026, 4, 15, 8, 30, 0),
                updated_at=datetime(2026, 4, 15, 8, 30, 0),
            ),
            FXDailyReferenceRate(
                rate_date=date(2026, 4, 14),
                base_currency="USD",
                quoted_currency="EUR",
                units_per_base=Decimal("0.9000"),
                source_name="OTHER",
                fetched_at=datetime(2026, 4, 14, 8, 30, 0),
                updated_at=datetime(2026, 4, 14, 8, 30, 0),
            ),
        ]
    )
    db_session.commit()

    service = ECBExchangeRateService(db_session)

    assert service.earliest_covered_date() == date(2026, 4, 15)


def test_earliest_covered_date_ignores_partial_coverage_until_both_quotes_exist(db_session):
    db_session.add_all(
        [
            FXDailyReferenceRate(
                rate_date=date(2026, 4, 14),
                base_currency="EUR",
                quoted_currency="USD",
                units_per_base=Decimal("1.0900"),
                source_name="ECB_EXR",
                fetched_at=datetime(2026, 4, 14, 8, 30, 0),
                updated_at=datetime(2026, 4, 14, 8, 30, 0),
            ),
            FXDailyReferenceRate(
                rate_date=date(2026, 4, 15),
                base_currency="EUR",
                quoted_currency="USD",
                units_per_base=Decimal("1.1000"),
                source_name="ECB_EXR",
                fetched_at=datetime(2026, 4, 15, 8, 30, 0),
                updated_at=datetime(2026, 4, 15, 8, 30, 0),
            ),
            FXDailyReferenceRate(
                rate_date=date(2026, 4, 15),
                base_currency="EUR",
                quoted_currency="BRL",
                units_per_base=Decimal("6.0100"),
                source_name="ECB_EXR",
                fetched_at=datetime(2026, 4, 15, 8, 30, 0),
                updated_at=datetime(2026, 4, 15, 8, 30, 0),
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
def test_latest_publication_day_on_or_before_handles_weekends_and_closing_days(db_session, day, expected):
    service = ECBExchangeRateService(db_session)

    assert service.latest_publication_day_on_or_before(day) == expected


def test_get_xml_response_uses_configured_timeout_for_injected_http_client(db_session):
    class FakeResponse:
        def __init__(self):
            self.raise_for_status_called = False

        def raise_for_status(self):
            self.raise_for_status_called = True

    class FakeHttpClient:
        def __init__(self):
            self.calls = []

        def get(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return FakeResponse()

    http_client = FakeHttpClient()
    service = ECBExchangeRateService(db_session, http_client=http_client, timeout=12.5)

    response = service._get_xml_response("https://example.com/rates.xml")

    assert isinstance(response, FakeResponse)
    assert http_client.calls == [
        (
            "https://example.com/rates.xml",
            {"timeout": 12.5, "follow_redirects": True},
        )
    ]
    assert response.raise_for_status_called is True


def test_get_xml_response_uses_configured_timeout_for_default_http_client(db_session, monkeypatch):
    init_kwargs = {}
    get_kwargs = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, **kwargs):
            init_kwargs.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url, **kwargs):
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


def test_has_historical_seed_coverage_requires_boundary_coverage_for_both_supported_quotes(db_session):
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
        now_provider=lambda: datetime(2026, 4, 17, 8, 30, 0),
    )
    db_session.add_all(
        [
            FXDailyReferenceRate(
                rate_date=date(2026, 4, 16),
                base_currency="EUR",
                quoted_currency="USD",
                units_per_base=Decimal("1.1100"),
                source_name="ECB_EXR",
                fetched_at=datetime(2026, 4, 16, 8, 30, 0),
                updated_at=datetime(2026, 4, 16, 8, 30, 0),
            ),
            FXDailyReferenceRate(
                rate_date=date(2026, 4, 16),
                base_currency="EUR",
                quoted_currency="BRL",
                units_per_base=Decimal("6.0100"),
                source_name="ECB_EXR",
                fetched_at=datetime(2026, 4, 16, 8, 30, 0),
                updated_at=datetime(2026, 4, 16, 8, 30, 0),
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
            fetched_at=datetime(2026, 4, 17, 8, 30, 0),
            updated_at=datetime(2026, 4, 17, 8, 30, 0),
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
            fetched_at=datetime(2026, 4, 17, 8, 30, 0),
            updated_at=datetime(2026, 4, 17, 8, 30, 0),
        )
    )
    db_session.commit()

    assert service.has_historical_seed_coverage(today=date(2026, 4, 17)) is True


def test_has_historical_seed_coverage_detects_mid_history_gap_between_boundaries(db_session):
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
        now_provider=lambda: datetime(2026, 4, 17, 8, 30, 0),
    )
    db_session.add_all(
        [
            FXDailyReferenceRate(
                rate_date=rate_date,
                base_currency="EUR",
                quoted_currency=quoted_currency,
                units_per_base=Decimal("1.1100") if quoted_currency == "USD" else Decimal("6.0100"),
                source_name="ECB_EXR",
                fetched_at=datetime(2026, 4, 17, 8, 30, 0),
                updated_at=datetime(2026, 4, 17, 8, 30, 0),
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
                units_per_base=Decimal("1.1200") if quoted_currency == "USD" else Decimal("6.0200"),
                source_name="ECB_EXR",
                fetched_at=datetime(2026, 4, 17, 9, 0, 0),
                updated_at=datetime(2026, 4, 17, 9, 0, 0),
            )
            for quoted_currency in ("USD", "BRL")
        ]
    )
    db_session.commit()

    assert service.has_historical_seed_coverage(today=date(2026, 4, 17)) is True


def test_seed_historical_rates_uses_last_five_years_when_no_transactions(db_session, monkeypatch):
    today = date(2026, 4, 17)
    monkeypatch.setattr(
        ECBExchangeRateService,
        "_fetch_series",
        lambda self, start_date, end_date: {
            date(2021, 4, 16): {"USD": Decimal("1.0500"), "BRL": Decimal("5.5000")},
            date(2021, 4, 17): {"USD": Decimal("1.0600"), "BRL": Decimal("5.6000")},
            date(2026, 4, 17): {"USD": Decimal("1.1700"), "BRL": Decimal("6.2000")},
        },
    )

    service = ECBExchangeRateService(
        db_session,
        now_provider=lambda: datetime(2026, 4, 17, 8, 30, 0),
    )

    result = service.seed_historical_rates(today=today)

    assert result.start_date == date(2021, 4, 17)
    assert result.end_date == today
    assert {(row.rate_date, row.quoted_currency) for row in _stored_rates(db_session)} == {
        (date(2021, 4, 17), "BRL"),
        (date(2021, 4, 17), "USD"),
        (date(2026, 4, 17), "BRL"),
        (date(2026, 4, 17), "USD"),
    }


def test_seed_historical_rates_uses_earliest_transaction_date_when_present(db_session, monkeypatch):
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
        lambda self, start_date, end_date: {
            date(2024, 2, 13): {"USD": Decimal("1.0200"), "BRL": Decimal("5.3000")},
            date(2024, 2, 14): {"USD": Decimal("1.0300"), "BRL": Decimal("5.4000")},
            date(2026, 4, 17): {"USD": Decimal("1.1700"), "BRL": Decimal("6.2000")},
        },
    )

    service = ECBExchangeRateService(
        db_session,
        now_provider=lambda: datetime(2026, 4, 17, 8, 30, 0),
    )

    result = service.seed_historical_rates(today=date(2026, 4, 17))

    assert result.start_date == date(2024, 2, 14)
    assert {(row.rate_date, row.quoted_currency) for row in _stored_rates(db_session)} == {
        (date(2024, 2, 14), "BRL"),
        (date(2024, 2, 14), "USD"),
        (date(2026, 4, 17), "BRL"),
        (date(2026, 4, 17), "USD"),
    }


def test_refresh_range_upserts_existing_rows_without_duplicates(db_session, monkeypatch):
    first_run_at = datetime(2026, 4, 17, 8, 30, 0)
    second_run_at = datetime(2026, 4, 17, 9, 45, 0)

    service = ECBExchangeRateService(db_session, now_provider=lambda: first_run_at)
    monkeypatch.setattr(
        ECBExchangeRateService,
        "_fetch_series",
        lambda self, start_date, end_date: {
            date(2026, 4, 16): {"USD": Decimal("1.1100"), "BRL": Decimal("6.0100")},
        },
    )

    first_result = service.refresh_range(date(2026, 4, 16), date(2026, 4, 16))
    first_rows = _stored_rates(db_session)
    first_updated_at = {
        row.quoted_currency: row.updated_at
        for row in first_rows
    }

    monkeypatch.setattr(
        ECBExchangeRateService,
        "_fetch_series",
        lambda self, start_date, end_date: {
            date(2026, 4, 16): {"USD": Decimal("1.2100"), "BRL": Decimal("6.1100")},
        },
    )
    service = ECBExchangeRateService(db_session, now_provider=lambda: second_run_at)
    second_result = service.refresh_range(date(2026, 4, 16), date(2026, 4, 16))

    db_session.expire_all()
    rows = _stored_rates(db_session)

    assert first_result.inserted_or_updated_rows == 2
    assert second_result.inserted_or_updated_rows == 2
    assert len(rows) == 2
    assert {row.quoted_currency: row.units_per_base for row in rows} == {
        "BRL": Decimal("6.11000000"),
        "USD": Decimal("1.21000000"),
    }
    assert {row.quoted_currency: row.fetched_at for row in rows} == {
        "BRL": second_run_at,
        "USD": second_run_at,
    }
    assert all(row.updated_at >= first_updated_at[row.quoted_currency] for row in rows)


def test_refresh_range_skips_unchanged_rows_without_timestamp_churn(db_session, monkeypatch):
    first_run_at = datetime(2026, 4, 17, 8, 30, 0)
    second_run_at = datetime(2026, 4, 17, 9, 45, 0)
    sample_series = {
        date(2026, 4, 16): {"USD": Decimal("1.1100"), "BRL": Decimal("6.0100")},
    }

    monkeypatch.setattr(ECBExchangeRateService, "_fetch_series", lambda self, start_date, end_date: sample_series)

    first_service = ECBExchangeRateService(db_session, now_provider=lambda: first_run_at)
    first_result = first_service.refresh_range(date(2026, 4, 16), date(2026, 4, 16))

    first_rows = _stored_rates(db_session)
    first_timestamps = {
        row.quoted_currency: (row.fetched_at, row.updated_at)
        for row in first_rows
    }

    second_service = ECBExchangeRateService(db_session, now_provider=lambda: second_run_at)
    second_result = second_service.refresh_range(date(2026, 4, 16), date(2026, 4, 16))

    db_session.expire_all()
    rows = _stored_rates(db_session)

    assert first_result.inserted_or_updated_rows == 2
    assert second_result.inserted_or_updated_rows == 0
    assert {
        row.quoted_currency: (row.fetched_at, row.updated_at)
        for row in rows
    } == first_timestamps


def test_catch_up_recent_days_ignores_weekend_gaps(db_session, monkeypatch):
    today = date(2026, 2, 20)
    start_date = date(2026, 1, 7)
    service = ECBExchangeRateService(
        db_session,
        now_provider=lambda: datetime(2026, 2, 20, 2, 0, 0),
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
        lambda self, start_date, end_date: series,
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


def test_refresh_range_reports_working_day_gap_for_missing_supported_quote(db_session, monkeypatch):
    monkeypatch.setattr(
        ECBExchangeRateService,
        "_fetch_series",
        lambda self, start_date, end_date: {
            date(2026, 4, 16): {"USD": Decimal("1.1100")},
        },
    )

    result = ECBExchangeRateService(
        db_session,
        now_provider=lambda: datetime(2026, 4, 16, 8, 30, 0),
    ).refresh_range(date(2026, 4, 16), date(2026, 4, 16))

    assert result.inserted_or_updated_rows == 1
    assert result.missing_publication_days == []
    assert result.missing_working_days == [(date(2026, 4, 16), "BRL")]


def test_build_fx_refresh_scheduler_registers_daily_utc_job():
    scheduler = build_fx_refresh_scheduler(lambda: None)

    try:
        job = scheduler.get_job("fx-daily-refresh")

        assert job is not None
        assert str(scheduler.timezone) == "UTC"
        assert str(job.trigger.timezone) == "UTC"
        assert str(job.trigger.fields[5]) == "2"
        assert str(job.trigger.fields[6]) == "0"
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)


def test_startup_refresh_seeds_history_before_recent_catch_up_when_fx_table_empty(monkeypatch):
    main_module = _import_main_with_dependency_stubs(monkeypatch)

    calls = []

    @contextmanager
    def fake_acquired_lock():
        yield True

    class FakeSessionContext:
        def __enter__(self):
            return object()

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeService:
        def __init__(self, db):
            calls.append("init")

        def has_historical_seed_coverage(self):
            calls.append("has_historical_seed_coverage")
            return False

        def seed_historical_rates(self):
            calls.append("seed_historical_rates")
            return FXRefreshResult(
                start_date=date(2021, 4, 17),
                end_date=date(2026, 4, 17),
                inserted_or_updated_rows=10,
                missing_publication_days=[],
                missing_working_days=[],
            )

        def catch_up_recent_days(self, *, window_days):
            calls.append(("catch_up_recent_days", window_days))
            return FXRefreshResult(
                start_date=date(2026, 3, 4),
                end_date=date(2026, 4, 17),
                inserted_or_updated_rows=2,
                missing_publication_days=[],
                missing_working_days=[],
            )

    monkeypatch.setattr(main_module, "_fx_refresh_lock", fake_acquired_lock)
    monkeypatch.setattr(main_module, "SessionLocal", lambda: FakeSessionContext())
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


def test_startup_refresh_skips_when_fx_lock_is_busy(monkeypatch):
    main_module = _import_main_with_dependency_stubs(monkeypatch)

    calls = []

    @contextmanager
    def fake_busy_lock():
        yield False

    class FakeSessionContext:
        def __enter__(self):
            calls.append("session_entered")
            return object()

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeService:
        def __init__(self, db):
            calls.append("service_init")

    monkeypatch.setattr(main_module, "_fx_refresh_lock", fake_busy_lock)
    monkeypatch.setattr(main_module, "SessionLocal", lambda: FakeSessionContext())
    monkeypatch.setattr(main_module, "ECBExchangeRateService", FakeService)

    main_module._run_startup_fx_refresh()

    assert calls == []


def test_lifespan_starts_startup_refresh_in_background(monkeypatch):
    main_module = _import_main_with_dependency_stubs(monkeypatch)

    calls = []

    def fake_startup_refresh():
        calls.append("refresh_ran_inline")

    class FakeThread:
        def __init__(self, *, target, name=None, daemon=None):
            calls.append(("thread_init", target, name, daemon))

        def start(self):
            calls.append("thread_start")

    class FakeScheduler:
        def __init__(self):
            self.running = False

        def start(self):
            self.running = True
            calls.append("scheduler_start")

        def shutdown(self, wait=False):
            self.running = False
            calls.append(("scheduler_shutdown", wait))

    monkeypatch.setattr(main_module, "_run_startup_fx_refresh", fake_startup_refresh)
    monkeypatch.setattr(main_module.threading, "Thread", FakeThread)
    monkeypatch.setattr(main_module, "build_fx_refresh_scheduler", lambda *args, **kwargs: FakeScheduler())

    async def exercise_lifespan():
        async with main_module.lifespan(main_module.app):
            assert "refresh_ran_inline" not in calls
            assert "thread_start" in calls

    asyncio.run(exercise_lifespan())

    assert calls[0][0] == "thread_init"
    assert calls[0][1] is fake_startup_refresh
    assert calls[0][2] == "fx-startup-refresh"
    assert calls[0][3] is True
