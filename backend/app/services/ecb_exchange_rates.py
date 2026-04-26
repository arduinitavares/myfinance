"""Module for backend app services ecb_exchange_rates."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar

import httpx
from defusedxml import ElementTree
from sqlalchemy import func, select

from app.config import settings
from app.models.fx import FXDailyReferenceRate
from app.models.imports import ImportTransactionDraft
from app.models.transaction import Transaction
from app.services.currency_aliases import normalize_currency_code
from app.services.fx_pairs import required_fx_quotes
from app.services.fx_refresh_lock import acquire_fx_refresh_lock
from app.services.reporting_currency import ALLOWED_REPORTING_CURRENCIES

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

FX_COVERAGE_LOOKBACK_DAYS: int = 10
ECB_PUBLICATION_WEEKDAY_COUNT: int = 5
type NowProvider = Callable[[], datetime]


def utc_now() -> datetime:
    """Return the current UTC datetime."""
    return datetime.now(UTC)


@dataclass(frozen=True)
class FXConversionCoverageRequest:
    """Represent f x conversion coverage request."""

    raw_currency: str
    reporting_currency: str
    transaction_date: date


class FXConversionCoverageStatus(StrEnum):
    """Represent f x conversion coverage status."""

    ALREADY_COVERED = "already_covered"
    FETCHED_AND_COVERED = "fetched_and_covered"
    UNSUPPORTED = "unsupported"
    MISSING = "missing"
    FETCH_FAILED = "fetch_failed"
    LOCK_TIMEOUT = "lock_timeout"


@dataclass(frozen=True)
class FXConversionCoverageResult:
    """Represent f x conversion coverage result."""

    status: FXConversionCoverageStatus
    required_quotes: tuple[str, ...] = ()
    missing_dates: tuple[date, ...] = ()
    start_date: date | None = None
    end_date: date | None = None
    error: str | None = None


@dataclass(frozen=True)
class _FXConversionCoverageInput:
    transaction_date: date
    required_quotes: tuple[str, ...]


@dataclass(frozen=True)
class _FXConversionCoverageBatch:
    inputs: tuple[_FXConversionCoverageInput, ...]
    has_unsupported: bool


@dataclass(frozen=True)
class FXRefreshResult:
    """Represent f x refresh result."""

    start_date: date
    end_date: date
    inserted_or_updated_rows: int
    missing_publication_days: list[tuple[date, str]]
    missing_working_days: list[tuple[date, str]]


class ECBExchangeRateService:
    """Represent e c b exchange rate service."""

    SOURCE_NAME = "ECB_EXR"
    BASE_CURRENCY = "EUR"
    SUPPORTED_QUOTES = ("USD", "BRL")
    SUPPORTED_CURRENCIES = frozenset(ALLOWED_REPORTING_CURRENCIES)
    ECB_XML_NAMESPACE: ClassVar[dict[str, str]] = {
        "ecb": "http://www.ecb.int/vocabulary/2002-08-01/eurofxref"
    }

    def __init__(
        self,
        db: Session,
        *,
        http_client: httpx.Client | None = None,
        timeout: float = 30.0,
        now_provider: NowProvider | None = None,
    ) -> None:
        """Initialize the instance."""
        self.db = db
        self._http_client = http_client
        self._timeout = timeout
        self._now_provider = now_provider or utc_now

    def has_seed_data(self) -> bool:
        """Handle has seed data."""
        existing_id = self.db.execute(
            select(FXDailyReferenceRate.id)
            .where(FXDailyReferenceRate.source_name == self.SOURCE_NAME)
            .limit(1)
        ).scalar_one_or_none()
        return existing_id is not None

    def check_conversion_coverage(
        self,
        requests: list[FXConversionCoverageRequest],
    ) -> FXConversionCoverageResult:
        """Handle check conversion coverage."""
        coverage_batch = self._coverage_inputs(requests)
        coverage_inputs = coverage_batch.inputs
        has_supported_non_identity_request = any(
            coverage_input.required_quotes for coverage_input in coverage_inputs
        )
        if coverage_batch.has_unsupported and not has_supported_non_identity_request:
            return FXConversionCoverageResult(
                status=FXConversionCoverageStatus.UNSUPPORTED
            )

        required_quotes = tuple(
            sorted(
                {
                    quote
                    for coverage_input in coverage_inputs
                    for quote in coverage_input.required_quotes
                }
            )
        )
        missing_dates = tuple(
            sorted(
                {
                    coverage_input.transaction_date
                    for coverage_input in coverage_inputs
                    if coverage_input.required_quotes
                    and self._latest_covered_rate_date(
                        transaction_date=coverage_input.transaction_date,
                        required_quotes=coverage_input.required_quotes,
                    )
                    is None
                }
            )
        )

        if missing_dates:
            return FXConversionCoverageResult(
                status=FXConversionCoverageStatus.MISSING,
                required_quotes=required_quotes,
                missing_dates=missing_dates,
            )

        return FXConversionCoverageResult(
            status=FXConversionCoverageStatus.ALREADY_COVERED,
            required_quotes=required_quotes,
        )

    def earliest_covered_date(self) -> date | None:
        """Handle earliest covered date."""
        covered_dates = (
            select(FXDailyReferenceRate.rate_date.label("rate_date"))
            .where(
                FXDailyReferenceRate.source_name == self.SOURCE_NAME,
                FXDailyReferenceRate.base_currency == self.BASE_CURRENCY,
                FXDailyReferenceRate.quoted_currency.in_(self.SUPPORTED_QUOTES),
            )
            .group_by(FXDailyReferenceRate.rate_date)
            .having(
                func.count(func.distinct(FXDailyReferenceRate.quoted_currency))
                == len(self.SUPPORTED_QUOTES)
            )
            .subquery()
        )
        return self.db.execute(
            select(func.min(covered_dates.c.rate_date))
        ).scalar_one_or_none()

    def _coverage_inputs(
        self,
        requests: list[FXConversionCoverageRequest],
    ) -> _FXConversionCoverageBatch:
        coverage_inputs: list[_FXConversionCoverageInput] = []
        has_unsupported = False
        for request in requests:
            normalized_raw_currency = normalize_currency_code(request.raw_currency)
            normalized_reporting_currency = normalize_currency_code(
                request.reporting_currency
            )

            if (
                normalized_raw_currency not in self.SUPPORTED_CURRENCIES
                or normalized_reporting_currency not in self.SUPPORTED_CURRENCIES
            ):
                has_unsupported = True
                continue

            coverage_inputs.append(
                _FXConversionCoverageInput(
                    transaction_date=request.transaction_date,
                    required_quotes=required_fx_quotes(
                        raw_currency=normalized_raw_currency,
                        reporting_currency=normalized_reporting_currency,
                        base_currency=self.BASE_CURRENCY,
                    ),
                )
            )

        return _FXConversionCoverageBatch(
            inputs=tuple(coverage_inputs),
            has_unsupported=has_unsupported,
        )

    def _latest_covered_rate_date(
        self,
        *,
        transaction_date: date,
        required_quotes: tuple[str, ...],
    ) -> date | None:
        if not required_quotes:
            return transaction_date

        return self.db.execute(
            select(FXDailyReferenceRate.rate_date)
            .where(
                FXDailyReferenceRate.source_name == self.SOURCE_NAME,
                FXDailyReferenceRate.base_currency == self.BASE_CURRENCY,
                FXDailyReferenceRate.rate_date <= transaction_date,
                FXDailyReferenceRate.quoted_currency.in_(required_quotes),
            )
            .group_by(FXDailyReferenceRate.rate_date)
            .having(
                func.count(func.distinct(FXDailyReferenceRate.quoted_currency))
                == len(required_quotes)
            )
            .order_by(FXDailyReferenceRate.rate_date.desc())
            .limit(1)
        ).scalar_one_or_none()

    def latest_publication_day_on_or_before(self, day: date) -> date:
        """Handle latest publication day on or before."""
        while not self._is_ecb_publication_day(day):
            day -= timedelta(days=1)
        return day

    def has_historical_seed_coverage(self, *, today: date | None = None) -> bool:
        """Handle has historical seed coverage."""
        end_date = today or self._today()
        required_start_date = self._historical_seed_start_date(end_date)
        expected_row_count = self._expected_observation_count(
            required_start_date, end_date
        )
        actual_row_count = self.db.execute(
            select(func.count(FXDailyReferenceRate.id)).where(
                FXDailyReferenceRate.source_name == self.SOURCE_NAME,
                FXDailyReferenceRate.base_currency == self.BASE_CURRENCY,
                FXDailyReferenceRate.quoted_currency.in_(self.SUPPORTED_QUOTES),
                FXDailyReferenceRate.rate_date >= required_start_date,
                FXDailyReferenceRate.rate_date <= end_date,
            )
        ).scalar_one()

        return actual_row_count == expected_row_count

    def seed_historical_rates(self, *, today: date | None = None) -> FXRefreshResult:
        """Handle seed historical rates."""
        end_date = today or self._today()
        start_date = self._historical_seed_start_date(end_date)
        return self.refresh_range(start_date, end_date)

    def catch_up_recent_days(
        self,
        *,
        today: date | None = None,
        window_days: int | None = None,
    ) -> FXRefreshResult:
        """Handle catch up recent days."""
        end_date = today or self._today()
        effective_window = window_days or settings.fx_startup_catchup_days
        start_date = end_date - timedelta(days=max(effective_window - 1, 0))
        return self.refresh_range(start_date, end_date)

    def ensure_conversion_coverage(
        self,
        requests: list[FXConversionCoverageRequest],
        *,
        lock_timeout_seconds: float = 0.0,
        lock_poll_seconds: float = 0.1,
    ) -> FXConversionCoverageResult:
        """Handle ensure conversion coverage."""
        coverage = self.check_conversion_coverage(requests)
        if coverage.status != FXConversionCoverageStatus.MISSING:
            return coverage

        start_date = min(coverage.missing_dates) - timedelta(
            days=FX_COVERAGE_LOOKBACK_DAYS
        )
        end_date = max(coverage.missing_dates)

        with acquire_fx_refresh_lock(
            settings.database_path,
            timeout_seconds=lock_timeout_seconds,
            poll_seconds=lock_poll_seconds,
        ) as acquired:
            if not acquired:
                return FXConversionCoverageResult(
                    status=FXConversionCoverageStatus.LOCK_TIMEOUT,
                    required_quotes=coverage.required_quotes,
                    missing_dates=coverage.missing_dates,
                    start_date=start_date,
                    end_date=end_date,
                )

            coverage_after_lock = self.check_conversion_coverage(requests)
            if coverage_after_lock.status != FXConversionCoverageStatus.MISSING:
                return coverage_after_lock

            try:
                self.refresh_range(start_date, end_date)
            except (
                ElementTree.ParseError,
                httpx.HTTPError,
                RuntimeError,
                ValueError,
            ) as exc:
                self.db.rollback()
                return FXConversionCoverageResult(
                    status=FXConversionCoverageStatus.FETCH_FAILED,
                    required_quotes=coverage_after_lock.required_quotes,
                    missing_dates=coverage_after_lock.missing_dates,
                    start_date=start_date,
                    end_date=end_date,
                    error=str(exc),
                )

            coverage_after_refresh = self.check_conversion_coverage(requests)
            if coverage_after_refresh.status == FXConversionCoverageStatus.MISSING:
                return FXConversionCoverageResult(
                    status=FXConversionCoverageStatus.MISSING,
                    required_quotes=coverage_after_refresh.required_quotes,
                    missing_dates=coverage_after_refresh.missing_dates,
                    start_date=start_date,
                    end_date=end_date,
                )

            return FXConversionCoverageResult(
                status=FXConversionCoverageStatus.FETCHED_AND_COVERED,
                required_quotes=coverage_after_refresh.required_quotes,
                missing_dates=coverage_after_refresh.missing_dates,
                start_date=start_date,
                end_date=end_date,
            )

    def refresh_range(self, start_date: date, end_date: date) -> FXRefreshResult:
        """Handle refresh range."""
        if start_date > end_date:
            msg = "start_date must be on or before end_date"
            raise ValueError(msg)

        fetched_at = self._now_provider()
        series = self._normalize_series(
            self._fetch_series(start_date, end_date),
            start_date=start_date,
            end_date=end_date,
        )
        inserted_or_updated_rows = self._upsert_series(series, fetched_at=fetched_at)
        missing_publication_days, missing_working_days = self._classify_missing_quotes(
            start_date, end_date, series
        )

        return FXRefreshResult(
            start_date=start_date,
            end_date=end_date,
            inserted_or_updated_rows=inserted_or_updated_rows,
            missing_publication_days=missing_publication_days,
            missing_working_days=missing_working_days,
        )

    def _historical_seed_start_date(self, end_date: date) -> date:
        earliest_transaction_date = self.db.execute(
            select(func.min(Transaction.transaction_date))
        ).scalar_one_or_none()
        earliest_import_draft_date = self.db.execute(
            select(func.min(ImportTransactionDraft.transaction_date))
        ).scalar_one_or_none()
        candidate_dates = [
            candidate_date
            for candidate_date in (
                earliest_transaction_date,
                earliest_import_draft_date,
            )
            if candidate_date is not None
        ]
        if candidate_dates:
            return min(candidate_dates)

        try:
            return end_date.replace(year=end_date.year - settings.fx_seed_years)
        except ValueError:
            return end_date.replace(
                month=2, day=28, year=end_date.year - settings.fx_seed_years
            )

    def _fetch_series(
        self, start_date: date, end_date: date
    ) -> dict[date, dict[str, Decimal]]:
        response = self._get_xml_response(
            self._series_url_for_range(start_date, end_date)
        )
        return self._parse_series(
            response.text, start_date=start_date, end_date=end_date
        )

    def _series_url_for_range(self, start_date: date, end_date: date) -> str:
        recent_cutoff = self._today() - timedelta(days=89)
        if start_date >= recent_cutoff and end_date >= recent_cutoff:
            return settings.ecb_history_90d_url
        return settings.ecb_history_url

    def _get_xml_response(self, url: str) -> httpx.Response:
        if self._http_client is None:
            with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
                response = client.get(url, timeout=self._timeout, follow_redirects=True)
        else:
            response = self._http_client.get(
                url, timeout=self._timeout, follow_redirects=True
            )

        response.raise_for_status()
        return response

    def _parse_series(
        self,
        xml_text: str,
        *,
        start_date: date,
        end_date: date,
    ) -> dict[date, dict[str, Decimal]]:
        root = ElementTree.fromstring(xml_text)
        series: dict[date, dict[str, Decimal]] = {}

        for day_cube in root.findall(".//ecb:Cube[@time]", self.ECB_XML_NAMESPACE):
            rate_date = date.fromisoformat(day_cube.attrib["time"])
            if rate_date < start_date or rate_date > end_date:
                continue

            quotes: dict[str, Decimal] = {}
            for quote_cube in day_cube.findall(
                "ecb:Cube[@currency]", self.ECB_XML_NAMESPACE
            ):
                currency = quote_cube.attrib["currency"]
                if currency not in self.SUPPORTED_QUOTES:
                    continue
                quotes[currency] = Decimal(quote_cube.attrib["rate"])

            if quotes:
                series[rate_date] = quotes

        return series

    def _normalize_series(
        self,
        series: dict[date, dict[str, Decimal]],
        *,
        start_date: date,
        end_date: date,
    ) -> dict[date, dict[str, Decimal]]:
        normalized: dict[date, dict[str, Decimal]] = {}
        for rate_date, quotes in series.items():
            if rate_date < start_date or rate_date > end_date:
                continue

            filtered_quotes = {
                quoted_currency: Decimal(str(units_per_base))
                for quoted_currency, units_per_base in quotes.items()
                if quoted_currency in self.SUPPORTED_QUOTES
            }
            if filtered_quotes:
                normalized[rate_date] = filtered_quotes

        return normalized

    def _upsert_series(
        self, series: dict[date, dict[str, Decimal]], *, fetched_at: datetime
    ) -> int:
        if not series:
            return 0

        existing_rows = self.db.execute(
            select(FXDailyReferenceRate).where(
                FXDailyReferenceRate.source_name == self.SOURCE_NAME,
                FXDailyReferenceRate.base_currency == self.BASE_CURRENCY,
                FXDailyReferenceRate.rate_date.in_(series.keys()),
                FXDailyReferenceRate.quoted_currency.in_(self.SUPPORTED_QUOTES),
            )
        ).scalars()
        existing_by_key = {
            (row.rate_date, row.quoted_currency): row for row in existing_rows
        }

        inserted_or_updated = 0
        for rate_date, quotes in sorted(series.items()):
            for quoted_currency in self.SUPPORTED_QUOTES:
                units_per_base = quotes.get(quoted_currency)
                if units_per_base is None:
                    continue

                row = existing_by_key.get((rate_date, quoted_currency))
                if row is None:
                    row = FXDailyReferenceRate(
                        rate_date=rate_date,
                        base_currency=self.BASE_CURRENCY,
                        quoted_currency=quoted_currency,
                        source_name=self.SOURCE_NAME,
                    )
                    self.db.add(row)
                    existing_by_key[(rate_date, quoted_currency)] = row
                    row.units_per_base = units_per_base
                    row.fetched_at = fetched_at
                    row.updated_at = fetched_at
                    inserted_or_updated += 1
                    continue

                if row.units_per_base == units_per_base:
                    continue

                row.units_per_base = units_per_base
                row.fetched_at = fetched_at
                row.updated_at = fetched_at
                inserted_or_updated += 1

        self.db.commit()
        return inserted_or_updated

    def _classify_missing_quotes(
        self,
        start_date: date,
        end_date: date,
        series: dict[date, dict[str, Decimal]],
    ) -> tuple[list[tuple[date, str]], list[tuple[date, str]]]:
        missing_publication_days: list[tuple[date, str]] = []
        missing_working_days: list[tuple[date, str]] = []
        current_date = start_date
        while current_date <= end_date:
            available_quotes = series.get(current_date, {})
            for quoted_currency in self.SUPPORTED_QUOTES:
                if quoted_currency in available_quotes:
                    continue

                if self._is_ecb_publication_day(current_date):
                    missing_working_days.append((current_date, quoted_currency))
                else:
                    missing_publication_days.append((current_date, quoted_currency))
            current_date += timedelta(days=1)

        return missing_publication_days, missing_working_days

    def _expected_observation_count(self, start_date: date, end_date: date) -> int:
        publication_day_count = 0
        current_date = start_date
        while current_date <= end_date:
            if self._is_ecb_publication_day(current_date):
                publication_day_count += 1
            current_date += timedelta(days=1)

        return publication_day_count * len(self.SUPPORTED_QUOTES)

    def _is_ecb_publication_day(self, day: date) -> bool:
        return (
            day.weekday() < ECB_PUBLICATION_WEEKDAY_COUNT
            and day not in self._target_closing_days(day.year)
        )

    def _target_closing_days(self, year: int) -> set[date]:
        easter_sunday = self._easter_sunday(year)
        return {
            date(year, 1, 1),
            easter_sunday - timedelta(days=2),
            easter_sunday + timedelta(days=1),
            date(year, 5, 1),
            date(year, 12, 25),
            date(year, 12, 26),
        }

    def _easter_sunday(self, year: int) -> date:
        a = year % 19
        b = year // 100
        c = year % 100
        d = b // 4
        e = b % 4
        f = (b + 8) // 25
        g = (b - f + 1) // 3
        h = (19 * a + b - d - g + 15) % 30
        i = c // 4
        k = c % 4
        adjustment = (32 + 2 * e + 2 * i - h - k) % 7
        m = (a + 11 * h + 22 * adjustment) // 451
        month = (h + adjustment - 7 * m + 114) // 31
        day = ((h + adjustment - 7 * m + 114) % 31) + 1
        return date(year, month, day)

    def _today(self) -> date:
        return self._now_provider().date()
