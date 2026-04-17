from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
import xml.etree.ElementTree as ET

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.fx import FXDailyReferenceRate
from app.models.transaction import Transaction

@dataclass(frozen=True)
class FXRefreshResult:
    start_date: date
    end_date: date
    inserted_or_updated_rows: int
    missing_publication_days: list[date]
    missing_working_days: list[date]


class ECBExchangeRateService:
    SOURCE_NAME = "ECB_EXR"
    BASE_CURRENCY = "EUR"
    SUPPORTED_QUOTES = ("USD", "BRL")
    ECB_XML_NAMESPACE = {"ecb": "http://www.ecb.int/vocabulary/2002-08-01/eurofxref"}

    def __init__(
        self,
        db: Session,
        *,
        http_client: httpx.Client | None = None,
        now_provider=None,
    ) -> None:
        self.db = db
        self._http_client = http_client
        self._now_provider = now_provider or datetime.utcnow

    def has_seed_data(self) -> bool:
        existing_id = self.db.execute(
            select(FXDailyReferenceRate.id)
            .where(FXDailyReferenceRate.source_name == self.SOURCE_NAME)
            .limit(1)
        ).scalar_one_or_none()
        return existing_id is not None

    def seed_historical_rates(self, *, today: date | None = None) -> FXRefreshResult:
        end_date = today or self._today()
        start_date = self._historical_seed_start_date(end_date)
        return self.refresh_range(start_date, end_date)

    def catch_up_recent_days(
        self,
        *,
        today: date | None = None,
        window_days: int | None = None,
    ) -> FXRefreshResult:
        end_date = today or self._today()
        effective_window = window_days or settings.fx_startup_catchup_days
        start_date = end_date - timedelta(days=max(effective_window - 1, 0))
        return self.refresh_range(start_date, end_date)

    def refresh_range(self, start_date: date, end_date: date) -> FXRefreshResult:
        if start_date > end_date:
            raise ValueError("start_date must be on or before end_date")

        fetched_at = self._now_provider()
        series = self._normalize_series(
            self._fetch_series(start_date, end_date),
            start_date=start_date,
            end_date=end_date,
        )
        inserted_or_updated_rows = self._upsert_series(series, fetched_at=fetched_at)
        available_dates = set(series.keys())
        missing_publication_days, missing_working_days = self._classify_missing_dates(
            start_date, end_date, available_dates
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
        if earliest_transaction_date is not None:
            return earliest_transaction_date

        try:
            return end_date.replace(year=end_date.year - settings.fx_seed_years)
        except ValueError:
            return end_date.replace(month=2, day=28, year=end_date.year - settings.fx_seed_years)

    def _fetch_series(self, start_date: date, end_date: date) -> dict[date, dict[str, Decimal]]:
        response = self._get_xml_response(self._series_url_for_range(start_date, end_date))
        return self._parse_series(response.text, start_date=start_date, end_date=end_date)

    def _series_url_for_range(self, start_date: date, end_date: date) -> str:
        recent_cutoff = self._today() - timedelta(days=89)
        if start_date >= recent_cutoff and end_date >= recent_cutoff:
            return settings.ecb_history_90d_url
        return settings.ecb_history_url

    def _get_xml_response(self, url: str) -> httpx.Response:
        if self._http_client is None:
            with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                response = client.get(url)
        else:
            response = self._http_client.get(url, timeout=30.0, follow_redirects=True)

        response.raise_for_status()
        return response

    def _parse_series(
        self,
        xml_text: str,
        *,
        start_date: date,
        end_date: date,
    ) -> dict[date, dict[str, Decimal]]:
        root = ET.fromstring(xml_text)
        series: dict[date, dict[str, Decimal]] = {}

        for day_cube in root.findall(".//ecb:Cube[@time]", self.ECB_XML_NAMESPACE):
            rate_date = date.fromisoformat(day_cube.attrib["time"])
            if rate_date < start_date or rate_date > end_date:
                continue

            quotes: dict[str, Decimal] = {}
            for quote_cube in day_cube.findall("ecb:Cube[@currency]", self.ECB_XML_NAMESPACE):
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

    def _upsert_series(self, series: dict[date, dict[str, Decimal]], *, fetched_at: datetime) -> int:
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
            (row.rate_date, row.quoted_currency): row
            for row in existing_rows
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

        self.db.commit()
        return inserted_or_updated

    def _classify_missing_dates(
        self,
        start_date: date,
        end_date: date,
        available_dates: set[date],
    ) -> tuple[list[date], list[date]]:
        missing_publication_days: list[date] = []
        missing_working_days: list[date] = []
        current_date = start_date
        while current_date <= end_date:
            if current_date not in available_dates:
                if self._is_ecb_publication_day(current_date):
                    missing_working_days.append(current_date)
                else:
                    missing_publication_days.append(current_date)
            current_date += timedelta(days=1)

        return missing_publication_days, missing_working_days

    def _is_ecb_publication_day(self, day: date) -> bool:
        return day.weekday() < 5 and day not in self._target_closing_days(day.year)

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
        l = (32 + 2 * e + 2 * i - h - k) % 7
        m = (a + 11 * h + 22 * l) // 451
        month = (h + l - 7 * m + 114) // 31
        day = ((h + l - 7 * m + 114) % 31) + 1
        return date(year, month, day)

    def _today(self) -> date:
        return self._now_provider().date()
