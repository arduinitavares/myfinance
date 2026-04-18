from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Iterable

from dateutil.relativedelta import relativedelta
from sqlalchemy import extract, func
from sqlalchemy.orm import Session

from ..models.statistics import StatisticsPeriod
from ..models.transaction import Transaction, TransactionType, TransferCategory
from ..schemas.transaction import TimePeriod
from ..services.currency_conversion import CurrencyConversionService, DisplayMoney
from ..services.statistics_service import StatisticsService


@dataclass
class ConversionSummary:
    converted_transaction_count: int = 0
    unavailable_transaction_count: int = 0
    unavailable_currencies: set[str] = field(default_factory=set)

    def record(self, display_money: DisplayMoney, raw_currency: str) -> None:
        if display_money.is_available and display_money.display_amount is not None:
            self.converted_transaction_count += 1
            return

        self.unavailable_transaction_count += 1
        normalized_currency = raw_currency.strip().upper()
        if normalized_currency:
            self.unavailable_currencies.add(normalized_currency)

    def as_payload(self) -> dict[str, Any]:
        return {
            "converted_transaction_count": self.converted_transaction_count,
            "unavailable_transaction_count": self.unavailable_transaction_count,
            "unavailable_currencies": sorted(self.unavailable_currencies),
        }


class ReportingCurrencyAnalyticsService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.conversion_service = CurrencyConversionService(db)

    @staticmethod
    def _month_end(value: date) -> date:
        return value.replace(day=calendar.monthrange(value.year, value.month)[1])

    @classmethod
    def _previous_month_end(cls, value: date) -> date:
        return cls._month_end(value - relativedelta(months=1))

    @staticmethod
    def _parse_iso_date(value: str | None) -> date | None:
        if value is None:
            return None
        return datetime.strptime(value, "%Y-%m-%d").date()

    @classmethod
    def resolve_reporting_window(
        cls,
        db: Session,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        time_period: TimePeriod | None = None,
    ) -> tuple[date, date]:
        latest_transaction_date = db.query(func.max(Transaction.transaction_date)).scalar()
        earliest_transaction_date = db.query(func.min(Transaction.transaction_date)).scalar()

        reference_date = latest_transaction_date or date.today()
        reference_date = cls._month_end(reference_date)
        end = reference_date

        if time_period and not (start_date or end_date):
            if time_period == TimePeriod.THREE_MONTHS:
                start = cls._month_end(reference_date - relativedelta(months=3)) + timedelta(days=1)
            elif time_period == TimePeriod.SIX_MONTHS:
                start = cls._month_end(reference_date - relativedelta(months=6)) + timedelta(days=1)
            elif time_period == TimePeriod.YEAR_TO_DATE:
                start = date(reference_date.year, 1, 1)
            elif time_period == TimePeriod.ONE_YEAR:
                start = cls._month_end(reference_date - relativedelta(years=1)) + timedelta(days=1)
            elif time_period == TimePeriod.TWO_YEARS:
                start = cls._month_end(reference_date - relativedelta(years=2)) + timedelta(days=1)
            else:
                start = earliest_transaction_date or reference_date
        else:
            start = cls._parse_iso_date(start_date) or earliest_transaction_date or reference_date
            parsed_end = cls._parse_iso_date(end_date)
            if parsed_end is not None:
                end = parsed_end

        if start > end:
            raise ValueError("Start date must be before end date")

        return start, end

    def _display_money(self, transaction: Transaction, reporting_currency: str) -> DisplayMoney:
        return self.conversion_service.convert(
            raw_amount=transaction.amount,
            raw_currency=transaction.currency,
            reporting_currency=reporting_currency,
            transaction_date=transaction.transaction_date,
        )

    def _conversion_summary_for(
        self,
        transactions: Iterable[Transaction],
        *,
        reporting_currency: str,
    ) -> ConversionSummary:
        summary = ConversionSummary()
        for transaction in transactions:
            summary.record(self._display_money(transaction, reporting_currency), transaction.currency)
        return summary

    def _summarize_financial_transactions(
        self,
        transactions: Iterable[Transaction],
        *,
        reporting_currency: str,
    ) -> tuple[dict[str, float | int], ConversionSummary]:
        income_total = Decimal("0")
        expense_total = Decimal("0")
        income_count = 0
        expense_count = 0
        converted_income_count = 0
        converted_expense_count = 0
        summary = ConversionSummary()

        for transaction in transactions:
            if transaction.transaction_type not in (TransactionType.INCOME, TransactionType.EXPENSE):
                continue

            if transaction.transaction_type == TransactionType.INCOME:
                income_count += 1
            else:
                expense_count += 1

            display_money = self._display_money(transaction, reporting_currency)
            summary.record(display_money, transaction.currency)
            if not display_money.is_available or display_money.display_amount is None:
                continue

            display_amount = StatisticsService._to_decimal(display_money.display_amount)
            if transaction.transaction_type == TransactionType.INCOME:
                income_total += display_amount
                converted_income_count += 1
            else:
                expense_total += abs(display_amount)
                converted_expense_count += 1

        period_net_savings = income_total - expense_total
        savings_rate = float(period_net_savings / income_total * 100) if income_total > 0 else 0.0

        return (
            {
                "period_income": StatisticsService._quantized_float(income_total),
                "period_expenses": StatisticsService._quantized_float(expense_total),
                "period_net_savings": StatisticsService._quantized_float(period_net_savings),
                "savings_rate": savings_rate,
                "income_count": income_count,
                "expense_count": expense_count,
                "average_income": (
                    StatisticsService._quantized_float(income_total / converted_income_count)
                    if converted_income_count > 0
                    else 0.0
                ),
                "average_expense": (
                    StatisticsService._quantized_float(expense_total / converted_expense_count)
                    if converted_expense_count > 0
                    else 0.0
                ),
            },
            summary,
        )

    def _financial_snapshot(
        self,
        *,
        period: StatisticsPeriod,
        target_date: date | None,
        reporting_currency: str,
    ) -> tuple[dict[str, float | int], ConversionSummary]:
        period_query, cumulative_query, yearly_query = StatisticsService._financial_stat_queries(
            self.db,
            period,
            target_date,
        )

        period_stats, period_summary = self._summarize_financial_transactions(
            period_query.all(),
            reporting_currency=reporting_currency,
        )
        cumulative_stats, _ = self._summarize_financial_transactions(
            cumulative_query.all(),
            reporting_currency=reporting_currency,
        )
        yearly_stats, _ = self._summarize_financial_transactions(
            yearly_query.all(),
            reporting_currency=reporting_currency,
        )

        return (
            {
                **period_stats,
                "total_income": cumulative_stats["period_income"],
                "total_expenses": cumulative_stats["period_expenses"],
                "total_net_savings": cumulative_stats["period_net_savings"],
                "yearly_income": yearly_stats["period_income"],
                "yearly_expenses": yearly_stats["period_expenses"],
            },
            period_summary,
        )

    def _build_overview_item(
        self,
        *,
        period: StatisticsPeriod,
        anchor_date: date | None,
        reporting_currency: str,
    ) -> dict[str, Any]:
        stats, conversion_summary = self._financial_snapshot(
            period=period,
            target_date=anchor_date,
            reporting_currency=reporting_currency,
        )
        return {
            "period": period.value,
            "date": anchor_date.isoformat() if anchor_date else None,
            "reporting_currency": reporting_currency,
            "conversion_summary": conversion_summary.as_payload(),
            **stats,
        }

    def build_overview(self, *, reporting_currency: str) -> dict[str, Any]:
        latest_transaction = self.db.query(Transaction).order_by(Transaction.transaction_date.desc()).first()

        if latest_transaction is None:
            current_month = self._month_end(date.today())
            last_month = self._previous_month_end(current_month)
            empty_stats = StatisticsService._zero_financial_stats()
            empty_summary = ConversionSummary().as_payload()
            return {
                "current_month": {
                    "period": StatisticsPeriod.MONTHLY.value,
                    "date": current_month.isoformat(),
                    "reporting_currency": reporting_currency,
                    "conversion_summary": empty_summary,
                    **empty_stats,
                },
                "last_month": {
                    "period": StatisticsPeriod.MONTHLY.value,
                    "date": last_month.isoformat(),
                    "reporting_currency": reporting_currency,
                    "conversion_summary": empty_summary,
                    **empty_stats,
                },
                "previous_year_last_month": None,
                "all_time": {
                    "period": StatisticsPeriod.ALL_TIME.value,
                    "date": None,
                    "reporting_currency": reporting_currency,
                    "conversion_summary": empty_summary,
                    **empty_stats,
                },
            }

        current_month = self._month_end(latest_transaction.transaction_date)
        last_month = self._previous_month_end(current_month)
        previous_year_last_month = date(current_month.year - 1, 12, 31)

        previous_year_last_month_has_activity = self.db.query(Transaction.id).filter(
            extract("year", Transaction.transaction_date) == previous_year_last_month.year,
            extract("month", Transaction.transaction_date) == previous_year_last_month.month,
        ).first()

        payload = {
            "current_month": self._build_overview_item(
                period=StatisticsPeriod.MONTHLY,
                anchor_date=current_month,
                reporting_currency=reporting_currency,
            ),
            "last_month": self._build_overview_item(
                period=StatisticsPeriod.MONTHLY,
                anchor_date=last_month,
                reporting_currency=reporting_currency,
            ),
            "previous_year_last_month": None,
            "all_time": self._build_overview_item(
                period=StatisticsPeriod.ALL_TIME,
                anchor_date=None,
                reporting_currency=reporting_currency,
            ),
        }

        if previous_year_last_month_has_activity:
            payload["previous_year_last_month"] = self._build_overview_item(
                period=StatisticsPeriod.MONTHLY,
                anchor_date=previous_year_last_month,
                reporting_currency=reporting_currency,
            )

        return payload

    def build_transfer_summary(
        self,
        *,
        start: date,
        end: date,
        reporting_currency: str,
    ) -> dict[str, Any]:
        transfers = self.db.query(Transaction).filter(
            Transaction.transaction_type == TransactionType.TRANSFER,
            Transaction.transaction_date >= start,
            Transaction.transaction_date <= end,
        ).all()

        summary_by_category: dict[str, dict[str, Any]] = {}
        conversion_summary = ConversionSummary()

        for transaction in transfers:
            category_name = (
                transaction.transfer_category.value
                if transaction.transfer_category is not None
                else TransferCategory.INTERNAL_TRANSFER.value
            )
            if category_name not in summary_by_category:
                summary_by_category[category_name] = {
                    "subtype": category_name,
                    "transaction_count": 0,
                    "total_outgoing": Decimal("0"),
                    "total_incoming": Decimal("0"),
                }

            summary_by_category[category_name]["transaction_count"] += 1

            display_money = self._display_money(transaction, reporting_currency)
            conversion_summary.record(display_money, transaction.currency)
            if not display_money.is_available or display_money.display_amount is None:
                continue

            display_amount = StatisticsService._to_decimal(display_money.display_amount)
            if display_amount < 0:
                summary_by_category[category_name]["total_outgoing"] += abs(display_amount)
            else:
                summary_by_category[category_name]["total_incoming"] += display_amount

        items = [
            {
                "subtype": item["subtype"],
                "transaction_count": item["transaction_count"],
                "total_outgoing": StatisticsService._quantized_float(item["total_outgoing"]),
                "total_incoming": StatisticsService._quantized_float(item["total_incoming"]),
            }
            for item in sorted(summary_by_category.values(), key=lambda entry: entry["subtype"])
        ]

        return {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "reporting_currency": reporting_currency,
            "conversion_summary": conversion_summary.as_payload(),
            "items": items,
        }

    @classmethod
    def _month_ends_between(cls, start: date, end: date) -> list[date]:
        month_ends: list[date] = []
        current = cls._month_end(start)
        while current <= end:
            month_ends.append(current)
            current = cls._month_end(current + relativedelta(months=1))
        return month_ends

    def build_financial_timeseries(
        self,
        *,
        start: date,
        end: date,
        reporting_currency: str,
    ) -> dict[str, Any]:
        financial_transactions = self.db.query(Transaction).filter(
            Transaction.transaction_type.in_([TransactionType.INCOME, TransactionType.EXPENSE]),
            Transaction.transaction_date >= start,
            Transaction.transaction_date <= end,
        ).all()

        items = []
        if financial_transactions:
            for month_end in self._month_ends_between(start, end):
                stats, _ = self._financial_snapshot(
                    period=StatisticsPeriod.MONTHLY,
                    target_date=month_end,
                    reporting_currency=reporting_currency,
                )
                items.append(
                    {
                        "period": StatisticsPeriod.MONTHLY.value,
                        "date": month_end.isoformat(),
                        **stats,
                    }
                )

        return {
            "reporting_currency": reporting_currency,
            "conversion_summary": self._conversion_summary_for(
                financial_transactions,
                reporting_currency=reporting_currency,
            ).as_payload(),
            "items": items,
        }
