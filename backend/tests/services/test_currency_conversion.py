from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import get_type_hints

from app.models.fx import FXDailyReferenceRate
from app.services.currency_conversion import CurrencyConversionService, DisplayMoney


def _store_rate(
    db_session,
    *,
    rate_date: date,
    quoted_currency: str,
    units_per_base: str,
) -> None:
    db_session.add(
        FXDailyReferenceRate(
            rate_date=rate_date,
            base_currency="EUR",
            quoted_currency=quoted_currency,
            units_per_base=Decimal(units_per_base),
            source_name="ECB_EXR",
            fetched_at=datetime(2026, 4, 17, 8, 30, 0),
            updated_at=datetime(2026, 4, 17, 8, 30, 0),
        )
    )
    db_session.commit()


def test_convert_identity_path_quantizes_and_marks_rate_as_same_day(db_session):
    service = CurrencyConversionService(db_session)

    result = service.convert(
        raw_amount=Decimal("1.005"),
        raw_currency="USD",
        reporting_currency="USD",
        transaction_date=date(2026, 4, 17),
    )

    assert result == DisplayMoney(
        display_amount=Decimal("1.01"),
        display_currency="USD",
        display_fx_rate=Decimal("1.0"),
        display_rate_date=date(2026, 4, 17),
        is_available=True,
        unavailable_reason=None,
    )


def test_convert_public_contract_accepts_decimal_and_float_amounts():
    raw_amount_hint = get_type_hints(CurrencyConversionService.convert)["raw_amount"]

    assert raw_amount_hint == Decimal | float


def test_convert_falls_back_to_most_recent_prior_rate_date(db_session):
    _store_rate(
        db_session,
        rate_date=date(2026, 4, 16),
        quoted_currency="USD",
        units_per_base="1.2000",
    )
    service = CurrencyConversionService(db_session)

    result = service.convert(
        raw_amount=Decimal("123.456"),
        raw_currency="EUR",
        reporting_currency="USD",
        transaction_date=date(2026, 4, 17),
    )

    assert result == DisplayMoney(
        display_amount=Decimal("148.15"),
        display_currency="USD",
        display_fx_rate=Decimal("1.2000"),
        display_rate_date=date(2026, 4, 16),
        is_available=True,
        unavailable_reason=None,
    )


def test_convert_accepts_float_amounts_from_transaction_storage_path(db_session):
    _store_rate(
        db_session,
        rate_date=date(2026, 4, 16),
        quoted_currency="USD",
        units_per_base="1.2000",
    )
    service = CurrencyConversionService(db_session)

    result = service.convert(
        raw_amount=123.456,
        raw_currency="EUR",
        reporting_currency="USD",
        transaction_date=date(2026, 4, 17),
    )

    assert result == DisplayMoney(
        display_amount=Decimal("148.15"),
        display_currency="USD",
        display_fx_rate=Decimal("1.2000"),
        display_rate_date=date(2026, 4, 16),
        is_available=True,
        unavailable_reason=None,
    )


def test_convert_cross_currency_uses_eur_native_rates(db_session):
    _store_rate(
        db_session,
        rate_date=date(2026, 4, 17),
        quoted_currency="USD",
        units_per_base="1.2500",
    )
    _store_rate(
        db_session,
        rate_date=date(2026, 4, 17),
        quoted_currency="BRL",
        units_per_base="6.5000",
    )
    service = CurrencyConversionService(db_session)

    result = service.convert(
        raw_amount=Decimal("10.00"),
        raw_currency="USD",
        reporting_currency="BRL",
        transaction_date=date(2026, 4, 17),
    )

    assert result == DisplayMoney(
        display_amount=Decimal("52.00"),
        display_currency="BRL",
        display_fx_rate=Decimal("5.2"),
        display_rate_date=date(2026, 4, 17),
        is_available=True,
        unavailable_reason=None,
    )


