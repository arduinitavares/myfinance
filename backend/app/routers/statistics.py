"""Module for backend app routers statistics."""

import calendar
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Annotated, Any, NoReturn, Protocol, cast

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import extract, func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.statistics import StatisticsPeriod
from ..models.transaction import ExpenseType, Transaction, TransactionType
from ..schemas.statistics import (
    CategoryAveragesResponse,
    CategoryStatisticsListResponse,
    CategoryTimeseriesResponse,
    ExpenseTypeStatisticsResponse,
    ExpenseTypeTimeseriesResponse,
    FinancialStatisticsTimeseriesResponse,
    StatisticsOverviewResponse,
    TransferSummaryResponse,
)
from ..schemas.transaction import TimePeriod
from ..services.reporting_currency import get_reporting_currency
from ..services.reporting_currency_analytics import ReportingCurrencyAnalyticsService
from ..services.statistics_service import StatisticsService

# Set up logging
logger: Any = logging.getLogger(__name__)

# Create router
router: Any = APIRouter(prefix="/statistics", tags=["statistics"])
type DbSession = Annotated[Session, Depends(get_db)]
type ReportingCurrency = Annotated[str, Depends(get_reporting_currency)]
type StatisticsPeriodQuery = Annotated[
    str,
    Query("monthly", description="Statistics period (monthly, yearly, all_time)"),
]
type StatisticsTargetDateQuery = Annotated[
    str | None,
    Query(
        None,
        alias="date",
        description=(
            "Target date in ISO format (YYYY-MM-DD). Required for monthly/yearly "
            "periods."
        ),
    ),
]
type StartDateQuery = Annotated[
    str | None,
    Query(None, description="Start date (YYYY-MM-DD)"),
]
type EndDateQuery = Annotated[
    str | None,
    Query(None, description="End date (YYYY-MM-DD)"),
]
type IsoStartDateQuery = Annotated[
    str | None,
    Query(None, description="Start date in ISO format (YYYY-MM-DD)"),
]
type IsoEndDateQuery = Annotated[
    str | None,
    Query(None, description="End date in ISO format (YYYY-MM-DD)"),
]
type TimePeriodQuery = Annotated[
    TimePeriod | None,
    Query(None, description="Relative time period (3M, 6M, YTD, 1Y, 2Y, ALL_TIME)"),
]
type TransactionTypeQuery = Annotated[
    TransactionType | None,
    Query(None, description="Filter by transaction type (expense, income, or both)"),
]
type ExpenseTypeQuery = Annotated[
    ExpenseType | None,
    Query(None, description="Filter by expense type (essential or discretionary)"),
]
type CategoryNameQuery = Annotated[
    str | None,
    Query(None, description="Filter by category name"),
]

STATISTICS_ROUTER_ERRORS: tuple[type[Exception], ...] = (
    RuntimeError,
    SQLAlchemyError,
    TypeError,
)
WEEKDAY_NAMES: tuple[str, ...] = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


@dataclass(frozen=True)
class PeriodBreakdownParams:
    """Query parameters for period breakdown endpoints."""

    period: StatisticsPeriodQuery = "monthly"
    target_date: StatisticsTargetDateQuery = None


@dataclass(frozen=True)
class ReportingWindowParams:
    """Query parameters for reporting-window endpoints."""

    start_date: StartDateQuery = None
    end_date: EndDateQuery = None
    time_period: TimePeriodQuery = None


@dataclass(frozen=True)
class TransferSummaryParams:
    """Query parameters for transfer summary."""

    start_date: IsoStartDateQuery = None
    end_date: IsoEndDateQuery = None


@dataclass(frozen=True)
class WeekdayDistributionParams:
    """Query parameters for weekday distribution."""

    transaction_type: TransactionTypeQuery = None
    start_date: StartDateQuery = None
    end_date: EndDateQuery = None


@dataclass(frozen=True)
class CategoryAveragesParams(ReportingWindowParams):
    """Query parameters for category averages."""

    transaction_type: TransactionTypeQuery = None


@dataclass(frozen=True)
class CategoryTimeseriesParams(ReportingWindowParams):
    """Query parameters for category timeseries."""

    transaction_type: TransactionTypeQuery = None
    category_name: CategoryNameQuery = None


