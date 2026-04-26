"""Module for backend app routers anomalies."""

import calendar
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, NoReturn

from dateutil.relativedelta import relativedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import asc, desc, func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Query as OrmQuery
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.anomaly import (
    AnomalyRule,
    AnomalySeverity,
    AnomalyStatus,
    AnomalyType,
    TransactionAnomaly,
)
from ..models.transaction import Transaction
from ..schemas import anomaly as schemas
from ..services.anomaly_detection_service import AnomalyDetectionService

logger: Any = logging.getLogger(__name__)

router: Any = APIRouter(prefix="/anomalies", tags=["anomalies"])
type DbSession = Annotated[Session, Depends(get_db)]
type AnomalyQuery = Annotated["AnomalyQueryParams", Depends()]

ANOMALY_ROUTER_ERRORS: tuple[type[Exception], ...] = (
    RuntimeError,
    SQLAlchemyError,
    TypeError,
    ValueError,
)
ANOMALY_SORT_COLUMNS: dict[str, Any] = {
    "detection_timestamp": TransactionAnomaly.detection_timestamp,
    "anomaly_score": TransactionAnomaly.anomaly_score,
    "severity": TransactionAnomaly.severity,
}


@dataclass(frozen=True)
class AnomalyQueryParams:
    """Group anomaly listing query parameters."""

    page: Annotated[int, Query(1, gt=0)] = 1
    page_size: Annotated[int, Query(20, gt=0, le=100)] = 20
    status: Annotated[str | None, Query(None)] = None
    severity: Annotated[str | None, Query(None)] = None
    anomaly_type: Annotated[str | None, Query(None)] = None
    sort_by: Annotated[
        str,
        Query(
            "detection_timestamp",
            pattern="^(detection_timestamp|anomaly_score|severity)$",
        ),
    ] = "detection_timestamp"
    sort_direction: Annotated[str, Query("desc", pattern="^(asc|desc)$")] = "desc"


def _today() -> date:
    return datetime.now(UTC).date()


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _month_end(value: date) -> date:
    return value.replace(day=calendar.monthrange(value.year, value.month)[1])


def _raise_http_error(status_code: int, detail: str) -> NoReturn:
    raise HTTPException(status_code=status_code, detail=detail)


def _raise_server_error(message: str, exc: Exception) -> NoReturn:
    logger.exception(message)
    raise HTTPException(status_code=500, detail=str(exc)) from exc


def _require_anomaly(db: Session, anomaly_id: int) -> TransactionAnomaly:
    anomaly = (
        db.query(TransactionAnomaly).filter(TransactionAnomaly.id == anomaly_id).first()
    )
    if anomaly is None:
        _raise_http_error(status_code=404, detail="Anomaly not found")
    return anomaly


def _require_rule(db: Session, rule_id: int) -> AnomalyRule:
    rule = db.query(AnomalyRule).filter(AnomalyRule.id == rule_id).first()
    if rule is None:
        _raise_http_error(status_code=404, detail="Rule not found")
    return rule


def _parse_status_filter(value: str | None) -> AnomalyStatus | None:
    if not value or not value.strip():
        return None
    try:
        return AnomalyStatus(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status value: {value}",
        ) from exc


def _parse_severity_filter(value: str | None) -> AnomalySeverity | None:
    if not value or not value.strip():
        return None
    try:
        return AnomalySeverity(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid severity value: {value}",
        ) from exc


def _parse_type_filter(value: str | None) -> AnomalyType | None:
    if not value or not value.strip():
        return None
    try:
        return AnomalyType(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid anomaly_type value: {value}",
        ) from exc


def _resolve_detection_window(
    db: Session,
    request: schemas.AnomalyDetectionRequest,
) -> tuple[date, date]:
    start = request.start_date
    end = request.end_date
    latest_transaction = db.query(func.max(Transaction.transaction_date)).scalar()
    reference_date = _month_end(latest_transaction or _today())

    if end is None:
        end = reference_date

    if start is None:
        start = _month_end(reference_date - relativedelta(months=1)) + timedelta(
            days=1
        )
    return start, end


