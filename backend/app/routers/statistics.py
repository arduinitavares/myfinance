from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
import logging
from datetime import date, datetime
import calendar
import numpy as np

from ..database import get_db
from ..models.transaction import Transaction, TransactionType, ExpenseType
from ..models.statistics import StatisticsPeriod
from ..services.reporting_currency_analytics import ReportingCurrencyAnalyticsService
from ..services.statistics_service import StatisticsService
from ..services.reporting_currency import get_reporting_currency
from ..schemas.statistics import (
    CategoryStatisticsListResponse,
    CategoryAveragesResponse,
    CategoryTimeseriesResponse,
    ExpenseTypeStatisticsResponse,
    ExpenseTypeTimeseriesResponse,
    FinancialStatisticsTimeseriesResponse,
    StatisticsOverviewResponse,
    TransferSummaryResponse,
)
from ..schemas.transaction import TimePeriod

# Set up logging
logger = logging.getLogger(__name__)

# Create router
router = APIRouter(
    prefix="/statistics",
    tags=["statistics"]
)


def _resolve_statistics_period_target(
    db: Session,
    *,
    period: str,
    target_date: str | None,
) -> tuple[StatisticsPeriod, date | None]:
    try:
        stat_period = StatisticsPeriod(period)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid period: {period}. Must be one of: monthly, yearly, all_time",
        ) from exc

    latest_transaction_date = db.query(func.max(Transaction.transaction_date)).scalar()
    if stat_period == StatisticsPeriod.ALL_TIME:
        return stat_period, None

    if target_date:
        try:
            resolved_target_date = datetime.strptime(target_date, "%Y-%m-%d").date()
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid date format: {target_date}. Use YYYY-MM-DD",
            ) from exc
    else:
        if latest_transaction_date is not None:
            resolved_target_date = latest_transaction_date
        else:
            today = datetime.now().date()
            if stat_period == StatisticsPeriod.MONTHLY:
                resolved_target_date = today.replace(day=calendar.monthrange(today.year, today.month)[1])
            else:
                resolved_target_date = date(today.year, 12, 31)

    if stat_period == StatisticsPeriod.MONTHLY:
        resolved_target_date = resolved_target_date.replace(
            day=calendar.monthrange(resolved_target_date.year, resolved_target_date.month)[1]
        )
    else:
        resolved_target_date = date(resolved_target_date.year, 12, 31)

    return stat_period, resolved_target_date

