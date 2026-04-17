from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from contextlib import contextmanager

from app.models.fx import FXDailyReferenceRate
from app.models.transaction import Transaction, TransactionType
from app.services.ecb_exchange_rates import ECBExchangeRateService
from app.services.ecb_exchange_rates import FXRefreshResult
from app.services.fx_refresh_scheduler import build_fx_refresh_scheduler


def _stored_rates(db_session):
    return (
        db_session.query(FXDailyReferenceRate)
        .order_by(FXDailyReferenceRate.rate_date, FXDailyReferenceRate.quoted_currency)
        .all()
    )


def test_has_historical_seed_coverage_requires_boundary_coverage_for_both_supported_quotes(db_session):
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
            rate_date=date(2021, 4, 17),
            base_currency="EUR",
            quoted_currency="USD",
            units_per_base=Decimal("1.0500"),
            source_name="ECB_EXR",
            fetched_at=datetime(2021, 4, 17, 8, 30, 0),
            updated_at=datetime(2021, 4, 17, 8, 30, 0),
        )
    )
    db_session.commit()

    assert service.has_historical_seed_coverage(today=date(2026, 4, 17)) is False

    db_session.add(
        FXDailyReferenceRate(
            rate_date=date(2021, 4, 17),
            base_currency="EUR",
            quoted_currency="BRL",
            units_per_base=Decimal("5.5000"),
            source_name="ECB_EXR",
            fetched_at=datetime(2021, 4, 17, 8, 30, 0),
            updated_at=datetime(2021, 4, 17, 8, 30, 0),
        )
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
    import app.main as main_module

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
    import app.main as main_module

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