def _apply_anomaly_filters(
    query: OrmQuery[TransactionAnomaly],
    params: AnomalyQueryParams,
) -> OrmQuery[TransactionAnomaly]:
    status = _parse_status_filter(params.status)
    severity = _parse_severity_filter(params.severity)
    anomaly_type = _parse_type_filter(params.anomaly_type)

    if status is not None:
        query = query.filter(TransactionAnomaly.status == status)
    if severity is not None:
        query = query.filter(TransactionAnomaly.severity == severity)
    if anomaly_type is not None:
        query = query.filter(TransactionAnomaly.anomaly_type == anomaly_type)
    return query


def _serialize_anomaly(anomaly: TransactionAnomaly) -> dict[str, Any]:
    return {
        "id": anomaly.id,
        "transaction_id": anomaly.transaction_id,
        "anomaly_type": anomaly.anomaly_type,
        "severity": anomaly.severity,
        "status": anomaly.status,
        "anomaly_score": anomaly.anomaly_score,
        "confidence": anomaly.confidence,
        "detection_method": anomaly.detection_method,
        "detection_timestamp": anomaly.detection_timestamp,
        "reason": anomaly.reason,
        "details": anomaly.details,
        "expected_value": anomaly.expected_value,
        "actual_value": anomaly.actual_value,
        "deviation_magnitude": anomaly.deviation_magnitude,
        "reviewed_at": anomaly.reviewed_at,
        "reviewed_by": anomaly.reviewed_by,
        "review_notes": anomaly.review_notes,
        "transaction": {
            "id": anomaly.transaction.id,
            "account_number": anomaly.transaction.account_number,
            "transaction_date": anomaly.transaction.transaction_date,
            "amount": anomaly.transaction.amount,
            "currency": anomaly.transaction.currency,
            "description": anomaly.transaction.description,
            "counterparty_name": anomaly.transaction.counterparty_name,
            "counterparty_account": anomaly.transaction.counterparty_account,
            "transaction_type": anomaly.transaction.transaction_type,
            "expense_category": anomaly.transaction.expense_category,
            "income_category": anomaly.transaction.income_category,
            "source_bank": anomaly.transaction.source_bank,
        },
    }


@router.post("/detect", response_model=schemas.AnomalyDetectionResult)
def detect_anomalies(
    request: schemas.AnomalyDetectionRequest,
    db: DbSession,
) -> dict[str, Any]:
    """Run anomaly detection on transactions."""
    try:
        start, end = _resolve_detection_window(db, request)
        result = AnomalyDetectionService.detect_anomalies(
            db=db,
            transaction_ids=request.transaction_ids,
            start_date=start,
            end_date=end,
            force_redetection=request.force_redetection,
        )
    except ANOMALY_ROUTER_ERRORS as exc:
        _raise_server_error("Error detecting anomalies", exc)
    return result


@router.get("/", response_model=schemas.AnomalyPage)
def get_anomalies(
    params: AnomalyQuery,
    db: DbSession,
) -> dict[str, Any]:
    """Get paginated list of anomalies with filters."""
    try:
        query = db.query(TransactionAnomaly).join(Transaction)
        query = _apply_anomaly_filters(query, params)

        # Apply sorting
        sort_column = ANOMALY_SORT_COLUMNS[params.sort_by]
        if params.sort_direction == "asc":
            query = query.order_by(asc(sort_column))
        else:
            query = query.order_by(desc(sort_column))

        # Get total count
        total_count = query.count()

        # Apply pagination
        offset = (params.page - 1) * params.page_size
        anomalies = query.offset(offset).limit(params.page_size).all()

        # Enrich with transaction data
        enriched_anomalies = [_serialize_anomaly(anomaly) for anomaly in anomalies]
        page = {
            "items": enriched_anomalies,
            "total": total_count,
            "page": params.page,
            "page_size": params.page_size,
            "total_pages": (total_count + params.page_size - 1) // params.page_size,
        }
    except HTTPException:
        raise
    except ANOMALY_ROUTER_ERRORS as exc:
        _raise_server_error("Error fetching anomalies", exc)
    return page


@router.get("/statistics", response_model=schemas.AnomalyStatistics)
def get_anomaly_statistics(db: DbSession) -> dict[str, Any]:
    """Get anomaly detection statistics."""
    try:
        statistics = AnomalyDetectionService.get_anomaly_statistics(db)
    except ANOMALY_ROUTER_ERRORS as exc:
        _raise_server_error("Error fetching anomaly statistics", exc)
    return statistics