def test_convert_uses_latest_prior_date_with_complete_quote_set(db_session):
    _store_rate(
        db_session,
        rate_date=date(2026, 4, 16),
        quoted_currency="USD",
        units_per_base="1.2500",
    )
    _store_rate(
        db_session,
        rate_date=date(2026, 4, 16),
        quoted_currency="BRL",
        units_per_base="6.5000",
    )
    _store_rate(
        db_session,
        rate_date=date(2026, 4, 17),
        quoted_currency="USD",
        units_per_base="1.3000",
    )
    service = CurrencyConversionService(db_session)

    result = service.convert(
        raw_amount=Decimal("10.00"),
        raw_currency="USD",
        reporting_currency="BRL",
        transaction_date=date(2026, 4, 17),
    )

    assert result == DisplayMoney(
        display_amount=Decimal("52.00"),
        display_currency="BRL",
        display_fx_rate=Decimal("5.2"),
        display_rate_date=date(2026, 4, 16),
        is_available=True,
        unavailable_reason=None,
    )


def test_convert_prefers_exact_date_when_exact_and_prior_complete_quote_sets_exist(db_session):
    _store_rate(
        db_session,
        rate_date=date(2026, 4, 16),
        quoted_currency="USD",
        units_per_base="1.2500",
    )
    _store_rate(
        db_session,
        rate_date=date(2026, 4, 16),
        quoted_currency="BRL",
        units_per_base="6.5000",
    )
    _store_rate(
        db_session,
        rate_date=date(2026, 4, 17),
        quoted_currency="USD",
        units_per_base="1.3000",
    )
    _store_rate(
        db_session,
        rate_date=date(2026, 4, 17),
        quoted_currency="BRL",
        units_per_base="6.5000",
    )
    service = CurrencyConversionService(db_session)

    result = service.convert(
        raw_amount=Decimal("10.00"),
        raw_currency="USD",
        reporting_currency="BRL",
        transaction_date=date(2026, 4, 17),
    )

    assert result == DisplayMoney(
        display_amount=Decimal("50.00"),
        display_currency="BRL",
        display_fx_rate=Decimal("5"),
        display_rate_date=date(2026, 4, 17),
        is_available=True,
        unavailable_reason=None,
    )


def test_convert_inverse_path_keeps_unrounded_internal_fx_rate(db_session):
    _store_rate(
        db_session,
        rate_date=date(2026, 4, 17),
        quoted_currency="USD",
        units_per_base="1.23456789",
    )
    service = CurrencyConversionService(db_session)

    result = service.convert(
        raw_amount=Decimal("10.00"),
        raw_currency="USD",
        reporting_currency="EUR",
        transaction_date=date(2026, 4, 17),
    )

    expected_fx_rate = Decimal("1") / Decimal("1.23456789")

    assert result == DisplayMoney(
        display_amount=(Decimal("10.00") * expected_fx_rate).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        ),
        display_currency="EUR",
        display_fx_rate=expected_fx_rate,
        display_rate_date=date(2026, 4, 17),
        is_available=True,
        unavailable_reason=None,
    )


def test_convert_returns_unavailable_when_no_exact_or_prior_rate_exists(db_session):
    _store_rate(
        db_session,
        rate_date=date(2026, 4, 18),
        quoted_currency="USD",
        units_per_base="1.2000",
    )
    service = CurrencyConversionService(db_session)

    result = service.convert(
        raw_amount=Decimal("10.00"),
        raw_currency="EUR",
        reporting_currency="USD",
        transaction_date=date(2026, 4, 17),
    )

    assert result == DisplayMoney(
        display_amount=None,
        display_currency="USD",
        display_fx_rate=None,
        display_rate_date=None,
        is_available=False,
        unavailable_reason="missing_rate",
    )


def test_convert_returns_distinct_unavailable_result_for_unsupported_currency(db_session):
    service = CurrencyConversionService(db_session)

    result = service.convert(
        raw_amount=Decimal("10.00"),
        raw_currency="GBP",
        reporting_currency="USD",
        transaction_date=date(2026, 4, 17),
    )

    assert result == DisplayMoney(
        display_amount=None,
        display_currency="USD",
        display_fx_rate=None,
        display_rate_date=None,
        is_available=False,
        unavailable_reason="unsupported_currency",
    )