@dataclass(frozen=True)
class ExpenseTypeTimeseriesParams(ReportingWindowParams):
    """Query parameters for expense type timeseries."""

    expense_type: ExpenseTypeQuery = None


@dataclass
class WeekdayBucket:
    """Accumulate weekday distribution statistics."""

    count: int = 0
    total: float = 0.0
    amounts: list[float] = field(default_factory=list)

    def record(self, amount: float) -> None:
        """Record an amount in this bucket."""
        self.count += 1
        self.total += amount
        self.amounts.append(amount)

    def as_payload(self) -> dict[str, float | int]:
        """Return the API payload for this bucket."""
        average = round(self.total / self.count, 2) if self.count > 0 else 0
        median = round(float(np.median(self.amounts)), 2) if self.amounts else 0
        minimum = round(min(self.amounts), 2) if self.amounts else 0
        maximum = round(max(self.amounts), 2) if self.amounts else 0
        return {
            "count": self.count,
            "total": round(self.total, 2),
            "average": average,
            "median": median,
            "min": minimum,
            "max": maximum,
        }


class WeekdayDistributionRow(Protocol):
    """Fields returned by the weekday distribution query."""

    weekday: int
    amount: float
    transaction_type: TransactionType


type PeriodBreakdownDependency = Annotated[PeriodBreakdownParams, Depends()]
type ReportingWindowDependency = Annotated[ReportingWindowParams, Depends()]
type TransferSummaryDependency = Annotated[TransferSummaryParams, Depends()]
type WeekdayDistributionDependency = Annotated[WeekdayDistributionParams, Depends()]
type CategoryAveragesDependency = Annotated[CategoryAveragesParams, Depends()]
type CategoryTimeseriesDependency = Annotated[CategoryTimeseriesParams, Depends()]
type ExpenseTypeTimeseriesDependency = Annotated[
    ExpenseTypeTimeseriesParams, Depends()
]


def _today() -> date:
    return datetime.now(UTC).date()


def _parse_iso_date(value: str | None, *, field_name: str = "date") -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {field_name} format. Use YYYY-MM-DD",
        ) from exc


def _raise_http_error(status_code: int, detail: str) -> NoReturn:
    raise HTTPException(status_code=status_code, detail=detail)


def _raise_server_error(message: str, exc: Exception) -> NoReturn:
    logger.exception(message)
    raise HTTPException(status_code=500, detail=str(exc)) from exc


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
            detail=(
                f"Invalid period: {period}. "
                "Must be one of: monthly, yearly, all_time"
            ),
        ) from exc

    latest_transaction_date = db.query(func.max(Transaction.transaction_date)).scalar()
    if stat_period == StatisticsPeriod.ALL_TIME:
        return stat_period, None

    parsed_target_date = _parse_iso_date(target_date)
    if parsed_target_date is not None:
        resolved_target_date = parsed_target_date
    elif latest_transaction_date is not None:
        resolved_target_date = latest_transaction_date
    else:
        today = _today()
        if stat_period == StatisticsPeriod.MONTHLY:
            resolved_target_date = today.replace(
                day=calendar.monthrange(today.year, today.month)[1]
            )
        else:
            resolved_target_date = date(today.year, 12, 31)

    if stat_period == StatisticsPeriod.MONTHLY:
        resolved_target_date = resolved_target_date.replace(
            day=calendar.monthrange(
                resolved_target_date.year, resolved_target_date.month
            )[1]
        )
    else:
        resolved_target_date = date(resolved_target_date.year, 12, 31)

    return stat_period, resolved_target_date


def _period_target_from_params(
    db: Session, params: PeriodBreakdownParams
) -> tuple[StatisticsPeriod, date | None]:
    return _resolve_statistics_period_target(
        db,
        period=params.period,
        target_date=params.target_date,
    )


def _resolve_reporting_window_from_params(
    db: Session,
    params: ReportingWindowParams,
) -> tuple[date, date]:
    return ReportingCurrencyAnalyticsService.resolve_reporting_window(
        db,
        start_date=params.start_date,
        end_date=params.end_date,
        time_period=params.time_period,
    )


def _resolve_transfer_window(
    db: Session,
    params: TransferSummaryParams,
) -> tuple[date, date]:
    latest_transaction_date = db.query(
        func.max(Transaction.transaction_date)
    ).scalar()
    end = _parse_iso_date(params.end_date, field_name="end date")
    end = end or latest_transaction_date or _today()
    start = _parse_iso_date(params.start_date, field_name="start date")
    start = start or end.replace(day=1)

    if start > end:
        _raise_http_error(status_code=400, detail="Start date must be before end date")
    return start, end


