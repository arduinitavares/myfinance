from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.fx import FXDailyReferenceRate
from app.services.currency_aliases import normalize_currency_code
from app.services.ecb_exchange_rates import ECBExchangeRateService
from app.services.reporting_currency import ALLOWED_REPORTING_CURRENCIES


DISPLAY_PRECISION = Decimal("0.01")
IDENTITY_FX_RATE = Decimal("1.0")
RawAmount = Decimal | float


@dataclass(frozen=True)
class DisplayMoney:
    display_amount: Decimal | None
    display_currency: str
    display_fx_rate: Decimal | None
    display_rate_date: date | None
    is_available: bool
    unavailable_reason: str | None = None

    @classmethod
    def unavailable(cls, *, display_currency: str, reason: str) -> "DisplayMoney":
        return cls(
            display_amount=None,
            display_currency=display_currency,
            display_fx_rate=None,
            display_rate_date=None,
            is_available=False,
            unavailable_reason=reason,
        )


class CurrencyConversionService:
    BASE_CURRENCY = ECBExchangeRateService.BASE_CURRENCY
    SOURCE_NAME = ECBExchangeRateService.SOURCE_NAME
    SUPPORTED_CURRENCIES = frozenset(ALLOWED_REPORTING_CURRENCIES)

    def __init__(self, db: Session) -> None:
        self.db = db

    def convert(
        self,
        *,
        raw_amount: RawAmount,
        raw_currency: str,
        reporting_currency: str,
        transaction_date: date,
    ) -> DisplayMoney:
        normalized_raw_currency = normalize_currency_code(raw_currency)
        normalized_reporting_currency = normalize_currency_code(reporting_currency)
        decimal_amount = Decimal(str(raw_amount))

        if (
            normalized_raw_currency not in self.SUPPORTED_CURRENCIES
            or normalized_reporting_currency not in self.SUPPORTED_CURRENCIES
        ):
            return DisplayMoney.unavailable(
                display_currency=normalized_reporting_currency or reporting_currency.strip().upper(),
                reason="unsupported_currency",
            )

        if normalized_raw_currency == normalized_reporting_currency:
            return DisplayMoney(
                display_amount=self._quantize_amount(decimal_amount),
                display_currency=normalized_raw_currency,
                display_fx_rate=IDENTITY_FX_RATE,
                display_rate_date=transaction_date,
                is_available=True,
                unavailable_reason=None,
            )

        required_quotes = self._required_quotes(
            raw_currency=normalized_raw_currency,
            reporting_currency=normalized_reporting_currency,
        )
        rate_date = self._latest_rate_date(
            transaction_date=transaction_date,
            required_quotes=required_quotes,
        )
        if rate_date is None:
            return DisplayMoney.unavailable(
                display_currency=normalized_reporting_currency,
                reason="missing_rate",
            )

        eur_native_rates = self._load_eur_native_rates(rate_date=rate_date, required_quotes=required_quotes)
        if set(eur_native_rates) != set(required_quotes):
            return DisplayMoney.unavailable(
                display_currency=normalized_reporting_currency,
                reason="missing_rate",
            )

        display_fx_rate = self._display_fx_rate(
            raw_currency=normalized_raw_currency,
            reporting_currency=normalized_reporting_currency,
            eur_native_rates=eur_native_rates,
        )
        display_amount = self._quantize_amount(decimal_amount * display_fx_rate)

        return DisplayMoney(
            display_amount=display_amount,
            display_currency=normalized_reporting_currency,
            display_fx_rate=display_fx_rate,
            display_rate_date=rate_date,
            is_available=True,
            unavailable_reason=None,
        )

    def _required_quotes(self, *, raw_currency: str, reporting_currency: str) -> tuple[str, ...]:
        if raw_currency == self.BASE_CURRENCY:
            return (reporting_currency,)
        if reporting_currency == self.BASE_CURRENCY:
            return (raw_currency,)
        return tuple(sorted({raw_currency, reporting_currency}))

    def _latest_rate_date(
        self,
        *,
        transaction_date: date,
        required_quotes: tuple[str, ...],
    ) -> date | None:
        return self.db.execute(
            select(FXDailyReferenceRate.rate_date)
            .where(
                FXDailyReferenceRate.source_name == self.SOURCE_NAME,
                FXDailyReferenceRate.base_currency == self.BASE_CURRENCY,
                FXDailyReferenceRate.rate_date <= transaction_date,
                FXDailyReferenceRate.quoted_currency.in_(required_quotes),
            )
            .group_by(FXDailyReferenceRate.rate_date)
            .having(func.count(func.distinct(FXDailyReferenceRate.quoted_currency)) == len(required_quotes))
            .order_by(FXDailyReferenceRate.rate_date.desc())
            .limit(1)
        ).scalar_one_or_none()

    def _load_eur_native_rates(
        self,
        *,
        rate_date: date,
        required_quotes: tuple[str, ...],
    ) -> dict[str, Decimal]:
        rows = self.db.execute(
            select(FXDailyReferenceRate).where(
                FXDailyReferenceRate.source_name == self.SOURCE_NAME,
                FXDailyReferenceRate.base_currency == self.BASE_CURRENCY,
                FXDailyReferenceRate.rate_date == rate_date,
                FXDailyReferenceRate.quoted_currency.in_(required_quotes),
            )
        ).scalars()

        return {
            row.quoted_currency: Decimal(str(row.units_per_base))
            for row in rows
        }

    def _display_fx_rate(
        self,
        *,
        raw_currency: str,
        reporting_currency: str,
        eur_native_rates: dict[str, Decimal],
    ) -> Decimal:
        if raw_currency == self.BASE_CURRENCY:
            return eur_native_rates[reporting_currency]
        if reporting_currency == self.BASE_CURRENCY:
            return Decimal("1") / eur_native_rates[raw_currency]
        return eur_native_rates[reporting_currency] / eur_native_rates[raw_currency]

    def _quantize_amount(self, amount: Decimal) -> Decimal:
        return amount.quantize(DISPLAY_PRECISION, rounding=ROUND_HALF_UP)