@router.get("/by-expense-type", response_model=ExpenseTypeStatisticsResponse)
def get_expense_type_statistics(
    db: Session = Depends(get_db),
    period: str = Query("monthly", description="Statistics period (monthly, yearly, all_time)"),
    date: str = Query(None, description="Target date in ISO format (YYYY-MM-DD). Required for monthly/yearly periods."),
    reporting_currency: str = Depends(get_reporting_currency),
):
    """Get statistics aggregated by expense type (essential vs discretionary)"""
    try:
        stat_period, target_date = _resolve_statistics_period_target(
            db,
            period=period,
            target_date=date,
        )
        service = ReportingCurrencyAnalyticsService(db)
        return service.build_expense_type_breakdown(
            period=stat_period,
            target_date=target_date,
            reporting_currency=reporting_currency,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_expense_type_statistics: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/by-category", response_model=CategoryStatisticsListResponse)
def get_category_statistics(
    db: Session = Depends(get_db),
    period: str = Query("monthly", description="Statistics period (monthly, yearly, all_time)"),
    date: str = Query(None, description="Target date in ISO format (YYYY-MM-DD). Required for monthly/yearly periods."),
    reporting_currency: str = Depends(get_reporting_currency),
):
    try:
        stat_period, target_date = _resolve_statistics_period_target(
            db,
            period=period,
            target_date=date,
        )
        service = ReportingCurrencyAnalyticsService(db)
        return service.build_category_breakdown(
            period=stat_period,
            target_date=target_date,
            reporting_currency=reporting_currency,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_category_statistics: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/overview", response_model=StatisticsOverviewResponse)
def get_statistics_overview(
    db: Session = Depends(get_db),
    reporting_currency: str = Depends(get_reporting_currency),
):
    try:
        service = ReportingCurrencyAnalyticsService(db)
        return service.build_overview(reporting_currency=reporting_currency)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_statistics_overview: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/transfers/summary", response_model=TransferSummaryResponse)
def get_transfer_summary(
    db: Session = Depends(get_db),
    start_date: str = Query(None, description="Start date in ISO format (YYYY-MM-DD)"),
    end_date: str = Query(None, description="End date in ISO format (YYYY-MM-DD)"),
    reporting_currency: str = Depends(get_reporting_currency),
):
    try:
        latest_transaction_date = db.query(func.max(Transaction.transaction_date)).scalar()
        end = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else latest_transaction_date
        if end is None:
            end = date.today()
        start = (
            datetime.strptime(start_date, "%Y-%m-%d").date()
            if start_date
            else end.replace(day=1)
        )

        if start > end:
            raise HTTPException(status_code=400, detail="Start date must be before end date")

        service = ReportingCurrencyAnalyticsService(db)
        return service.build_transfer_summary(
            start=start,
            end=end,
            reporting_currency=reporting_currency,
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_transfer_summary: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/initialize")
def initialize_statistics(db: Session = Depends(get_db)):
    try:
        StatisticsService.initialize_statistics(db)
        StatisticsService.initialize_category_statistics(db)
        return {"message": "Statistics initialized successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/weekday-distribution")
def get_weekday_distribution(
    db: Session = Depends(get_db),
    transaction_type: TransactionType = Query(None, description="Filter by transaction type (expense, income, or both)"),
    start_date: str = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(None, description="End date (YYYY-MM-DD)")
):
    try:
        # Build base query
        query = db.query(
            # Extract weekday (0=Monday, 6=Sunday in PostgreSQL)
            extract('dow', Transaction.transaction_date).label('weekday'),
            Transaction.amount,
            Transaction.transaction_type
        )
        
        # Apply date filters if provided
        if start_date:
            try:
                start = datetime.strptime(start_date, "%Y-%m-%d").date()
                query = query.filter(Transaction.transaction_date >= start)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid start date format. Use YYYY-MM-DD")
        
        if end_date:
            try:
                end = datetime.strptime(end_date, "%Y-%m-%d").date()
                query = query.filter(Transaction.transaction_date <= end)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid end date format. Use YYYY-MM-DD")
        
        # Apply transaction type filter if provided
        if transaction_type:
            if transaction_type == TransactionType.EXPENSE:
                query = query.filter(Transaction.transaction_type == TransactionType.EXPENSE)
            elif transaction_type == TransactionType.INCOME:
                query = query.filter(Transaction.transaction_type == TransactionType.INCOME)
        
        # Execute query to get all transactions with weekday
        transactions = query.all()
        
        if not transactions:
            return {
                "weekdays": [],
                "message": "No transactions found for the specified criteria"
            }
        
        # Process results by weekday
        weekday_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        
        # Initialize results structure
        results = {}
        for i, day in enumerate(weekday_names):
            results[day] = {
                "expense": {
                    "count": 0,
                    "total": 0,
                    "average": 0,
                    "median": 0,
                    "min": 0,
                    "max": 0,
                    "amounts": []
                },
                "income": {
                    "count": 0,
                    "total": 0,
                    "average": 0,
                    "median": 0,
                    "min": 0,
                    "max": 0,
                    "amounts": []
                }
            }
        
        # Group transactions by weekday and type
        for t in transactions:
            # Convert PostgreSQL's Sunday=0 to Monday=0 format
            weekday_idx = (int(t.weekday) + 6) % 7
            weekday = weekday_names[weekday_idx]
            
            # Determine transaction type and amount
            t_type = "expense" if t.transaction_type == TransactionType.EXPENSE else "income"
            amount = abs(t.amount)  # Use absolute value for calculations
            
            # Add to appropriate category
            results[weekday][t_type]["count"] += 1
            results[weekday][t_type]["total"] += amount
            results[weekday][t_type]["amounts"].append(amount)
        
        # Calculate statistics for each weekday and type
        for day in weekday_names:
            for t_type in ["expense", "income"]:
                amounts = results[day][t_type]["amounts"]
                count = results[day][t_type]["count"]
                
                if count > 0:
                    results[day][t_type]["average"] = round(results[day][t_type]["total"] / count, 2)
                    results[day][t_type]["median"] = round(float(np.median(amounts)), 2) if amounts else 0
                    results[day][t_type]["min"] = round(min(amounts), 2) if amounts else 0
                    results[day][t_type]["max"] = round(max(amounts), 2) if amounts else 0
                
                # Remove the raw amounts array from the response
                del results[day][t_type]["amounts"]
                
                # Round total for better display
                results[day][t_type]["total"] = round(results[day][t_type]["total"], 2)
        
        return {
            "weekdays": results,
            "transaction_count": len(transactions)
        }
    except Exception as e:
        logger.error(f"Error in get_weekday_distribution: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/timeseries", response_model=FinancialStatisticsTimeseriesResponse)
def get_statistics_timeseries(
    db: Session = Depends(get_db),
    start_date: str = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(None, description="End date (YYYY-MM-DD)"),
    time_period: TimePeriod = Query(None, description="Relative time period (3M, 6M, YTD, 1Y, 2Y, ALL_TIME)"),
    reporting_currency: str = Depends(get_reporting_currency),
):
    try:
        start, end = ReportingCurrencyAnalyticsService.resolve_reporting_window(
            db,
            start_date=start_date,
            end_date=end_date,
            time_period=time_period,
        )
        service = ReportingCurrencyAnalyticsService(db)
        return service.build_financial_timeseries(
            start=start,
            end=end,
            reporting_currency=reporting_currency,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/category/averages", response_model=CategoryAveragesResponse)
def get_category_averages(
    db: Session = Depends(get_db),
    transaction_type: TransactionType = Query(None, description="Filter by transaction type (expense, income, or both)"),
    start_date: str = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(None, description="End date (YYYY-MM-DD)"),
    time_period: TimePeriod = Query(None, description="Relative time period (3M, 6M, YTD, 1Y, 2Y, ALL_TIME)"),
    reporting_currency: str = Depends(get_reporting_currency),
):
    try:
        start, end = ReportingCurrencyAnalyticsService.resolve_reporting_window(
            db,
            start_date=start_date,
            end_date=end_date,
            time_period=time_period,
        )
        service = ReportingCurrencyAnalyticsService(db)
        return service.build_category_averages(
            start=start,
            end=end,
            reporting_currency=reporting_currency,
            transaction_type=transaction_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error calculating category averages: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error calculating category averages: {str(e)}")


@router.get("/category/timeseries", response_model=CategoryTimeseriesResponse)
def get_category_statistics_timeseries(
    db: Session = Depends(get_db),
    transaction_type: TransactionType = Query(None, description="Filter by transaction type (expense, income, or both)"),
    category_name: str = Query(None, description="Filter by category name"),
    start_date: str = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(None, description="End date (YYYY-MM-DD)"),
    time_period: TimePeriod = Query(None, description="Relative time period (3M, 6M, YTD, 1Y, 2Y, ALL_TIME)"),
    reporting_currency: str = Depends(get_reporting_currency),
):
    try:
        start, end = ReportingCurrencyAnalyticsService.resolve_reporting_window(
            db,
            start_date=start_date,
            end_date=end_date,
            time_period=time_period,
        )
        service = ReportingCurrencyAnalyticsService(db)
        return service.build_category_timeseries(
            start=start,
            end=end,
            reporting_currency=reporting_currency,
            transaction_type=transaction_type,
            category_name=category_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_category_statistics_timeseries: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/expense-type/timeseries", response_model=ExpenseTypeTimeseriesResponse)
def get_expense_type_statistics_timeseries(
    db: Session = Depends(get_db),
    expense_type: ExpenseType = Query(None, description="Filter by expense type (essential or discretionary)"),
    start_date: str = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(None, description="End date (YYYY-MM-DD)"),
    time_period: TimePeriod = Query(None, description="Relative time period (3M, 6M, YTD, 1Y, 2Y, ALL_TIME)"),
    reporting_currency: str = Depends(get_reporting_currency),
):
    try:
        start, end = ReportingCurrencyAnalyticsService.resolve_reporting_window(
            db,
            start_date=start_date,
            end_date=end_date,
            time_period=time_period,
        )
        service = ReportingCurrencyAnalyticsService(db)
        return service.build_expense_type_timeseries(
            start=start,
            end=end,
            reporting_currency=reporting_currency,
            expense_type=expense_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_expense_type_statistics_timeseries: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