def _weekday_transactions(
    db: Session,
    params: WeekdayDistributionParams,
) -> list[WeekdayDistributionRow]:
    query = db.query(
        extract("dow", Transaction.transaction_date).label("weekday"),
        Transaction.amount,
        Transaction.transaction_type,
    )
    start = _parse_iso_date(params.start_date, field_name="start date")
    end = _parse_iso_date(params.end_date, field_name="end date")
    if start is not None:
        query = query.filter(Transaction.transaction_date >= start)
    if end is not None:
        query = query.filter(Transaction.transaction_date <= end)
    if params.transaction_type in (TransactionType.EXPENSE, TransactionType.INCOME):
        query = query.filter(Transaction.transaction_type == params.transaction_type)
    return cast("list[WeekdayDistributionRow]", query.all())


def _empty_weekday_buckets() -> dict[str, dict[str, WeekdayBucket]]:
    return {
        day: {"expense": WeekdayBucket(), "income": WeekdayBucket()}
        for day in WEEKDAY_NAMES
    }


def _weekday_distribution_payload(
    transactions: list[WeekdayDistributionRow],
) -> dict[str, dict[str, dict[str, float | int]]]:
    results = _empty_weekday_buckets()
    for transaction in transactions:
        weekday_idx = (int(transaction.weekday) + 6) % 7
        weekday = WEEKDAY_NAMES[weekday_idx]
        transaction_key = (
            "expense"
            if transaction.transaction_type == TransactionType.EXPENSE
            else "income"
        )
        results[weekday][transaction_key].record(abs(transaction.amount))

    return {
        day: {
            "expense": buckets["expense"].as_payload(),
            "income": buckets["income"].as_payload(),
        }
        for day, buckets in results.items()
    }


@router.get("/by-expense-type", response_model=ExpenseTypeStatisticsResponse)
def get_expense_type_statistics(
    params: PeriodBreakdownDependency,
    db: DbSession,
    reporting_currency: ReportingCurrency,
) -> dict[str, object]:
    """Get statistics aggregated by expense type (essential vs discretionary)."""
    try:
        stat_period, target_date = _period_target_from_params(db, params)
        service = ReportingCurrencyAnalyticsService(db)
        response = service.build_expense_type_breakdown(
            period=stat_period,
            target_date=target_date,
            reporting_currency=reporting_currency,
        )
    except HTTPException:
        raise
    except STATISTICS_ROUTER_ERRORS as exc:
        _raise_server_error("Error in get_expense_type_statistics", exc)
    return response


@router.get("/by-category", response_model=CategoryStatisticsListResponse)
def get_category_statistics(
    params: PeriodBreakdownDependency,
    db: DbSession,
    reporting_currency: ReportingCurrency,
) -> dict[str, object]:
    """Return category statistics."""
    try:
        stat_period, target_date = _period_target_from_params(db, params)
        service = ReportingCurrencyAnalyticsService(db)
        response = service.build_category_breakdown(
            period=stat_period,
            target_date=target_date,
            reporting_currency=reporting_currency,
        )
    except HTTPException:
        raise
    except STATISTICS_ROUTER_ERRORS as exc:
        _raise_server_error("Error in get_category_statistics", exc)
    return response


@router.get("/overview", response_model=StatisticsOverviewResponse)
def get_statistics_overview(
    db: DbSession,
    reporting_currency: ReportingCurrency,
) -> dict[str, object]:
    """Return statistics overview."""
    try:
        service = ReportingCurrencyAnalyticsService(db)
        response = service.build_overview(reporting_currency=reporting_currency)
    except HTTPException:
        raise
    except STATISTICS_ROUTER_ERRORS as exc:
        _raise_server_error("Error in get_statistics_overview", exc)
    return response


