"""Module for backend app services statistics_service."""

import calendar
import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import extract, func, text
from sqlalchemy.orm import Query, Session

from ..models.statistics import (
    CategoryStatistics,
    FinancialStatistics,
    StatisticsPeriod,
)
from ..models.transaction import (
    ExpenseCategory,
    IncomeCategory,
    Transaction,
    TransactionType,
    TransferCategory,
)
from ..services.currency_conversion import CurrencyConversionService

# Set up logging
logging.basicConfig(level=logging.INFO)
logger: logging.Logger = logging.getLogger(__name__)

type StatisticsPayload = dict[str, float | int]
type CategoryStatisticsPayload = dict[str, object]
type TransferSummaryPayload = dict[str, str | int | float]


@dataclass
class TransferSummaryAccumulator:
    """Track transfer totals while building summary rows."""

    subtype: str
    total_incoming: Decimal
    total_outgoing: Decimal
    transaction_count: int


@dataclass(frozen=True)
class CategoryStatisticsQueryContext:
    """Shared filters and period metadata for category statistics."""

    period: StatisticsPeriod
    period_filters: list[object]
    cumulative_filters: list[object]
    yearly_filters: list[object]
    period_total: float


@dataclass(frozen=True)
class CategoryAmountQuery:
    """Parameters for category amount/count aggregation."""

    transaction_type: TransactionType
    category_field: object
    category: ExpenseCategory | IncomeCategory
    filters: list[object]
    use_absolute: bool


