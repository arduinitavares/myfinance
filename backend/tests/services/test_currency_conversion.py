"""Module for backend tests services test_currency_conversion."""

from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import get_type_hints

from app.models.fx import FXDailyReferenceRate
from app.schemas.transaction import serialize_display_money
from app.services.currency_conversion import CurrencyConversionService, DisplayMoney
from app.services.fx_pairs import required_fx_quotes
from sqlalchemy.orm import Session

FETCHED_AT: datetime = datetime(2026, 4, 17, 8, 30, 0, tzinfo=UTC)


def _store_rate(
    db_session: Session,
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
            fetched_at=FETCHED_AT,
            updated_at=FETCHED_AT,
        )
    )
    db_session.commit()


def test_required_fx_quotes_matches_eur_base_conversion_pairs() -> None:
    """Verify required fx quotes matches eur base conversion pairs."""
    assert required_fx_quotes(
        raw_currency="EUR", reporting_currency="USD", base_currency="EUR"
    ) == ("USD",)
    assert required_fx_quotes(
        raw_currency="USD", reporting_currency="EUR", base_currency="EUR"
    ) == ("USD",)
    assert required_fx_quotes(
        raw_currency="USD", reporting_currency="BRL", base_currency="EUR"
    ) == (
        "BRL",
        "USD",
    )
    assert (
        required_fx_quotes(
            raw_currency="USD", reporting_currency="USD", base_currency="EUR"
        )
        == ()
    )


def test_convert_identity_path_quantizes_and_marks_rate_as_same_day(
    db_session: Session,
) -> None:
    """Verify convert identity path quantizes and marks rate as same day."""
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


def test_convert_public_contract_accepts_decimal_and_float_amounts() -> None:
    """Verify convert public contract accepts decimal and float amounts."""
    raw_amount_hint = get_type_hints(CurrencyConversionService.convert)["raw_amount"]

    assert raw_amount_hint == Decimal | float


def test_convert_falls_back_to_most_recent_prior_rate_date(
    db_session: Session,
) -> None:
    """Verify convert falls back to most recent prior rate date."""
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


def test_convert_accepts_float_amounts_from_transaction_storage_path(
    db_session: Session,
) -> None:
    """Verify convert accepts float amounts from transaction storage path."""
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


def test_convert_cross_currency_uses_eur_native_rates(db_session: Session) -> None:
    """Verify convert cross currency uses eur native rates."""
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


def test_convert_uses_latest_prior_date_with_complete_quote_set(
    db_session: Session,
) -> None:
    """Verify convert uses latest prior date with complete quote set."""
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


def test_convert_prefers_exact_date_when_exact_and_prior_complete_quote_sets_exist(
    db_session: Session,
) -> None:
    """Verify exact date is preferred over prior complete quote sets."""
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


def test_convert_inverse_path_keeps_unrounded_internal_fx_rate(
    db_session: Session,
) -> None:
    """Verify convert inverse path keeps unrounded internal fx rate."""
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


def test_convert_returns_unavailable_when_no_exact_or_prior_rate_exists(
    db_session: Session,
) -> None:
    """Verify convert returns unavailable when no exact or prior rate exists."""
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


def test_convert_returns_distinct_unavailable_result_for_unsupported_currency(
    db_session: Session,
) -> None:
    """Verify convert returns distinct unavailable result for unsupported currency."""
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


def test_convert_normalizes_supported_alias_before_conversion(
    db_session: Session,
) -> None:
    """Verify convert normalizes supported alias before conversion."""
    _store_rate(
        db_session,
        rate_date=date(2026, 4, 17),
        quoted_currency="USD",
        units_per_base="1.2500",
    )
    service = CurrencyConversionService(db_session)

    result = service.convert(
        raw_amount=Decimal("10.00"),
        raw_currency="xUSD",
        reporting_currency="EUR",
        transaction_date=date(2026, 4, 17),
    )

    assert result == DisplayMoney(
        display_amount=Decimal("8.00"),
        display_currency="EUR",
        display_fx_rate=Decimal("0.8"),
        display_rate_date=date(2026, 4, 17),
        is_available=True,
        unavailable_reason=None,
    )


def test_serialize_display_money_includes_explicit_availability_fields() -> None:
    """Verify serialize display money includes explicit availability fields."""
    payload = serialize_display_money(
        DisplayMoney.unavailable(display_currency="BRL", reason="unsupported_currency")
    )

    assert payload == {
        "display_amount": None,
        "display_currency": "BRL",
        "display_fx_rate": None,
        "display_rate_date": None,
        "display_is_available": False,
        "display_unavailable_reason": "unsupported_currency",
    }