@router.patch("/{anomaly_id}/status", response_model=schemas.Anomaly)
def update_anomaly_status(
    anomaly_id: int,
    update_data: schemas.AnomalyUpdate,
    db: DbSession,
) -> TransactionAnomaly:
    """Update anomaly review status."""
    try:
        if not update_data.status:
            _raise_http_error(status_code=400, detail="Status is required")

        anomaly = AnomalyDetectionService.update_anomaly_status(
            db=db,
            anomaly_id=anomaly_id,
            status=update_data.status,
            review_notes=update_data.review_notes,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RuntimeError, SQLAlchemyError, TypeError) as exc:
        _raise_server_error("Error updating anomaly status", exc)
    return anomaly


@router.get("/{anomaly_id}", response_model=schemas.AnomalyWithTransaction)
def get_anomaly_detail(anomaly_id: int, db: DbSession) -> dict[str, Any]:
    """Get detailed information about a specific anomaly."""
    try:
        anomaly_detail = _serialize_anomaly(_require_anomaly(db, anomaly_id))
    except HTTPException:
        raise
    except ANOMALY_ROUTER_ERRORS as exc:
        _raise_server_error("Error fetching anomaly detail", exc)
    return anomaly_detail


@router.delete("/{anomaly_id}")
def delete_anomaly(anomaly_id: int, db: DbSession) -> dict[str, str]:
    """Delete an anomaly (mark as false positive)."""
    try:
        anomaly = _require_anomaly(db, anomaly_id)

        # Mark as false positive instead of deleting
        anomaly.status = AnomalyStatus.FALSE_POSITIVE
        anomaly.reviewed_at = _utcnow()

        db.commit()
        result = {"message": "Anomaly marked as false positive"}
    except HTTPException:
        raise
    except ANOMALY_ROUTER_ERRORS as exc:
        _raise_server_error("Error deleting anomaly", exc)
    return result


# Anomaly Rules endpoints
@router.get("/rules/", response_model=list[schemas.AnomalyRule])
def get_anomaly_rules(db: DbSession) -> list[AnomalyRule]:
    """Get all anomaly detection rules."""
    try:
        rules = db.query(AnomalyRule).filter(AnomalyRule.is_active).all()
    except ANOMALY_ROUTER_ERRORS as exc:
        _raise_server_error("Error fetching anomaly rules", exc)
    return rules


@router.post("/rules/", response_model=schemas.AnomalyRule)
def create_anomaly_rule(
    rule_data: schemas.AnomalyRuleCreate,
    db: DbSession,
) -> AnomalyRule:
    """Create a new anomaly detection rule."""
    try:
        rule = AnomalyRule(**rule_data.model_dump())
        db.add(rule)
        db.commit()
        db.refresh(rule)
    except ANOMALY_ROUTER_ERRORS as exc:
        _raise_server_error("Error creating anomaly rule", exc)
    return rule


@router.patch("/rules/{rule_id}", response_model=schemas.AnomalyRule)
def update_anomaly_rule(
    rule_id: int,
    rule_data: schemas.AnomalyRuleUpdate,
    db: DbSession,
) -> AnomalyRule:
    """Update an anomaly detection rule."""
    try:
        rule = _require_rule(db, rule_id)

        update_data = rule_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(rule, field, value)

        rule.updated_at = _utcnow()
        db.commit()
        db.refresh(rule)
    except HTTPException:
        raise
    except ANOMALY_ROUTER_ERRORS as exc:
        _raise_server_error("Error updating anomaly rule", exc)
    return rule


@router.delete("/rules/{rule_id}")
def delete_anomaly_rule(rule_id: int, db: DbSession) -> dict[str, str]:
    """Delete an anomaly detection rule."""
    try:
        rule = _require_rule(db, rule_id)

        rule.is_active = False
        rule.updated_at = _utcnow()
        db.commit()
        result = {"message": "Rule deactivated successfully"}
    except HTTPException:
        raise
    except ANOMALY_ROUTER_ERRORS as exc:
        _raise_server_error("Error deleting anomaly rule", exc)
    return result