class StatisticsService:
    """Represent statistics service."""

    @staticmethod
    def _to_decimal(value: Decimal | float | int) -> Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))

    @classmethod
    def _quantized_float(cls, value: Decimal | float | int) -> float:
        return float(cls._to_decimal(value).quantize(Decimal("0.01")))

    @classmethod
    def _zero_financial_stats(cls) -> dict[str, float | int]:
        return {
            "period_income": 0.0,
            "period_expenses": 0.0,
            "period_net_savings": 0.0,
            "savings_rate": 0.0,
            "total_income": 0.0,
            "total_expenses": 0.0,
            "total_net_savings": 0.0,
            "income_count": 0,
            "expense_count": 0,
            "average_income": 0.0,
            "average_expense": 0.0,
            "yearly_income": 0.0,
            "yearly_expenses": 0.0,
        }

    @classmethod
    def _summarize_transactions(
        cls,
        transactions: list[Transaction],
        *,
        conversion_service: CurrencyConversionService,
        reporting_currency: str,
    ) -> dict[str, float | int]:
        income_total = Decimal("0")
        expense_total = Decimal("0")
        income_count = 0
        expense_count = 0
        converted_income_count = 0
        converted_expense_count = 0

        for trans in transactions:
            if trans.transaction_type not in (
                TransactionType.INCOME,
                TransactionType.EXPENSE,
            ):
                continue

            if trans.transaction_type == TransactionType.INCOME:
                income_count += 1
            elif trans.transaction_type == TransactionType.EXPENSE:
                expense_count += 1

            display_money = conversion_service.convert(
                raw_amount=trans.amount,
                raw_currency=trans.currency,
                reporting_currency=reporting_currency,
                transaction_date=trans.transaction_date,
            )
            if not display_money.is_available or display_money.display_amount is None:
                continue

            display_amount = cls._to_decimal(display_money.display_amount)
            if trans.transaction_type == TransactionType.INCOME:
                income_total += display_amount
                converted_income_count += 1
            elif trans.transaction_type == TransactionType.EXPENSE:
                expense_total += abs(display_amount)
                converted_expense_count += 1

        period_net_savings = income_total - expense_total
        savings_rate = (
            float(period_net_savings / income_total * 100) if income_total > 0 else 0.0
        )

        return {
            "period_income": cls._quantized_float(income_total),
            "period_expenses": cls._quantized_float(expense_total),
            "period_net_savings": cls._quantized_float(period_net_savings),
            "savings_rate": savings_rate,
            "income_count": income_count,
            "expense_count": expense_count,
            "average_income": cls._quantized_float(
                income_total / converted_income_count
            )
            if converted_income_count > 0
            else 0.0,
            "average_expense": cls._quantized_float(
                expense_total / converted_expense_count
            )
            if converted_expense_count > 0
            else 0.0,
        }

    @staticmethod
    def _financial_stat_queries(
        db: Session,
        period: StatisticsPeriod,
        target_date: date | None = None,
    ) -> tuple[Query[Transaction], Query[Transaction], Query[Transaction]]:
        period_query = db.query(Transaction)
        cumulative_query = db.query(Transaction)
        yearly_query = db.query(Transaction)

        if period != StatisticsPeriod.ALL_TIME:
            if target_date is None:
                msg = "target_date is required for period statistics"
                raise ValueError(msg)
            if period == StatisticsPeriod.MONTHLY:
                period_query = period_query.filter(
                    extract("year", Transaction.transaction_date) == target_date.year,
                    extract("month", Transaction.transaction_date) == target_date.month,
                )
                cumulative_query = cumulative_query.filter(
                    Transaction.transaction_date
                    <= target_date.replace(
                        day=calendar.monthrange(target_date.year, target_date.month)[1]
                    )
                )
                yearly_query = yearly_query.filter(
                    extract("year", Transaction.transaction_date) == target_date.year,
                    Transaction.transaction_date
                    <= target_date.replace(
                        day=calendar.monthrange(target_date.year, target_date.month)[1]
                    ),
                )
            elif period == StatisticsPeriod.YEARLY:
                period_query = period_query.filter(
                    extract("year", Transaction.transaction_date) == target_date.year
                )
                cumulative_query = cumulative_query.filter(
                    Transaction.transaction_date <= date(target_date.year, 12, 31)
                )

        return period_query, cumulative_query, yearly_query

    @staticmethod
    def calculate_statistics(
        db: Session,
        period: StatisticsPeriod,
        target_date: date | None = None,
    ) -> StatisticsPayload:
        """Calculate statistics."""
        period_query, cumulative_query, yearly_query = (
            StatisticsService._financial_stat_queries(
                db,
                period,
                target_date,
            )
        )

        # Calculate period-specific stats
        period_transactions = period_query.all()
        period_income = 0.0
        period_expenses = 0.0
        income_count = 0
        expense_count = 0

        for trans in period_transactions:
            if trans.transaction_type == TransactionType.INCOME:
                period_income += trans.amount
                income_count += 1
            elif trans.transaction_type == TransactionType.EXPENSE:
                period_expenses += abs(trans.amount)
                expense_count += 1

        # Calculate cumulative stats
        cumulative_transactions = cumulative_query.all()
        total_income = 0.0
        total_expenses = 0.0

        for trans in cumulative_transactions:
            if trans.transaction_type == TransactionType.INCOME:
                total_income += trans.amount
            elif trans.transaction_type == TransactionType.EXPENSE:
                total_expenses += abs(trans.amount)

        # Calculate yearly stats
        yearly_transactions = yearly_query.all()
        yearly_income = 0.0
        yearly_expenses = 0.0

        for trans in yearly_transactions:
            if trans.transaction_type == TransactionType.INCOME:
                yearly_income += trans.amount
            elif trans.transaction_type == TransactionType.EXPENSE:
                yearly_expenses += abs(trans.amount)

        # Calculate derived statistics
        period_net_savings = period_income - period_expenses
        savings_rate = (
            period_net_savings / period_income * 100 if period_income > 0 else 0.0
        )
        average_income = period_income / income_count if income_count > 0 else 0.0
        average_expense = period_expenses / expense_count if expense_count > 0 else 0.0

        return {
            "period_income": period_income,
            "period_expenses": period_expenses,
            "income_count": income_count,
            "expense_count": expense_count,
            "period_net_savings": period_net_savings,
            "savings_rate": savings_rate,
            "total_income": total_income,
            "total_expenses": total_expenses,
            "total_net_savings": total_income - total_expenses,
            "average_income": average_income,
            "average_expense": average_expense,
            "yearly_income": yearly_income,
            "yearly_expenses": yearly_expenses,
        }

    @staticmethod
    def calculate_statistics_for_reporting_currency(
        db: Session,
        period: StatisticsPeriod,
        target_date: date | None = None,
        reporting_currency: str = "EUR",
    ) -> StatisticsPayload:
        """Calculate statistics for reporting currency."""
        period_query, cumulative_query, yearly_query = (
            StatisticsService._financial_stat_queries(
                db,
                period,
                target_date,
            )
        )

        conversion_service = CurrencyConversionService(db)

        period_transactions = period_query.all()
        period_stats = StatisticsService._summarize_transactions(
            period_transactions,
            conversion_service=conversion_service,
            reporting_currency=reporting_currency,
        )

        cumulative_transactions = cumulative_query.all()
        cumulative_summary = StatisticsService._summarize_transactions(
            cumulative_transactions,
            conversion_service=conversion_service,
            reporting_currency=reporting_currency,
        )

        yearly_transactions = yearly_query.all()
        yearly_summary = StatisticsService._summarize_transactions(
            yearly_transactions,
            conversion_service=conversion_service,
            reporting_currency=reporting_currency,
        )

        return {
            **period_stats,
            "total_income": cumulative_summary["period_income"],
            "total_expenses": cumulative_summary["period_expenses"],
            "total_net_savings": cumulative_summary["period_net_savings"],
            "yearly_income": yearly_summary["period_income"],
            "yearly_expenses": yearly_summary["period_expenses"],
        }

    @staticmethod
    def calculate_category_statistics(
        db: Session, period: StatisticsPeriod, target_date: date | None = None
    ) -> list[CategoryStatisticsPayload]:
        """Calculate statistics for each category for the given period."""
        period_date = StatisticsService._period_target_date(period, target_date)
        period_filters = StatisticsService._period_filters(period, period_date)
        cumulative_filters = StatisticsService._cumulative_filters(period, period_date)
        yearly_filters = StatisticsService._yearly_filters(period, period_date)
        period_income_total = StatisticsService._period_total(
            db,
            transaction_type=TransactionType.INCOME,
            filters=period_filters,
            use_absolute=False,
        )
        period_expense_total = StatisticsService._period_total(
            db,
            transaction_type=TransactionType.EXPENSE,
            filters=period_filters,
            use_absolute=True,
        )
        expense_context = CategoryStatisticsQueryContext(
            period=period,
            period_filters=period_filters,
            cumulative_filters=cumulative_filters,
            yearly_filters=yearly_filters,
            period_total=period_expense_total,
        )
        income_context = CategoryStatisticsQueryContext(
            period=period,
            period_filters=period_filters,
            cumulative_filters=cumulative_filters,
            yearly_filters=yearly_filters,
            period_total=period_income_total,
        )

        expense_categories = [
            StatisticsService._expense_category_statistics_payload(
                db, category, expense_context
            )
            for category in ExpenseCategory
        ]
        income_categories = [
            StatisticsService._income_category_statistics_payload(
                db, category, income_context
            )
            for category in IncomeCategory
        ]
        return expense_categories + income_categories

    @staticmethod
    def _period_target_date(period: StatisticsPeriod, target_date: date | None) -> date:
        if target_date is not None:
            return target_date
        if period == StatisticsPeriod.ALL_TIME:
            return date.min
        msg = "target_date is required for category statistics"
        raise ValueError(msg)

    @staticmethod
    def _period_filters(period: StatisticsPeriod, target_date: date) -> list[object]:
        if period == StatisticsPeriod.MONTHLY:
            return [
                extract("year", Transaction.transaction_date) == target_date.year,
                extract("month", Transaction.transaction_date) == target_date.month,
            ]
        if period == StatisticsPeriod.YEARLY:
            return [extract("year", Transaction.transaction_date) == target_date.year]
        return []

    @staticmethod
    def _cumulative_filters(
        period: StatisticsPeriod, target_date: date
    ) -> list[object]:
        if period == StatisticsPeriod.MONTHLY:
            return [
                Transaction.transaction_date
                <= target_date.replace(
                    day=calendar.monthrange(target_date.year, target_date.month)[1]
                )
            ]
        if period == StatisticsPeriod.YEARLY:
            return [Transaction.transaction_date <= date(target_date.year, 12, 31)]
        return []

    @staticmethod
    def _yearly_filters(period: StatisticsPeriod, target_date: date) -> list[object]:
        if period == StatisticsPeriod.MONTHLY:
            return [
                extract("year", Transaction.transaction_date) == target_date.year,
                Transaction.transaction_date
                <= target_date.replace(
                    day=calendar.monthrange(target_date.year, target_date.month)[1]
                ),
            ]
        return []

    @staticmethod
    def _period_total(
        db: Session,
        *,
        transaction_type: TransactionType,
        filters: list[object],
        use_absolute: bool,
    ) -> float:
        amount_expression = (
            func.sum(func.abs(Transaction.amount))
            if use_absolute
            else func.sum(Transaction.amount)
        )
        return float(
            db.query(amount_expression)
            .filter(Transaction.transaction_type == transaction_type, *filters)
            .scalar()
            or 0.0
        )

    @staticmethod
    def _expense_category_statistics_payload(
        db: Session,
        category: ExpenseCategory,
        context: CategoryStatisticsQueryContext,
    ) -> CategoryStatisticsPayload:
        period_amount, period_count = StatisticsService._category_amount_and_count(
            db,
            CategoryAmountQuery(
                transaction_type=TransactionType.EXPENSE,
                category_field=Transaction.expense_category,
                category=category,
                filters=context.period_filters,
                use_absolute=True,
            ),
        )
        total_amount, total_count = StatisticsService._category_amount_and_count(
            db,
            CategoryAmountQuery(
                transaction_type=TransactionType.EXPENSE,
                category_field=Transaction.expense_category,
                category=category,
                filters=context.cumulative_filters,
                use_absolute=True,
            ),
        )
        yearly_amount, yearly_count = StatisticsService._category_amount_and_count(
            db,
            CategoryAmountQuery(
                transaction_type=TransactionType.EXPENSE,
                category_field=Transaction.expense_category,
                category=category,
                filters=context.yearly_filters,
                use_absolute=True,
            ),
        )
        return {
            "category_name": category.value,
            "transaction_type": TransactionType.EXPENSE,
            "expense_type": category.expense_type,
            "period_amount": period_amount,
            "period_transaction_count": period_count,
            "period_percentage": StatisticsService._percentage(
                period_amount, context.period_total
            ),
            "total_amount": total_amount,
            "total_transaction_count": total_count,
            "average_transaction_amount": StatisticsService._average(
                period_amount, period_count
            ),
            "yearly_amount": yearly_amount
            if context.period == StatisticsPeriod.MONTHLY
            else period_amount,
            "yearly_transaction_count": yearly_count
            if context.period == StatisticsPeriod.MONTHLY
            else period_count,
        }

    @staticmethod
    def _income_category_statistics_payload(
        db: Session,
        category: IncomeCategory,
        context: CategoryStatisticsQueryContext,
    ) -> CategoryStatisticsPayload:
        period_amount, period_count = StatisticsService._category_amount_and_count(
            db,
            CategoryAmountQuery(
                transaction_type=TransactionType.INCOME,
                category_field=Transaction.income_category,
                category=category,
                filters=context.period_filters,
                use_absolute=False,
            ),
        )
        total_amount, total_count = StatisticsService._category_amount_and_count(
            db,
            CategoryAmountQuery(
                transaction_type=TransactionType.INCOME,
                category_field=Transaction.income_category,
                category=category,
                filters=context.cumulative_filters,
                use_absolute=False,
            ),
        )
        yearly_amount, yearly_count = StatisticsService._category_amount_and_count(
            db,
            CategoryAmountQuery(
                transaction_type=TransactionType.INCOME,
                category_field=Transaction.income_category,
                category=category,
                filters=context.yearly_filters,
                use_absolute=False,
            ),
        )
        return {
            "category_name": category.value,
            "transaction_type": TransactionType.INCOME,
            "period_amount": period_amount,
            "period_transaction_count": period_count,
            "period_percentage": StatisticsService._percentage(
                period_amount, context.period_total
            ),
            "total_amount": total_amount,
            "total_transaction_count": total_count,
            "average_transaction_amount": StatisticsService._average(
                period_amount, period_count
            ),
            "yearly_amount": yearly_amount
            if context.period == StatisticsPeriod.MONTHLY
            else period_amount,
            "yearly_transaction_count": yearly_count
            if context.period == StatisticsPeriod.MONTHLY
            else period_count,
        }

    @staticmethod
    def _category_amount_and_count(
        db: Session,
        query: CategoryAmountQuery,
    ) -> tuple[float, int]:
        amount_expression = (
            func.sum(func.abs(Transaction.amount))
            if query.use_absolute
            else func.sum(Transaction.amount)
        )
        amount = float(
            db.query(amount_expression)
            .filter(
                Transaction.transaction_type == query.transaction_type,
                query.category_field == query.category,
                *query.filters,
            )
            .scalar()
            or 0.0
        )
        count = int(
            db.query(func.count(Transaction.id))
            .filter(
                Transaction.transaction_type == query.transaction_type,
                query.category_field == query.category,
                *query.filters,
            )
            .scalar()
            or 0
        )
        return amount, count

    @staticmethod
    def _percentage(amount: float, total: float) -> float:
        return amount / total * 100 if total > 0 else 0.0

    @staticmethod
    def _average(amount: float, count: int) -> float:
        return amount / count if count > 0 else 0.0

    @staticmethod
    def _period_transaction_count(cat_data: CategoryStatisticsPayload) -> int:
        value = cat_data.get("period_transaction_count", 0)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        return 0

    @staticmethod
    def calculate_transfer_summary(
        db: Session,
        start: date,
        end: date,
        reporting_currency: str = "EUR",
    ) -> list[TransferSummaryPayload]:
        """Summarize transfer transactions by transfer category."""
        transfers = (
            db.query(
                Transaction.transfer_category,
                Transaction.amount,
                Transaction.currency,
                Transaction.transaction_date,
            )
            .filter(
                Transaction.transaction_type == TransactionType.TRANSFER,
                Transaction.transaction_date >= start,
                Transaction.transaction_date <= end,
            )
            .all()
        )

        conversion_service = CurrencyConversionService(db)
        summary: dict[str, TransferSummaryAccumulator] = {}
        for transfer_category, amount, raw_currency, transaction_date in transfers:
            category_name = (
                transfer_category.value
                if transfer_category is not None
                else TransferCategory.INTERNAL_TRANSFER.value
            )

            if category_name not in summary:
                summary[category_name] = TransferSummaryAccumulator(
                    subtype=category_name,
                    total_incoming=Decimal("0"),
                    total_outgoing=Decimal("0"),
                    transaction_count=0,
                )

            summary[category_name].transaction_count += 1

            display_money = conversion_service.convert(
                raw_amount=amount,
                raw_currency=raw_currency,
                reporting_currency=reporting_currency,
                transaction_date=transaction_date,
            )
            if not display_money.is_available or display_money.display_amount is None:
                continue

            display_amount = StatisticsService._to_decimal(display_money.display_amount)
            if display_amount < 0:
                summary[category_name].total_outgoing += abs(display_amount)
            else:
                summary[category_name].total_incoming += display_amount

        return [
            {
                "subtype": item.subtype,
                "transaction_count": item.transaction_count,
                "total_outgoing": StatisticsService._quantized_float(
                    item.total_outgoing
                ),
                "total_incoming": StatisticsService._quantized_float(
                    item.total_incoming
                ),
            }
            for item in sorted(summary.values(), key=lambda entry: entry.subtype)
        ]

    @staticmethod
    def update_statistics(db: Session, transaction_date: date) -> None:
        """Update statistics for the given transaction date.

        Uses row-level locking to prevent concurrent update inconsistencies.
        """
        # Get all statistics that need updating with FOR UPDATE lock
        # to prevent concurrent modifications

        # Update monthly stats
        monthly_date = transaction_date.replace(
            day=calendar.monthrange(transaction_date.year, transaction_date.month)[1]
        )
        monthly_stats = (
            db.query(FinancialStatistics)
            .filter(
                FinancialStatistics.period == StatisticsPeriod.MONTHLY,
                FinancialStatistics.date == monthly_date,
            )
            .with_for_update()
            .first()
        )

        if not monthly_stats:
            monthly_stats = FinancialStatistics(
                period=StatisticsPeriod.MONTHLY, date=monthly_date
            )
            db.add(monthly_stats)
            db.flush()  # Ensure it's in the DB before calculating

        # Update yearly stats
        yearly_date = date(transaction_date.year, 12, 31)
        yearly_stats = (
            db.query(FinancialStatistics)
            .filter(
                FinancialStatistics.period == StatisticsPeriod.YEARLY,
                FinancialStatistics.date == yearly_date,
            )
            .with_for_update()
            .first()
        )

        if not yearly_stats:
            yearly_stats = FinancialStatistics(
                period=StatisticsPeriod.YEARLY, date=yearly_date
            )
            db.add(yearly_stats)
            db.flush()  # Ensure it's in the DB before calculating

        # Update all-time stats
        all_time_stats = (
            db.query(FinancialStatistics)
            .filter(FinancialStatistics.period == StatisticsPeriod.ALL_TIME)
            .with_for_update()
            .first()
        )

        if not all_time_stats:
            all_time_stats = FinancialStatistics(period=StatisticsPeriod.ALL_TIME)
            db.add(all_time_stats)
            db.flush()  # Ensure it's in the DB before calculating

        # Now that we have locks on all relevant statistics rows,
        # calculate the updated values
        monthly_data = StatisticsService.calculate_statistics(
            db, StatisticsPeriod.MONTHLY, transaction_date
        )

        yearly_data = StatisticsService.calculate_statistics(
            db, StatisticsPeriod.YEARLY, transaction_date
        )

        all_time_data = StatisticsService.calculate_statistics(
            db, StatisticsPeriod.ALL_TIME
        )

        # Update all statistics objects
        for stats_obj, data in [
            (monthly_stats, monthly_data),
            (yearly_stats, yearly_data),
            (all_time_stats, all_time_data),
        ]:
            for key, value in data.items():
                setattr(stats_obj, key, value)

        # Update category statistics
        StatisticsService.update_category_statistics(db, transaction_date)

        db.commit()

    @staticmethod
    def update_category_statistics(db: Session, transaction_date: date) -> None:
        """Update category statistics for the given transaction date."""
        try:
            # Calculate end of month date for monthly stats
            monthly_date = transaction_date.replace(
                day=calendar.monthrange(transaction_date.year, transaction_date.month)[
                    1
                ]
            )

            # Calculate end of year date for yearly stats
            yearly_date = date(transaction_date.year, 12, 31)

            # Clear existing category statistics for this month
            db.query(CategoryStatistics).filter(
                CategoryStatistics.period == StatisticsPeriod.MONTHLY,
                CategoryStatistics.date == monthly_date,
            ).delete()

            # Clear existing category statistics for this year
            db.query(CategoryStatistics).filter(
                CategoryStatistics.period == StatisticsPeriod.YEARLY,
                CategoryStatistics.date == yearly_date,
            ).delete()

            # Calculate new category statistics
            monthly_categories = StatisticsService.calculate_category_statistics(
                db, StatisticsPeriod.MONTHLY, transaction_date
            )

            yearly_categories = StatisticsService.calculate_category_statistics(
                db, StatisticsPeriod.YEARLY, transaction_date
            )

            all_time_categories = StatisticsService.calculate_category_statistics(
                db, StatisticsPeriod.ALL_TIME
            )

            # Create and save monthly category statistics
            for cat_data in monthly_categories:
                if StatisticsService._period_transaction_count(cat_data) > 0:
                    cat_stat = CategoryStatistics(
                        period=StatisticsPeriod.MONTHLY, date=monthly_date, **cat_data
                    )
                    db.add(cat_stat)

            # Create and save yearly category statistics
            for cat_data in yearly_categories:
                if StatisticsService._period_transaction_count(cat_data) > 0:
                    cat_stat = CategoryStatistics(
                        period=StatisticsPeriod.YEARLY, date=yearly_date, **cat_data
                    )
                    db.add(cat_stat)

            # Update or create all-time category statistics
            db.query(CategoryStatistics).filter(
                CategoryStatistics.period == StatisticsPeriod.ALL_TIME
            ).delete()

            for cat_data in all_time_categories:
                if StatisticsService._period_transaction_count(cat_data) > 0:
                    cat_stat = CategoryStatistics(
                        period=StatisticsPeriod.ALL_TIME, **cat_data
                    )
                    db.add(cat_stat)

            db.flush()

        except Exception:
            logger.exception("Error updating category statistics")
            raise

    @staticmethod
    def initialize_statistics(db: Session, *, commit: bool = True) -> None:
        """Initialize financial statistics for all existing transactions."""
        try:
            # Lock the database during administrative initialization.
            if commit:
                db.execute(text("BEGIN"))

            # Clear existing financial statistics
            db.query(FinancialStatistics).delete()
            db.flush()

            # Get all unique months from transactions
            months = (
                db.query(
                    extract("year", Transaction.transaction_date).label("year"),
                    extract("month", Transaction.transaction_date).label("month"),
                )
                .distinct()
                .all()
            )

            # Get all unique years from transactions
            years = (
                db.query(extract("year", Transaction.transaction_date).label("year"))
                .distinct()
                .all()
            )

            # Initialize monthly statistics for each month
            for year, month in months:
                # set day to the last day of the month
                date_obj = date(
                    year=int(year),
                    month=int(month),
                    day=calendar.monthrange(int(year), int(month))[1],
                )

                # Monthly stats
                monthly_stats = FinancialStatistics(
                    period=StatisticsPeriod.MONTHLY, date=date_obj
                )
                db.add(monthly_stats)

                # Calculate statistics
                monthly_data = StatisticsService.calculate_statistics(
                    db, StatisticsPeriod.MONTHLY, date_obj
                )

                # Update the statistics objects
                for key, value in monthly_data.items():
                    setattr(monthly_stats, key, value)

            # Initialize yearly statistics for each year
            for (year,) in years:
                # set day to the last day of the year
                date_obj = date(year=int(year), month=12, day=31)

                # Yearly stats
                yearly_stats = FinancialStatistics(
                    period=StatisticsPeriod.YEARLY, date=date_obj
                )
                db.add(yearly_stats)

                # Calculate statistics
                yearly_data = StatisticsService.calculate_statistics(
                    db, StatisticsPeriod.YEARLY, date_obj
                )

                # Update the statistics objects
                for key, value in yearly_data.items():
                    setattr(yearly_stats, key, value)

            # Initialize all-time statistics
            all_time_stats = FinancialStatistics(period=StatisticsPeriod.ALL_TIME)
            db.add(all_time_stats)
            all_time_data = StatisticsService.calculate_statistics(
                db, StatisticsPeriod.ALL_TIME
            )

            for key, value in all_time_data.items():
                setattr(all_time_stats, key, value)

            if commit:
                db.commit()
            else:
                db.flush()
        except Exception:
            if commit:
                db.rollback()
            logger.exception("Error initializing financial statistics")
            raise

    @staticmethod
    def initialize_category_statistics(db: Session, *, commit: bool = True) -> None:
        """Initialize category statistics for all existing transactions."""
        try:
            # Lock the database during administrative initialization.
            if commit:
                db.execute(text("BEGIN"))

            # Clear existing category statistics
            db.query(CategoryStatistics).delete()
            db.flush()

            # Get all unique months from transactions
            months = (
                db.query(
                    extract("year", Transaction.transaction_date).label("year"),
                    extract("month", Transaction.transaction_date).label("month"),
                )
                .distinct()
                .all()
            )

            # Get all unique years from transactions
            years = (
                db.query(extract("year", Transaction.transaction_date).label("year"))
                .distinct()
                .all()
            )

            # Initialize monthly category statistics for each month
            for year, month in months:
                date_obj = date(
                    year=int(year),
                    month=int(month),
                    day=calendar.monthrange(int(year), int(month))[1],
                )
                StatisticsService._add_category_statistics_for_period(
                    db, StatisticsPeriod.MONTHLY, date_obj
                )

            # Initialize yearly category statistics for each year
            for (year,) in years:
                date_obj = date(year=int(year), month=12, day=31)
                StatisticsService._add_category_statistics_for_period(
                    db, StatisticsPeriod.YEARLY, date_obj
                )

            StatisticsService._add_category_statistics_for_period(
                db, StatisticsPeriod.ALL_TIME, None
            )

            if commit:
                db.commit()
            else:
                db.flush()
            logger.info("Category statistics initialized successfully")
        except Exception:
            if commit:
                db.rollback()
            logger.exception("Error initializing category statistics")
            raise

    @staticmethod
    def _add_category_statistics_for_period(
        db: Session,
        period: StatisticsPeriod,
        period_date: date | None,
    ) -> None:
        categories = StatisticsService.calculate_category_statistics(
            db, period, period_date
        )
        for cat_data in categories:
            if StatisticsService._period_transaction_count(cat_data) <= 0:
                continue
            stat_kwargs: CategoryStatisticsPayload = {
                "period": period,
                **cat_data,
            }
            if period_date is not None:
                stat_kwargs["date"] = period_date
            db.add(CategoryStatistics(**stat_kwargs))
