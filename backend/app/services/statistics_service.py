from sqlalchemy.orm import Session
from datetime import date
import calendar
from decimal import Decimal
from ..models.statistics import FinancialStatistics, CategoryStatistics, StatisticsPeriod
from ..models.transaction import Transaction, TransactionType, ExpenseCategory, IncomeCategory, TransferCategory
from sqlalchemy import func, extract, and_, or_, text
from ..services.currency_conversion import CurrencyConversionService
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class StatisticsService:
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
            if trans.transaction_type not in (TransactionType.INCOME, TransactionType.EXPENSE):
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
        savings_rate = float(period_net_savings / income_total * 100) if income_total > 0 else 0.0

        return {
            "period_income": cls._quantized_float(income_total),
            "period_expenses": cls._quantized_float(expense_total),
            "period_net_savings": cls._quantized_float(period_net_savings),
            "savings_rate": savings_rate,
            "income_count": income_count,
            "expense_count": expense_count,
            "average_income": cls._quantized_float(income_total / converted_income_count) if converted_income_count > 0 else 0.0,
            "average_expense": cls._quantized_float(expense_total / converted_expense_count) if converted_expense_count > 0 else 0.0,
        }

    @staticmethod
    def _financial_stat_queries(
        db: Session,
        period: StatisticsPeriod,
        target_date: date = None,
    ):
        period_query = db.query(Transaction)
        cumulative_query = db.query(Transaction)
        yearly_query = db.query(Transaction)

        if period != StatisticsPeriod.ALL_TIME:
            if period == StatisticsPeriod.MONTHLY:
                period_query = period_query.filter(
                    extract('year', Transaction.transaction_date) == target_date.year,
                    extract('month', Transaction.transaction_date) == target_date.month
                )
                cumulative_query = cumulative_query.filter(
                    Transaction.transaction_date <= target_date.replace(day=calendar.monthrange(target_date.year, target_date.month)[1])
                )
                yearly_query = yearly_query.filter(
                    extract('year', Transaction.transaction_date) == target_date.year,
                    Transaction.transaction_date <= target_date.replace(
                        day=calendar.monthrange(target_date.year, target_date.month)[1]
                    )
                )
            elif period == StatisticsPeriod.YEARLY:
                period_query = period_query.filter(
                    extract('year', Transaction.transaction_date) == target_date.year
                )
                cumulative_query = cumulative_query.filter(
                    Transaction.transaction_date <= date(target_date.year, 12, 31)
                )

        return period_query, cumulative_query, yearly_query

    @staticmethod
    def calculate_statistics(
        db: Session,
        period: StatisticsPeriod,
        target_date: date = None,
    ):
        period_query, cumulative_query, yearly_query = StatisticsService._financial_stat_queries(
            db,
            period,
            target_date,
        )

        # Calculate period-specific stats
        period_transactions = period_query.all()
        period_stats = {
            'period_income': 0,
            'period_expenses': 0,
            'income_count': 0,
            'expense_count': 0
        }

        for trans in period_transactions:
            if trans.transaction_type == TransactionType.INCOME:
                period_stats['period_income'] += trans.amount
                period_stats['income_count'] += 1
            elif trans.transaction_type == TransactionType.EXPENSE:
                period_stats['period_expenses'] += abs(trans.amount)
                period_stats['expense_count'] += 1

        # Calculate cumulative stats
        cumulative_transactions = cumulative_query.all()
        cumulative_stats = {
            'total_income': 0,
            'total_expenses': 0
        }

        for trans in cumulative_transactions:
            if trans.transaction_type == TransactionType.INCOME:
                cumulative_stats['total_income'] += trans.amount
            elif trans.transaction_type == TransactionType.EXPENSE:
                cumulative_stats['total_expenses'] += abs(trans.amount)

        # Calculate yearly stats
        yearly_transactions = yearly_query.all()
        yearly_stats = {
            'yearly_income': 0,
            'yearly_expenses': 0
        }

        for trans in yearly_transactions:
            if trans.transaction_type == TransactionType.INCOME:
                yearly_stats['yearly_income'] += trans.amount
            elif trans.transaction_type == TransactionType.EXPENSE:
                yearly_stats['yearly_expenses'] += abs(trans.amount)

        # Calculate derived statistics
        period_stats['period_net_savings'] = period_stats['period_income'] - period_stats['period_expenses']
        period_stats['savings_rate'] = (period_stats['period_net_savings'] / period_stats['period_income'] * 100) if period_stats['period_income'] > 0 else 0

        cumulative_stats['total_net_savings'] = cumulative_stats['total_income'] - cumulative_stats['total_expenses']

        # Calculate averages
        period_stats['average_income'] = period_stats['period_income'] / period_stats['income_count'] if period_stats['income_count'] > 0 else 0
        period_stats['average_expense'] = period_stats['period_expenses'] / period_stats['expense_count'] if period_stats['expense_count'] > 0 else 0

        return {**period_stats, **cumulative_stats, **yearly_stats}

    @staticmethod
    def calculate_statistics_for_reporting_currency(
        db: Session,
        period: StatisticsPeriod,
        target_date: date = None,
        reporting_currency: str = "EUR",
    ):
        period_query, cumulative_query, yearly_query = StatisticsService._financial_stat_queries(
            db,
            period,
            target_date,
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
    def calculate_category_statistics(db: Session, period: StatisticsPeriod, target_date: date = None):
        """
        Calculate statistics for each category for the given period
        """
        # Base queries for different time periods
        period_query = db.query(Transaction)
        cumulative_query = db.query(Transaction)
        
        # Apply time filters
        if period != StatisticsPeriod.ALL_TIME:
            if period == StatisticsPeriod.MONTHLY:
                period_query = period_query.filter(
                    extract('year', Transaction.transaction_date) == target_date.year,
                    extract('month', Transaction.transaction_date) == target_date.month
                )
                cumulative_query = cumulative_query.filter(
                    Transaction.transaction_date <= target_date.replace(day=calendar.monthrange(target_date.year, target_date.month)[1])
                )
            elif period == StatisticsPeriod.YEARLY:
                period_query = period_query.filter(
                    extract('year', Transaction.transaction_date) == target_date.year
                )
                cumulative_query = cumulative_query.filter(
                    Transaction.transaction_date <= date(target_date.year, 12, 31)
                )
        
        # Build filters based on period
        period_filters = []
        if period != StatisticsPeriod.ALL_TIME:
            if period == StatisticsPeriod.MONTHLY:
                period_filters = [
                    extract('year', Transaction.transaction_date) == target_date.year,
                    extract('month', Transaction.transaction_date) == target_date.month
                ]
            elif period == StatisticsPeriod.YEARLY:
                period_filters = [
                    extract('year', Transaction.transaction_date) == target_date.year
                ]
                
        # Get period totals for percentage calculations
        period_income_total = db.query(func.sum(Transaction.amount)).filter(
            Transaction.transaction_type == TransactionType.INCOME,
            *period_filters
        ).scalar() or 0
        
        period_expense_total = db.query(func.sum(func.abs(Transaction.amount))).filter(
            Transaction.transaction_type == TransactionType.EXPENSE,
            *period_filters
        ).scalar() or 0
        
        # Get all expense categories
        expense_categories = []
        for cat in ExpenseCategory:
            # Period-specific stats
            period_amount = db.query(func.sum(func.abs(Transaction.amount))).filter(
                Transaction.transaction_type == TransactionType.EXPENSE,
                Transaction.expense_category == cat,
                *period_filters
            ).scalar() or 0
            
            period_count = db.query(func.count(Transaction.id)).filter(
                Transaction.transaction_type == TransactionType.EXPENSE,
                Transaction.expense_category == cat,
                *period_filters
            ).scalar() or 0
            
            # Calculate percentage of total expenses
            period_percentage = (period_amount / period_expense_total * 100) if period_expense_total > 0 else 0
            
            # Build cumulative filters
            cumulative_filters = []
            if period != StatisticsPeriod.ALL_TIME:
                if period == StatisticsPeriod.MONTHLY:
                    cumulative_filters = [
                        Transaction.transaction_date <= target_date.replace(
                            day=calendar.monthrange(target_date.year, target_date.month)[1]
                        )
                    ]
                elif period == StatisticsPeriod.YEARLY:
                    cumulative_filters = [
                        Transaction.transaction_date <= date(target_date.year, 12, 31)
                    ]
            
            # Cumulative stats
            total_amount = db.query(func.sum(func.abs(Transaction.amount))).filter(
                Transaction.transaction_type == TransactionType.EXPENSE,
                Transaction.expense_category == cat,
                *cumulative_filters
            ).scalar() or 0
            
            total_count = db.query(func.count(Transaction.id)).filter(
                Transaction.transaction_type == TransactionType.EXPENSE,
                Transaction.expense_category == cat,
                *cumulative_filters
            ).scalar() or 0
            
            # Build yearly filters
            yearly_filters = []
            if period != StatisticsPeriod.ALL_TIME and period != StatisticsPeriod.YEARLY:
                # For monthly, we still need yearly stats
                if period == StatisticsPeriod.MONTHLY:
                    yearly_filters = [
                        extract('year', Transaction.transaction_date) == target_date.year,
                        Transaction.transaction_date <= target_date.replace(
                            day=calendar.monthrange(target_date.year, target_date.month)[1]
                        )
                    ]
            
            # Yearly stats
            yearly_amount = db.query(func.sum(func.abs(Transaction.amount))).filter(
                Transaction.transaction_type == TransactionType.EXPENSE,
                Transaction.expense_category == cat,
                *yearly_filters
            ).scalar() or 0
            
            yearly_count = db.query(func.count(Transaction.id)).filter(
                Transaction.transaction_type == TransactionType.EXPENSE,
                Transaction.expense_category == cat,
                *yearly_filters
            ).scalar() or 0
            
            # Average transaction amount
            avg_amount = period_amount / period_count if period_count > 0 else 0
            
            expense_categories.append({
                'category_name': cat.value,
                'transaction_type': TransactionType.EXPENSE,
                'expense_type': cat.expense_type,  # Add the expense type (essential or discretionary)
                'period_amount': period_amount,
                'period_transaction_count': period_count,
                'period_percentage': period_percentage,
                'total_amount': total_amount,
                'total_transaction_count': total_count,
                'average_transaction_amount': avg_amount,
                'yearly_amount': yearly_amount if StatisticsPeriod.MONTHLY else period_amount,
                'yearly_transaction_count': yearly_count if StatisticsPeriod.MONTHLY else period_count
            })
        
        # Get all income categories
        income_categories = []
        for cat in IncomeCategory:
            # Period-specific stats
            period_amount = db.query(func.sum(Transaction.amount)).filter(
                Transaction.transaction_type == TransactionType.INCOME,
                Transaction.income_category == cat,
                *period_filters
            ).scalar() or 0
            
            period_count = db.query(func.count(Transaction.id)).filter(
                Transaction.transaction_type == TransactionType.INCOME,
                Transaction.income_category == cat,
                *period_filters
            ).scalar() or 0
            
            # Calculate percentage of total income
            period_percentage = (period_amount / period_income_total * 100) if period_income_total > 0 else 0
            
            # Build cumulative filters (reusing from above)
            cumulative_filters = []
            if period != StatisticsPeriod.ALL_TIME:
                if period == StatisticsPeriod.MONTHLY:
                    cumulative_filters = [
                        Transaction.transaction_date <= target_date.replace(
                            day=calendar.monthrange(target_date.year, target_date.month)[1]
                        )
                    ]
                elif period == StatisticsPeriod.YEARLY:
                    cumulative_filters = [
                        Transaction.transaction_date <= date(target_date.year, 12, 31)
                    ]
                    
            # Cumulative stats
            total_amount = db.query(func.sum(Transaction.amount)).filter(
                Transaction.transaction_type == TransactionType.INCOME,
                Transaction.income_category == cat,
                *cumulative_filters
            ).scalar() or 0
            
            total_count = db.query(func.count(Transaction.id)).filter(
                Transaction.transaction_type == TransactionType.INCOME,
                Transaction.income_category == cat,
                *cumulative_filters
            ).scalar() or 0
            
            # Build yearly filters (reusing from above)
            yearly_filters = []
            if period != StatisticsPeriod.ALL_TIME and period != StatisticsPeriod.YEARLY:
                # For monthly, we still need yearly stats
                if period == StatisticsPeriod.MONTHLY:
                    yearly_filters = [
                        extract('year', Transaction.transaction_date) == target_date.year,
                        Transaction.transaction_date <= target_date.replace(
                            day=calendar.monthrange(target_date.year, target_date.month)[1]
                        )
                    ]
            
            # Yearly stats
            yearly_amount = db.query(func.sum(Transaction.amount)).filter(
                Transaction.transaction_type == TransactionType.INCOME,
                Transaction.income_category == cat,
                *yearly_filters
            ).scalar() or 0
            
            yearly_count = db.query(func.count(Transaction.id)).filter(
                Transaction.transaction_type == TransactionType.INCOME,
                Transaction.income_category == cat,
                *yearly_filters
            ).scalar() or 0
            
            # Average transaction amount
            avg_amount = period_amount / period_count if period_count > 0 else 0
            
            income_categories.append({
                'category_name': cat.value,
                'transaction_type': TransactionType.INCOME,
                'period_amount': period_amount,
                'period_transaction_count': period_count,
                'period_percentage': period_percentage,
                'total_amount': total_amount,
                'total_transaction_count': total_count,
                'average_transaction_amount': avg_amount,
                'yearly_amount': yearly_amount if StatisticsPeriod.MONTHLY else period_amount,
                'yearly_transaction_count': yearly_count if StatisticsPeriod.MONTHLY else period_count
            })
        
        return expense_categories + income_categories

    @staticmethod
    def calculate_transfer_summary(
        db: Session,
        start: date,
        end: date,
        reporting_currency: str = "EUR",
    ):
        """
        Summarize transfer transactions by transfer category.
        """
        transfers = db.query(
            Transaction.transfer_category,
            Transaction.amount,
            Transaction.currency,
            Transaction.transaction_date,
        ).filter(
            Transaction.transaction_type == TransactionType.TRANSFER,
            Transaction.transaction_date >= start,
            Transaction.transaction_date <= end,
        ).all()

        conversion_service = CurrencyConversionService(db)
        summary = {}
        for transfer_category, amount, raw_currency, transaction_date in transfers:
            category_name = (
                transfer_category.value
                if transfer_category is not None
                else TransferCategory.INTERNAL_TRANSFER.value
            )

            if category_name not in summary:
                summary[category_name] = {
                    "subtype": category_name,
                    "total_incoming": Decimal("0"),
                    "total_outgoing": Decimal("0"),
                    "transaction_count": 0,
                }

            summary[category_name]["transaction_count"] += 1

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
                summary[category_name]["total_outgoing"] += abs(display_amount)
            else:
                summary[category_name]["total_incoming"] += display_amount

        items = []
        for item in sorted(summary.values(), key=lambda entry: entry["subtype"]):
            items.append(
                {
                    "subtype": item["subtype"],
                    "transaction_count": item["transaction_count"],
                    "total_outgoing": StatisticsService._quantized_float(item["total_outgoing"]),
                    "total_incoming": StatisticsService._quantized_float(item["total_incoming"]),
                }
            )

        return items

    @staticmethod
    def update_statistics(db: Session, transaction_date: date):
        """
        Update statistics for the given transaction date.
        Uses row-level locking to prevent concurrent updates from causing inconsistencies.
        """
        # Get all statistics that need updating with FOR UPDATE lock 
        # to prevent concurrent modifications
        
        # Update monthly stats
        monthly_date = transaction_date.replace(day=calendar.monthrange(transaction_date.year, transaction_date.month)[1])
        monthly_stats = db.query(FinancialStatistics).filter(
            FinancialStatistics.period == StatisticsPeriod.MONTHLY,
            FinancialStatistics.date == monthly_date
        ).with_for_update().first()
        
        if not monthly_stats:
            monthly_stats = FinancialStatistics(
                period=StatisticsPeriod.MONTHLY,
                date=monthly_date
            )
            db.add(monthly_stats)
            db.flush()  # Ensure it's in the DB before calculating
        
        # Update yearly stats
        yearly_date = date(transaction_date.year, 12, 31)
        yearly_stats = db.query(FinancialStatistics).filter(
            FinancialStatistics.period == StatisticsPeriod.YEARLY,
            FinancialStatistics.date == yearly_date
        ).with_for_update().first()
        
        if not yearly_stats:
            yearly_stats = FinancialStatistics(
                period=StatisticsPeriod.YEARLY,
                date=yearly_date
            )
            db.add(yearly_stats)
            db.flush()  # Ensure it's in the DB before calculating
        
        # Update all-time stats
        all_time_stats = db.query(FinancialStatistics).filter(
            FinancialStatistics.period == StatisticsPeriod.ALL_TIME
        ).with_for_update().first()
        
        if not all_time_stats:
            all_time_stats = FinancialStatistics(
                period=StatisticsPeriod.ALL_TIME
            )
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
            (all_time_stats, all_time_data)
        ]:
            for key, value in data.items():
                setattr(stats_obj, key, value)
                
        # Update category statistics
        StatisticsService.update_category_statistics(db, transaction_date)
        
        db.commit()

    @staticmethod
    def update_category_statistics(db: Session, transaction_date: date):
        """
        Update category statistics for the given transaction date.
        """
        try:
            # Calculate end of month date for monthly stats
            monthly_date = transaction_date.replace(day=calendar.monthrange(transaction_date.year, transaction_date.month)[1])
            
            # Calculate end of year date for yearly stats
            yearly_date = date(transaction_date.year, 12, 31)
            
            # Clear existing category statistics for this month
            db.query(CategoryStatistics).filter(
                CategoryStatistics.period == StatisticsPeriod.MONTHLY,
                CategoryStatistics.date == monthly_date
            ).delete()
            
            # Clear existing category statistics for this year
            db.query(CategoryStatistics).filter(
                CategoryStatistics.period == StatisticsPeriod.YEARLY,
                CategoryStatistics.date == yearly_date
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
                if cat_data['period_transaction_count'] > 0:
                    cat_stat = CategoryStatistics(
                        period=StatisticsPeriod.MONTHLY,
                        date=monthly_date,
                        **cat_data
                    )
                    db.add(cat_stat)
            
            # Create and save yearly category statistics
            for cat_data in yearly_categories:
                if cat_data['period_transaction_count'] > 0:
                    cat_stat = CategoryStatistics(
                        period=StatisticsPeriod.YEARLY,
                        date=yearly_date,
                        **cat_data
                    )
                    db.add(cat_stat)
            
            # Update or create all-time category statistics
            db.query(CategoryStatistics).filter(
                CategoryStatistics.period == StatisticsPeriod.ALL_TIME
            ).delete()
            
            for cat_data in all_time_categories:
                if cat_data['period_transaction_count'] > 0:
                    cat_stat = CategoryStatistics(
                        period=StatisticsPeriod.ALL_TIME,
                        **cat_data
                    )
                    db.add(cat_stat)
            
            db.flush()
                
        except Exception as e:
            logger.error(f"Error updating category statistics: {str(e)}")
            raise e

    @staticmethod
    def initialize_statistics(db: Session, *, commit: bool = True):
        """Initialize financial statistics for all existing transactions"""
        try:
            # Lock the database to prevent any concurrent modifications during initialization
            # This is an administrative operation that should run when the system is not heavily used
            if commit:
                db.execute(text("BEGIN"))
            
            # Clear existing financial statistics
            db.query(FinancialStatistics).delete()
            db.flush()
            
            # Get all unique months from transactions
            months = db.query(
                extract('year', Transaction.transaction_date).label('year'),
                extract('month', Transaction.transaction_date).label('month')
            ).distinct().all()
            
            # Get all unique years from transactions
            years = db.query(
                extract('year', Transaction.transaction_date).label('year')
            ).distinct().all()
            
            # Initialize monthly statistics for each month
            for year, month in months:
                # set day to the last day of the month
                date_obj = date(year=int(year), month=int(month), day=calendar.monthrange(int(year), int(month))[1])
                
                # Monthly stats
                monthly_stats = FinancialStatistics(
                    period=StatisticsPeriod.MONTHLY,
                    date=date_obj
                )
                db.add(monthly_stats)
                
                # Calculate statistics
                monthly_data = StatisticsService.calculate_statistics(db, StatisticsPeriod.MONTHLY, date_obj)
                
                # Update the statistics objects
                for key, value in monthly_data.items():
                    setattr(monthly_stats, key, value)
            
            # Initialize yearly statistics for each year
            for (year,) in years:
                # set day to the last day of the year
                date_obj = date(year=int(year), month=12, day=31)
                
                # Yearly stats
                yearly_stats = FinancialStatistics(
                    period=StatisticsPeriod.YEARLY,
                    date=date_obj
                )
                db.add(yearly_stats)
                
                # Calculate statistics
                yearly_data = StatisticsService.calculate_statistics(db, StatisticsPeriod.YEARLY, date_obj)
                
                # Update the statistics objects
                for key, value in yearly_data.items():
                    setattr(yearly_stats, key, value)
            
            # Initialize all-time statistics
            all_time_stats = FinancialStatistics(period=StatisticsPeriod.ALL_TIME)
            db.add(all_time_stats)
            all_time_data = StatisticsService.calculate_statistics(db, StatisticsPeriod.ALL_TIME)
            
            for key, value in all_time_data.items():
                setattr(all_time_stats, key, value)
            
            if commit:
                db.commit()
            else:
                db.flush()
        except Exception as e:
            if commit:
                db.rollback()
            logger.error(f"Error initializing financial statistics: {str(e)}")
            raise e
            
    @staticmethod
    def initialize_category_statistics(db: Session, *, commit: bool = True):
        """Initialize category statistics for all existing transactions"""
        try:
            # Lock the database to prevent any concurrent modifications during initialization
            # This is an administrative operation that should run when the system is not heavily used
            if commit:
                db.execute(text("BEGIN"))
            
            # Clear existing category statistics
            db.query(CategoryStatistics).delete()
            db.flush()
            
            # Get all unique months from transactions
            months = db.query(
                extract('year', Transaction.transaction_date).label('year'),
                extract('month', Transaction.transaction_date).label('month')
            ).distinct().all()
            
            # Get all unique years from transactions
            years = db.query(
                extract('year', Transaction.transaction_date).label('year')
            ).distinct().all()
            
            # Initialize monthly category statistics for each month
            for year, month in months:
                # set day to the last day of the month
                date_obj = date(year=int(year), month=int(month), day=calendar.monthrange(int(year), int(month))[1])
                
                # Calculate category statistics for monthly
                monthly_categories = StatisticsService.calculate_category_statistics(
                    db, StatisticsPeriod.MONTHLY, date_obj
                )
                
                # Create and save monthly category statistics
                for cat_data in monthly_categories:
                    if cat_data['period_transaction_count'] > 0:
                        cat_stat = CategoryStatistics(
                            period=StatisticsPeriod.MONTHLY,
                            date=date_obj,
                            **cat_data
                        )
                        db.add(cat_stat)
            
            # Initialize yearly category statistics for each year
            for (year,) in years:
                # set day to the last day of the year
                date_obj = date(year=int(year), month=12, day=31)
                
                # Calculate category statistics for yearly
                yearly_categories = StatisticsService.calculate_category_statistics(
                    db, StatisticsPeriod.YEARLY, date_obj
                )
                
                # Create and save yearly category statistics
                for cat_data in yearly_categories:
                    if cat_data['period_transaction_count'] > 0:
                        cat_stat = CategoryStatistics(
                            period=StatisticsPeriod.YEARLY,
                            date=date_obj,
                            **cat_data
                        )
                        db.add(cat_stat)
            
            # Initialize all-time category statistics
            all_time_categories = StatisticsService.calculate_category_statistics(
                db, StatisticsPeriod.ALL_TIME
            )
            
            for cat_data in all_time_categories:
                if cat_data['period_transaction_count'] > 0:
                    cat_stat = CategoryStatistics(
                        period=StatisticsPeriod.ALL_TIME,
                        **cat_data
                    )
                    db.add(cat_stat)
            
            if commit:
                db.commit()
            else:
                db.flush()
            logger.info("Category statistics initialized successfully")
        except Exception as e:
            if commit:
                db.rollback()
            logger.error(f"Error initializing category statistics: {str(e)}")
            raise e
