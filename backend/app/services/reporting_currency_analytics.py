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
from ..models.transaction import (
    ExpenseCategory,
    ExpenseType,
    IncomeCategory,
    Transaction,
    TransactionType,
    TransferCategory,
)
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
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError("Invalid date format. Use YYYY-MM-DD") from exc

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

    @staticmethod
    def _conversion_summary_for_prepared(
        transactions: Iterable[Any],
    ) -> ConversionSummary:
        summary = ConversionSummary()
        for transaction in transactions:
            if transaction.is_available and transaction.display_amount is not None:
                summary.converted_transaction_count += 1
                continue

            summary.unavailable_transaction_count += 1
            normalized_currency = transaction.raw_currency.strip().upper()
            if normalized_currency:
                summary.unavailable_currencies.add(normalized_currency)
        return summary

    @dataclass(frozen=True)
    class _PreparedFinancialTransaction:
        transaction_date: date
        month_end: date
        raw_currency: str
        transaction_type: TransactionType
        display_amount: Decimal | None
        is_available: bool

    @dataclass(frozen=True)
    class _PreparedCategoryTransaction:
        transaction_date: date
        month_end: date
        raw_currency: str
        transaction_type: TransactionType
        category_name: str
        expense_type: ExpenseType | None
        display_amount: Decimal | None
        is_available: bool

    def _prepare_financial_transactions(
        self,
        *,
        end: date,
        reporting_currency: str,
    ) -> tuple[list[_PreparedFinancialTransaction], ConversionSummary]:
        transactions = self.db.query(Transaction).filter(
            Transaction.transaction_type.in_([TransactionType.INCOME, TransactionType.EXPENSE]),
            Transaction.transaction_date <= end,
        ).order_by(Transaction.transaction_date.asc(), Transaction.id.asc()).all()

        prepared: list[ReportingCurrencyAnalyticsService._PreparedFinancialTransaction] = []
        conversion_summary = ConversionSummary()

        for transaction in transactions:
            display_money = self._display_money(transaction, reporting_currency)
            conversion_summary.record(display_money, transaction.currency)
            prepared.append(
                self._PreparedFinancialTransaction(
                    transaction_date=transaction.transaction_date,
                    month_end=self._month_end(transaction.transaction_date),
                    raw_currency=transaction.currency,
                    transaction_type=transaction.transaction_type,
                    display_amount=(
                        StatisticsService._to_decimal(display_money.display_amount)
                        if display_money.is_available and display_money.display_amount is not None
                        else None
                    ),
                    is_available=display_money.is_available and display_money.display_amount is not None,
                )
            )

        return prepared, conversion_summary

    def _prepare_category_transactions(
        self,
        *,
        end: date,
        reporting_currency: str,
    ) -> list[_PreparedCategoryTransaction]:
        transactions = self.db.query(Transaction).filter(
            Transaction.transaction_type.in_([TransactionType.INCOME, TransactionType.EXPENSE]),
            Transaction.transaction_date <= end,
        ).order_by(Transaction.transaction_date.asc(), Transaction.id.asc()).all()

        prepared: list[ReportingCurrencyAnalyticsService._PreparedCategoryTransaction] = []
        for transaction in transactions:
            display_money = self._display_money(transaction, reporting_currency)
            prepared.append(
                self._PreparedCategoryTransaction(
                    transaction_date=transaction.transaction_date,
                    month_end=self._month_end(transaction.transaction_date),
                    raw_currency=transaction.currency,
                    transaction_type=transaction.transaction_type,
                    category_name=self._category_name_for(transaction),
                    expense_type=(
                        transaction.expense_category.expense_type
                        if transaction.transaction_type == TransactionType.EXPENSE
                        and transaction.expense_category is not None
                        else None
                    ),
                    display_amount=(
                        StatisticsService._to_decimal(display_money.display_amount)
                        if display_money.is_available and display_money.display_amount is not None
                        else None
                    ),
                    is_available=display_money.is_available and display_money.display_amount is not None,
                )
            )

        return prepared

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

    def _transactions_for_period(
        self,
        *,
        period: StatisticsPeriod,
        target_date: date | None,
    ) -> tuple[list[Transaction], date | None]:
        query = self.db.query(Transaction).filter(
            Transaction.transaction_type.in_([TransactionType.INCOME, TransactionType.EXPENSE]),
        )

        normalized_target_date = target_date
        if period == StatisticsPeriod.MONTHLY:
            if target_date is None:
                raise ValueError("target_date is required for monthly statistics")
            normalized_target_date = self._month_end(target_date)
            query = query.filter(
                extract("year", Transaction.transaction_date) == normalized_target_date.year,
                extract("month", Transaction.transaction_date) == normalized_target_date.month,
            )
        elif period == StatisticsPeriod.YEARLY:
            if target_date is None:
                raise ValueError("target_date is required for yearly statistics")
            normalized_target_date = date(target_date.year, 12, 31)
            query = query.filter(
                extract("year", Transaction.transaction_date) == normalized_target_date.year,
            )

        return (
            query.order_by(Transaction.transaction_date.asc(), Transaction.id.asc()).all(),
            normalized_target_date,
        )

    @staticmethod
    def _transactions_for_month(
        transactions: Iterable[_PreparedCategoryTransaction],
        *,
        month_end: date,
    ) -> list[_PreparedCategoryTransaction]:
        return [transaction for transaction in transactions if transaction.month_end == month_end]

    @staticmethod
    def _category_name_for(transaction: Transaction) -> str:
        if transaction.transaction_type == TransactionType.EXPENSE:
            return (
                transaction.expense_category.value
                if transaction.expense_category is not None
                else ExpenseCategory.OTHERS.value
            )
        if transaction.transaction_type == TransactionType.INCOME:
            return (
                transaction.income_category.value
                if transaction.income_category is not None
                else IncomeCategory.OTHER.value
            )
        return "Uncategorized"

    @staticmethod
    def _empty_category_bucket(
        *,
        category_name: str,
        transaction_type: TransactionType,
        expense_type: ExpenseType | None,
        period: StatisticsPeriod,
        anchor_date: date | None,
    ) -> dict[str, Any]:
        return {
            "category": category_name,
            "category_name": category_name,
            "transaction_type": transaction_type.value,
            "expense_type": expense_type.value if expense_type is not None else None,
            "period": period.value,
            "date": anchor_date.isoformat() if anchor_date is not None else None,
            "period_amount": Decimal("0"),
            "period_transaction_count": 0,
            "period_percentage": Decimal("0"),
            "total_amount": Decimal("0"),
            "transaction_count": 0,
            "total_amount_cumulative": Decimal("0"),
            "total_transaction_count": 0,
            "average_transaction_amount": Decimal("0"),
            "yearly_amount": Decimal("0"),
            "yearly_transaction_count": 0,
            "_period_available_count": 0,
        }

    @staticmethod
    def _finalize_category_percentages(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        expense_total = sum(
            item["period_amount"]
            for item in items
            if item["transaction_type"] == TransactionType.EXPENSE.value
        )
        income_total = sum(
            item["period_amount"]
            for item in items
            if item["transaction_type"] == TransactionType.INCOME.value
        )

        for item in items:
            total = (
                expense_total
                if item["transaction_type"] == TransactionType.EXPENSE.value
                else income_total
            )
            item["period_percentage"] = (item["period_amount"] / total * 100) if total > 0 else Decimal("0")
            item["average_transaction_amount"] = (
                item["period_amount"] / item["_period_available_count"]
                if item["_period_available_count"] > 0
                else Decimal("0")
            )
            item["total_amount"] = item["period_amount"]
            item["transaction_count"] = item["period_transaction_count"]

            item["period_amount"] = StatisticsService._quantized_float(item["period_amount"])
            item["period_percentage"] = StatisticsService._quantized_float(item["period_percentage"])
            item["total_amount"] = StatisticsService._quantized_float(item["total_amount"])
            item["total_amount_cumulative"] = StatisticsService._quantized_float(item["total_amount_cumulative"])
            item["average_transaction_amount"] = StatisticsService._quantized_float(item["average_transaction_amount"])
            item["yearly_amount"] = StatisticsService._quantized_float(item["yearly_amount"])
            item.pop("_period_available_count", None)

        return sorted(
            items,
            key=lambda item: (
                item["transaction_type"],
                -item["period_amount"],
                item["category"],
            ),
        )

    def _aggregate_category_breakdown(
        self,
        *,
        period_transactions: Iterable[Transaction],
        cumulative_transactions: Iterable[Transaction],
        yearly_transactions: Iterable[Transaction],
        reporting_currency: str,
        period: StatisticsPeriod,
        anchor_date: date | None,
    ) -> list[dict[str, Any]]:
        items_by_key: dict[tuple[str, str, str | None], dict[str, Any]] = {}

        def ensure_bucket(transaction: Transaction) -> dict[str, Any]:
            category_name = self._category_name_for(transaction)
            expense_type = (
                transaction.expense_category.expense_type
                if transaction.transaction_type == TransactionType.EXPENSE
                and transaction.expense_category is not None
                else None
            )
            key = (
                category_name,
                transaction.transaction_type.value,
                expense_type.value if expense_type is not None else None,
            )
            if key not in items_by_key:
                items_by_key[key] = self._empty_category_bucket(
                    category_name=category_name,
                    transaction_type=transaction.transaction_type,
                    expense_type=expense_type,
                    period=period,
                    anchor_date=anchor_date,
                )
            return items_by_key[key]

        for transaction in period_transactions:
            if transaction.transaction_type not in (TransactionType.INCOME, TransactionType.EXPENSE):
                continue
            bucket = ensure_bucket(transaction)
            bucket["period_transaction_count"] += 1
            display_money = self._display_money(transaction, reporting_currency)
            if not display_money.is_available or display_money.display_amount is None:
                continue
            amount = StatisticsService._to_decimal(display_money.display_amount)
            bucket["period_amount"] += abs(amount) if transaction.transaction_type == TransactionType.EXPENSE else amount
            bucket["_period_available_count"] += 1

        for transaction in cumulative_transactions:
            if transaction.transaction_type not in (TransactionType.INCOME, TransactionType.EXPENSE):
                continue
            bucket = ensure_bucket(transaction)
            bucket["total_transaction_count"] += 1
            display_money = self._display_money(transaction, reporting_currency)
            if not display_money.is_available or display_money.display_amount is None:
                continue
            amount = StatisticsService._to_decimal(display_money.display_amount)
            bucket["total_amount_cumulative"] += (
                abs(amount) if transaction.transaction_type == TransactionType.EXPENSE else amount
            )

        for transaction in yearly_transactions:
            if transaction.transaction_type not in (TransactionType.INCOME, TransactionType.EXPENSE):
                continue
            bucket = ensure_bucket(transaction)
            bucket["yearly_transaction_count"] += 1
            display_money = self._display_money(transaction, reporting_currency)
            if not display_money.is_available or display_money.display_amount is None:
                continue
            amount = StatisticsService._to_decimal(display_money.display_amount)
            bucket["yearly_amount"] += abs(amount) if transaction.transaction_type == TransactionType.EXPENSE else amount

        return self._finalize_category_percentages(list(items_by_key.values()))

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
        target_month_ends = self._month_ends_between(start, end)
        if not target_month_ends:
            return {
                "reporting_currency": reporting_currency,
                "conversion_summary": ConversionSummary().as_payload(),
                "items": [],
            }

        prepared_transactions, _ = self._prepare_financial_transactions(
            end=end,
            reporting_currency=reporting_currency,
        )

        if not prepared_transactions or not any(
            start <= prepared.transaction_date <= end for prepared in prepared_transactions
        ):
            return {
                "reporting_currency": reporting_currency,
                "conversion_summary": ConversionSummary().as_payload(),
                "items": [],
            }

        last_target_month_end = target_month_ends[-1]
        contributing_transactions = [
            prepared for prepared in prepared_transactions if prepared.month_end <= last_target_month_end
        ]
        if not contributing_transactions:
            return {
                "reporting_currency": reporting_currency,
                "conversion_summary": ConversionSummary().as_payload(),
                "items": [],
            }

        transactions_by_month_end: dict[date, list[ReportingCurrencyAnalyticsService._PreparedFinancialTransaction]] = {}
        for prepared in contributing_transactions:
            transactions_by_month_end.setdefault(prepared.month_end, []).append(prepared)

        first_month_end = contributing_transactions[0].month_end
        processing_start = min(first_month_end, target_month_ends[0])
        target_month_end_set = set(target_month_ends)
        items = []

        cumulative_income = Decimal("0")
        cumulative_expenses = Decimal("0")
        yearly_totals: dict[int, dict[str, Decimal]] = {}

        for month_end in self._month_ends_between(processing_start, end):
            month_transactions = transactions_by_month_end.get(month_end, [])
            month_income = Decimal("0")
            month_expenses = Decimal("0")
            income_count = 0
            expense_count = 0
            converted_income_count = 0
            converted_expense_count = 0

            for prepared in month_transactions:
                year_totals = yearly_totals.setdefault(
                    prepared.transaction_date.year,
                    {"income": Decimal("0"), "expenses": Decimal("0")},
                )

                if prepared.transaction_type == TransactionType.INCOME:
                    income_count += 1
                    if prepared.is_available and prepared.display_amount is not None:
                        month_income += prepared.display_amount
                        cumulative_income += prepared.display_amount
                        year_totals["income"] += prepared.display_amount
                        converted_income_count += 1
                else:
                    expense_count += 1
                    if prepared.is_available and prepared.display_amount is not None:
                        display_expense = abs(prepared.display_amount)
                        month_expenses += display_expense
                        cumulative_expenses += display_expense
                        year_totals["expenses"] += display_expense
                        converted_expense_count += 1

            if month_end not in target_month_end_set:
                continue

            period_net_savings = month_income - month_expenses
            year_totals = yearly_totals.setdefault(
                month_end.year,
                {"income": Decimal("0"), "expenses": Decimal("0")},
            )
            items.append(
                {
                    "period": StatisticsPeriod.MONTHLY.value,
                    "date": month_end.isoformat(),
                    "period_income": StatisticsService._quantized_float(month_income),
                    "period_expenses": StatisticsService._quantized_float(month_expenses),
                    "period_net_savings": StatisticsService._quantized_float(period_net_savings),
                    "savings_rate": float(period_net_savings / month_income * 100) if month_income > 0 else 0.0,
                    "total_income": StatisticsService._quantized_float(cumulative_income),
                    "total_expenses": StatisticsService._quantized_float(cumulative_expenses),
                    "total_net_savings": StatisticsService._quantized_float(cumulative_income - cumulative_expenses),
                    "income_count": income_count,
                    "expense_count": expense_count,
                    "average_income": (
                        StatisticsService._quantized_float(month_income / converted_income_count)
                        if converted_income_count > 0
                        else 0.0
                    ),
                    "average_expense": (
                        StatisticsService._quantized_float(month_expenses / converted_expense_count)
                        if converted_expense_count > 0
                        else 0.0
                    ),
                    "yearly_income": StatisticsService._quantized_float(year_totals["income"]),
                    "yearly_expenses": StatisticsService._quantized_float(year_totals["expenses"]),
                }
            )

        return {
            "reporting_currency": reporting_currency,
            "conversion_summary": {
                "converted_transaction_count": sum(1 for prepared in contributing_transactions if prepared.is_available),
                "unavailable_transaction_count": sum(1 for prepared in contributing_transactions if not prepared.is_available),
                "unavailable_currencies": sorted(
                    {
                        prepared.raw_currency.strip().upper()
                        for prepared in contributing_transactions
                        if not prepared.is_available and prepared.raw_currency.strip()
                    }
                ),
            },
            "items": items,
        }

    def build_category_breakdown(
        self,
        *,
        period: StatisticsPeriod,
        target_date: date | None,
        reporting_currency: str,
    ) -> dict[str, Any]:
        period_transactions, normalized_target_date = self._transactions_for_period(
            period=period,
            target_date=target_date,
        )

        cumulative_query = self.db.query(Transaction).filter(
            Transaction.transaction_type.in_([TransactionType.INCOME, TransactionType.EXPENSE]),
        )
        yearly_query = self.db.query(Transaction).filter(
            Transaction.transaction_type.in_([TransactionType.INCOME, TransactionType.EXPENSE]),
        )

        if period == StatisticsPeriod.MONTHLY and normalized_target_date is not None:
            cumulative_query = cumulative_query.filter(Transaction.transaction_date <= normalized_target_date)
            yearly_query = yearly_query.filter(
                extract("year", Transaction.transaction_date) == normalized_target_date.year,
                Transaction.transaction_date <= normalized_target_date,
            )
        elif period == StatisticsPeriod.YEARLY and normalized_target_date is not None:
            cumulative_query = cumulative_query.filter(Transaction.transaction_date <= normalized_target_date)
            yearly_query = yearly_query.filter(
                extract("year", Transaction.transaction_date) == normalized_target_date.year,
            )

        cumulative_transactions = cumulative_query.order_by(
            Transaction.transaction_date.asc(),
            Transaction.id.asc(),
        ).all()
        yearly_transactions = yearly_query.order_by(
            Transaction.transaction_date.asc(),
            Transaction.id.asc(),
        ).all()

        items = self._aggregate_category_breakdown(
            period_transactions=period_transactions,
            cumulative_transactions=cumulative_transactions,
            yearly_transactions=yearly_transactions,
            reporting_currency=reporting_currency,
            period=period,
            anchor_date=normalized_target_date,
        )

        return {
            "reporting_currency": reporting_currency,
            "conversion_summary": self._conversion_summary_for(
                cumulative_transactions,
                reporting_currency=reporting_currency,
            ).as_payload(),
            "items": items,
        }

    def build_expense_type_breakdown(
        self,
        *,
        period: StatisticsPeriod,
        target_date: date | None,
        reporting_currency: str,
    ) -> dict[str, Any]:
        _, normalized_target_date = self._transactions_for_period(
            period=period,
            target_date=target_date,
        )
        category_payload = self.build_category_breakdown(
            period=period,
            target_date=normalized_target_date,
            reporting_currency=reporting_currency,
        )

        grouped: dict[str, dict[str, Any]] = {}
        for item in category_payload["items"]:
            if item["transaction_type"] != TransactionType.EXPENSE.value or item["expense_type"] is None:
                continue

            expense_type = item["expense_type"]
            if expense_type not in grouped:
                grouped[expense_type] = {
                    "expense_type": expense_type,
                    "period": item["period"],
                    "date": item["date"],
                    "period_amount": Decimal("0"),
                    "period_transaction_count": 0,
                    "period_percentage": Decimal("0"),
                    "total_amount": Decimal("0"),
                    "transaction_count": 0,
                    "total_amount_cumulative": Decimal("0"),
                    "total_transaction_count": 0,
                    "average_transaction_amount": Decimal("0"),
                    "yearly_amount": Decimal("0"),
                    "yearly_transaction_count": 0,
                    "categories": [],
                }

            grouped_item = grouped[expense_type]
            grouped_item["period_amount"] += StatisticsService._to_decimal(item["period_amount"])
            grouped_item["period_transaction_count"] += item["period_transaction_count"]
            grouped_item["total_amount"] += StatisticsService._to_decimal(item["total_amount"])
            grouped_item["transaction_count"] += item["transaction_count"]
            grouped_item["total_amount_cumulative"] += StatisticsService._to_decimal(item["total_amount_cumulative"])
            grouped_item["total_transaction_count"] += item["total_transaction_count"]
            grouped_item["yearly_amount"] += StatisticsService._to_decimal(item["yearly_amount"])
            grouped_item["yearly_transaction_count"] += item["yearly_transaction_count"]
            grouped_item["categories"].append(
                {
                    "category": item["category"],
                    "period_amount": item["period_amount"],
                    "period_transaction_count": item["period_transaction_count"],
                    "period_percentage": item["period_percentage"],
                }
            )

        expense_total = sum(item["period_amount"] for item in grouped.values())
        items: list[dict[str, Any]] = []
        for item in grouped.values():
            item["period_percentage"] = (
                item["period_amount"] / expense_total * 100 if expense_total > 0 else Decimal("0")
            )
            item["average_transaction_amount"] = (
                item["period_amount"] / item["period_transaction_count"]
                if item["period_transaction_count"] > 0
                else Decimal("0")
            )
            item["period_amount"] = StatisticsService._quantized_float(item["period_amount"])
            item["period_percentage"] = StatisticsService._quantized_float(item["period_percentage"])
            item["total_amount"] = StatisticsService._quantized_float(item["total_amount"])
            item["total_amount_cumulative"] = StatisticsService._quantized_float(item["total_amount_cumulative"])
            item["average_transaction_amount"] = StatisticsService._quantized_float(item["average_transaction_amount"])
            item["yearly_amount"] = StatisticsService._quantized_float(item["yearly_amount"])
            item["categories"].sort(key=lambda category: (-category["period_amount"], category["category"]))
            items.append(item)

        items.sort(key=lambda item: (-item["period_amount"], item["expense_type"]))
        return {
            "reporting_currency": reporting_currency,
            "conversion_summary": category_payload["conversion_summary"],
            "items": items,
        }

    def build_category_averages(
        self,
        *,
        start: date,
        end: date,
        reporting_currency: str,
        transaction_type: TransactionType | None = None,
    ) -> dict[str, Any]:
        transactions = self.db.query(Transaction).filter(
            Transaction.transaction_type.in_([TransactionType.INCOME, TransactionType.EXPENSE]),
            Transaction.transaction_date >= start,
            Transaction.transaction_date <= end,
        ).order_by(Transaction.transaction_date.asc(), Transaction.id.asc()).all()

        if transaction_type is not None:
            transactions = [
                transaction for transaction in transactions if transaction.transaction_type == transaction_type
            ]

        months_count = (end.year - start.year) * 12 + end.month - start.month + 1
        category_data: dict[tuple[str, str, str | None], dict[str, Any]] = {}
        conversion_summary = ConversionSummary()

        for transaction in transactions:
            category_name = self._category_name_for(transaction)
            expense_type = (
                transaction.expense_category.expense_type
                if transaction.transaction_type == TransactionType.EXPENSE
                and transaction.expense_category is not None
                else None
            )
            key = (
                category_name,
                transaction.transaction_type.value,
                expense_type.value if expense_type is not None else None,
            )
            if key not in category_data:
                category_data[key] = {
                    "category_name": category_name,
                    "transaction_type": transaction.transaction_type.value,
                    "expense_type": expense_type.value if expense_type is not None else None,
                    "total_amount": Decimal("0"),
                    "transaction_count": 0,
                    "_available_count": 0,
                }

            category_data[key]["transaction_count"] += 1
            display_money = self._display_money(transaction, reporting_currency)
            conversion_summary.record(display_money, transaction.currency)
            if not display_money.is_available or display_money.display_amount is None:
                continue

            amount = StatisticsService._to_decimal(display_money.display_amount)
            category_data[key]["total_amount"] += (
                abs(amount) if transaction.transaction_type == TransactionType.EXPENSE else amount
            )
            category_data[key]["_available_count"] += 1

        expense_total = sum(
            item["total_amount"]
            for item in category_data.values()
            if item["transaction_type"] == TransactionType.EXPENSE.value
        )
        income_total = sum(
            item["total_amount"]
            for item in category_data.values()
            if item["transaction_type"] == TransactionType.INCOME.value
        )

        categories = []
        for item in category_data.values():
            total = expense_total if item["transaction_type"] == TransactionType.EXPENSE.value else income_total
            average_transaction_amount = (
                item["total_amount"] / item["_available_count"] if item["_available_count"] > 0 else Decimal("0")
            )
            categories.append(
                {
                    "category_name": item["category_name"],
                    "transaction_type": item["transaction_type"],
                    "expense_type": item["expense_type"],
                    "average_amount": StatisticsService._quantized_float(item["total_amount"] / months_count),
                    "total_amount": StatisticsService._quantized_float(item["total_amount"]),
                    "transaction_count": item["transaction_count"],
                    "average_transaction_amount": StatisticsService._quantized_float(average_transaction_amount),
                    "percentage": StatisticsService._quantized_float(
                        item["total_amount"] / total * 100 if total > 0 else Decimal("0")
                    ),
                }
            )

        categories.sort(key=lambda category: (-category["average_amount"], category["category_name"]))
        return {
            "reporting_currency": reporting_currency,
            "conversion_summary": conversion_summary.as_payload(),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "months_count": months_count,
            "categories": categories,
        }

    def build_category_timeseries(
        self,
        *,
        start: date,
        end: date,
        reporting_currency: str,
        transaction_type: TransactionType | None = None,
        category_name: str | None = None,
    ) -> dict[str, Any]:
        target_month_ends = self._month_ends_between(start, end)
        if not target_month_ends:
            return {
                "reporting_currency": reporting_currency,
                "conversion_summary": ConversionSummary().as_payload(),
                "items": [],
            }

        prepared_transactions = self._prepare_category_transactions(
            end=end,
            reporting_currency=reporting_currency,
        )

        def matches_filters(transaction: ReportingCurrencyAnalyticsService._PreparedCategoryTransaction) -> bool:
            if transaction_type is not None and transaction.transaction_type != transaction_type:
                return False
            if category_name is not None and transaction.category_name != category_name:
                return False
            return True

        filtered_transactions = [transaction for transaction in prepared_transactions if matches_filters(transaction)]
        if not filtered_transactions or not any(
            start <= transaction.transaction_date <= end for transaction in filtered_transactions
        ):
            return {
                "reporting_currency": reporting_currency,
                "conversion_summary": ConversionSummary().as_payload(),
                "items": [],
            }

        last_target_month_end = target_month_ends[-1]
        contributing_transactions = [
            transaction
            for transaction in filtered_transactions
            if transaction.month_end <= last_target_month_end
        ]
        if not contributing_transactions:
            return {
                "reporting_currency": reporting_currency,
                "conversion_summary": ConversionSummary().as_payload(),
                "items": [],
            }

        first_month_end = contributing_transactions[0].month_end
        processing_start = min(first_month_end, target_month_ends[0])
        target_month_end_set = set(target_month_ends)

        cumulative_by_key: dict[tuple[str, str, str | None], dict[str, Decimal | int]] = {}
        yearly_by_year_key: dict[tuple[int, str, str, str | None], dict[str, Decimal | int]] = {}
        items: list[dict[str, Any]] = []

        for month_end in self._month_ends_between(processing_start, end):
            month_transactions = self._transactions_for_month(
                contributing_transactions,
                month_end=month_end,
            )
            if not month_transactions and month_end not in target_month_end_set:
                continue

            month_items_by_key: dict[tuple[str, str, str | None], dict[str, Any]] = {}
            for transaction in month_transactions:
                key = (
                    transaction.category_name,
                    transaction.transaction_type.value,
                    transaction.expense_type.value if transaction.expense_type is not None else None,
                )
                if key not in month_items_by_key:
                    month_items_by_key[key] = self._empty_category_bucket(
                        category_name=transaction.category_name,
                        transaction_type=transaction.transaction_type,
                        expense_type=transaction.expense_type,
                        period=StatisticsPeriod.MONTHLY,
                        anchor_date=month_end,
                    )

                item = month_items_by_key[key]
                item["period_transaction_count"] += 1
                if transaction.is_available and transaction.display_amount is not None:
                    amount = (
                        abs(transaction.display_amount)
                        if transaction.transaction_type == TransactionType.EXPENSE
                        else transaction.display_amount
                    )
                    item["period_amount"] += amount
                    item["_period_available_count"] += 1

            for key, item in month_items_by_key.items():
                cumulative = cumulative_by_key.setdefault(
                    key,
                    {"amount": Decimal("0"), "count": 0},
                )
                cumulative["amount"] += item["period_amount"]
                cumulative["count"] += item["period_transaction_count"]
                item["total_amount_cumulative"] = cumulative["amount"]
                item["total_transaction_count"] = cumulative["count"]

                yearly = yearly_by_year_key.setdefault(
                    (month_end.year, *key),
                    {"amount": Decimal("0"), "count": 0},
                )
                yearly["amount"] += item["period_amount"]
                yearly["count"] += item["period_transaction_count"]
                item["yearly_amount"] = yearly["amount"]
                item["yearly_transaction_count"] = yearly["count"]

            if month_end in target_month_end_set:
                items.extend(self._finalize_category_percentages(list(month_items_by_key.values())))

        return {
            "reporting_currency": reporting_currency,
            "conversion_summary": self._conversion_summary_for_prepared(
                contributing_transactions,
            ).as_payload(),
            "items": items,
        }

    @staticmethod
    def _group_month_by_expense_type(
        month_transactions: Iterable[_PreparedCategoryTransaction],
        *,
        month_end: date,
    ) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for transaction in month_transactions:
            if transaction.transaction_type != TransactionType.EXPENSE or transaction.expense_type is None:
                continue

            key = transaction.expense_type.value
            if key not in grouped:
                grouped[key] = {
                    "date": month_end.isoformat(),
                    "expense_type": key,
                    "period_amount": Decimal("0"),
                    "period_transaction_count": 0,
                }

            grouped[key]["period_transaction_count"] += 1
            if transaction.is_available and transaction.display_amount is not None:
                grouped[key]["period_amount"] += abs(transaction.display_amount)

        items = []
        for item in grouped.values():
            item["period_amount"] = StatisticsService._quantized_float(item["period_amount"])
            items.append(item)
        items.sort(key=lambda item: item["expense_type"])
        return items

    def build_expense_type_timeseries(
        self,
        *,
        start: date,
        end: date,
        reporting_currency: str,
        expense_type: ExpenseType | None = None,
    ) -> dict[str, Any]:
        target_month_ends = self._month_ends_between(start, end)
        if not target_month_ends:
            return {
                "reporting_currency": reporting_currency,
                "conversion_summary": ConversionSummary().as_payload(),
                "items": [],
            }

        prepared_transactions = self._prepare_category_transactions(
            end=end,
            reporting_currency=reporting_currency,
        )
        filtered_transactions = [
            transaction
            for transaction in prepared_transactions
            if transaction.transaction_type == TransactionType.EXPENSE
            and transaction.expense_type is not None
            and (expense_type is None or transaction.expense_type == expense_type)
        ]
        if not filtered_transactions or not any(
            start <= transaction.transaction_date <= end for transaction in filtered_transactions
        ):
            return {
                "reporting_currency": reporting_currency,
                "conversion_summary": ConversionSummary().as_payload(),
                "items": [],
            }

        last_target_month_end = target_month_ends[-1]
        contributing_transactions = [
            transaction
            for transaction in filtered_transactions
            if transaction.month_end <= last_target_month_end
        ]
        if not contributing_transactions:
            return {
                "reporting_currency": reporting_currency,
                "conversion_summary": ConversionSummary().as_payload(),
                "items": [],
            }

        target_month_end_set = set(target_month_ends)
        items: list[dict[str, Any]] = []
        for month_end in self._month_ends_between(min(contributing_transactions[0].month_end, target_month_ends[0]), end):
            if month_end not in target_month_end_set:
                continue
            month_transactions = self._transactions_for_month(
                contributing_transactions,
                month_end=month_end,
            )
            items.extend(
                self._group_month_by_expense_type(
                    month_transactions,
                    month_end=month_end,
                )
            )

        return {
            "reporting_currency": reporting_currency,
            "conversion_summary": self._conversion_summary_for_prepared(
                contributing_transactions,
            ).as_payload(),
            "items": items,
        }