@router.get("/transfers/summary", response_model=TransferSummaryResponse)
def get_transfer_summary(
    params: TransferSummaryDependency,
    db: DbSession,
    reporting_currency: ReportingCurrency,
) -> dict[str, object]:
    """Return transfer summary."""
    try:
        start, end = _resolve_transfer_window(db, params)
        service = ReportingCurrencyAnalyticsService(db)
        response = service.build_transfer_summary(
            start=start,
            end=end,
            reporting_currency=reporting_currency,
        )
    except HTTPException:
        raise
    except STATISTICS_ROUTER_ERRORS as exc:
        _raise_server_error("Error in get_transfer_summary", exc)
    return response


@router.post("/initialize")
def initialize_statistics(db: DbSession) -> dict[str, str]:
    """Initialize statistics."""
    try:
        StatisticsService.initialize_statistics(db)
        StatisticsService.initialize_category_statistics(db)
        response = {"message": "Statistics initialized successfully"}
    except STATISTICS_ROUTER_ERRORS as exc:
        _raise_server_error("Error initializing statistics", exc)
    return response


@router.get("/weekday-distribution")
def get_weekday_distribution(
    params: WeekdayDistributionDependency,
    db: DbSession,
) -> dict[str, object]:
    """Return weekday distribution."""
    try:
        response: dict[str, object]
        transactions = _weekday_transactions(db, params)

        if not transactions:
            response = {
                "weekdays": [],
                "message": "No transactions found for the specified criteria",
            }
        else:
            response = {
                "weekdays": _weekday_distribution_payload(transactions),
                "transaction_count": len(transactions),
            }
    except HTTPException:
        raise
    except STATISTICS_ROUTER_ERRORS as exc:
        _raise_server_error("Error in get_weekday_distribution", exc)
    return response


@router.get("/timeseries", response_model=FinancialStatisticsTimeseriesResponse)
def get_statistics_timeseries(
    params: ReportingWindowDependency,
    db: DbSession,
    reporting_currency: ReportingCurrency,
) -> dict[str, object]:
    """Return statistics timeseries."""
    try:
        start, end = _resolve_reporting_window_from_params(db, params)
        service = ReportingCurrencyAnalyticsService(db)
        response = service.build_financial_timeseries(
            start=start,
            end=end,
            reporting_currency=reporting_currency,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except STATISTICS_ROUTER_ERRORS as exc:
        _raise_server_error("Error in get_statistics_timeseries", exc)
    return response


@router.get("/category/averages", response_model=CategoryAveragesResponse)
def get_category_averages(
    params: CategoryAveragesDependency,
    db: DbSession,
    reporting_currency: ReportingCurrency,
) -> dict[str, object]:
    """Return category averages."""
    try:
        start, end = _resolve_reporting_window_from_params(db, params)
        service = ReportingCurrencyAnalyticsService(db)
        response = service.build_category_averages(
            start=start,
            end=end,
            reporting_currency=reporting_currency,
            transaction_type=params.transaction_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except STATISTICS_ROUTER_ERRORS as exc:
        _raise_server_error("Error calculating category averages", exc)
    return response


@router.get("/category/timeseries", response_model=CategoryTimeseriesResponse)
def get_category_statistics_timeseries(
    params: CategoryTimeseriesDependency,
    db: DbSession,
    reporting_currency: ReportingCurrency,
) -> dict[str, object]:
    """Return category statistics timeseries."""
    try:
        start, end = _resolve_reporting_window_from_params(db, params)
        service = ReportingCurrencyAnalyticsService(db)
        response = service.build_category_timeseries(
            start=start,
            end=end,
            reporting_currency=reporting_currency,
            transaction_type=params.transaction_type,
            category_name=params.category_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except STATISTICS_ROUTER_ERRORS as exc:
        _raise_server_error("Error in get_category_statistics_timeseries", exc)
    return response


@router.get("/expense-type/timeseries", response_model=ExpenseTypeTimeseriesResponse)
def get_expense_type_statistics_timeseries(
    params: ExpenseTypeTimeseriesDependency,
    db: DbSession,
    reporting_currency: ReportingCurrency,
) -> dict[str, object]:
    """Return expense type statistics timeseries."""
    try:
        start, end = _resolve_reporting_window_from_params(db, params)
        service = ReportingCurrencyAnalyticsService(db)
        response = service.build_expense_type_timeseries(
            start=start,
            end=end,
            reporting_currency=reporting_currency,
            expense_type=params.expense_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except STATISTICS_ROUTER_ERRORS as exc:
        _raise_server_error("Error in get_expense_type_statistics_timeseries", exc)
    return response
