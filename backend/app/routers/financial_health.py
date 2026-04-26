"""Module for backend app routers financial_health."""

import calendar
import logging
from datetime import UTC, date, datetime
from typing import Annotated, Any, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.financial_health import FinancialHealth, FinancialRecommendation
from ..models.transaction import Transaction
from ..schemas import financial_health as schemas
from ..services.financial_health_service import FinancialHealthService

# Set up logging
logger: Any = logging.getLogger(__name__)

# Create router
router: Any = APIRouter(prefix="/financial-health", tags=["financial-health"])
DbSession: object = Annotated[Session, Depends(get_db)]
TargetDateQuery: object = Annotated[
    str | None,
    Query(description="Target date (YYYY-MM-DD)"),
]
HistoryMonthsQuery: object = Annotated[
    int,
    Query(gt=0, le=60, description="Number of months of history to retrieve"),
]
ActiveOnlyQuery: object = Annotated[
    bool,
    Query(description="Only return active (not completed) recommendations"),
]


def _today() -> date:
    return datetime.now(UTC).date()


def _parse_target_date(target_date: str | None) -> date | None:
    if target_date is None:
        return None
    try:
        return date.fromisoformat(target_date)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid date format. Use YYYY-MM-DD",
        ) from exc


def _resolve_health_score_date(db: Session, target_date: str | None) -> date:
    parsed_date = _parse_target_date(target_date)
    if parsed_date is not None:
        return parsed_date

    latest_transaction = (
        db.query(Transaction).order_by(Transaction.transaction_date.desc()).first()
    )
    if latest_transaction:
        return latest_transaction.transaction_date
    return _today()


def _month_end(value: date) -> date:
    return value.replace(day=calendar.monthrange(value.year, value.month)[1])


def _raise_not_found(detail: str) -> NoReturn:
    raise HTTPException(status_code=404, detail=detail)


@router.get("/score", response_model=schemas.FinancialHealth)
def get_health_score(
    db: DbSession,
    target_date: TargetDateQuery = None,
) -> FinancialHealth:
    """Get the financial health score for a specific date.

    If no date is provided, uses the date from the latest available transaction.
    """
    try:
        date_obj = _resolve_health_score_date(db, target_date)
        health_score = FinancialHealthService.calculate_health_score(db, date_obj)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error calculating financial health score")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return health_score


@router.get("/history", response_model=schemas.FinancialHealthHistory)
def get_health_history(
    db: DbSession,
    months: HistoryMonthsQuery = 12,
) -> dict[str, Any]:
    """Get historical financial health scores for the specified number of months."""
    try:
        history = FinancialHealthService.get_health_history(db, months)
    except Exception as exc:
        logger.exception("Error retrieving financial health history")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return history


@router.get("/recommendations", response_model=list[schemas.Recommendation])
def get_recommendations(
    db: DbSession,
    active_only: ActiveOnlyQuery = True,
) -> list[FinancialRecommendation]:
    """Get personalized financial recommendations."""
    try:
        recommendations = FinancialHealthService.get_recommendations(db, active_only)
    except Exception as exc:
        logger.exception("Error retrieving recommendations")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return recommendations


@router.patch(
    "/recommendations/{recommendation_id}", response_model=schemas.Recommendation
)
def update_recommendation(
    recommendation_id: int,
    update_data: schemas.RecommendationUpdate,
    db: DbSession,
) -> FinancialRecommendation:
    """Update a recommendation's completion status."""
    try:
        updated_recommendation = FinancialHealthService.update_recommendation(
            db, recommendation_id, update_data.is_completed
        )
    except Exception as exc:
        logger.exception("Error updating recommendation")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not updated_recommendation:
        _raise_not_found("Recommendation not found")
    return updated_recommendation


@router.post("/recalculate", response_model=schemas.FinancialHealth)
def recalculate_health_score(
    db: DbSession,
    target_date: TargetDateQuery = None,
) -> FinancialHealth:
    """Force recalculation of the financial health score for a specific date.

    If no date is provided, uses the current month.
    """
    try:
        date_obj = _parse_target_date(target_date) or _today()

        # Delete existing score for the month if it exists
        month_start = date_obj.replace(day=1)
        month_end = _month_end(date_obj)

        db.query(FinancialHealth).filter(
            FinancialHealth.date >= month_start, FinancialHealth.date <= month_end
        ).delete()

        db.commit()

        # Calculate new score
        health_score = FinancialHealthService.calculate_health_score(db, date_obj)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error recalculating financial health score")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return health_score
