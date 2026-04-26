"""Module for backend app routers transactions."""

import logging
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Any, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, false, func, or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Query as OrmQuery
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from ..database import get_db
from ..models.anomaly import TransactionAnomaly
from ..models.transaction import (
    ExpenseCategory,
    IncomeCategory,
    Transaction,
    TransactionType,
    TransferCategory,
)
from ..schemas import transaction as schemas
from ..services.anomaly_detection_service import AnomalyDetectionService
from ..services.classification_commit_service import (
    CategoryChangeRequest,
    commit_category_change,
)
from ..services.currency_conversion import CurrencyConversionService
from ..services.reporting_currency import get_reporting_currency
from ..services.statistics_service import StatisticsService

# Set up logging
logger: Any = logging.getLogger(__name__)

# Create router
router: Any = APIRouter(prefix="/transactions", tags=["transactions"])
DbSession: object = Annotated[Session, Depends(get_db)]
ReportingCurrency: object = Annotated[str, Depends(get_reporting_currency)]
CategoryQuery: object = Annotated[str, Query(...)]
TransactionTypeQuery: object = Annotated[TransactionType, Query(...)]

# Define sort field mapping
SORT_FIELD_MAPPING: dict[str, str] = {
    "date": "transaction_date",
    "description": "description",
    "amount": "amount",
    "type": "transaction_type",
}
TRANSACTION_ROUTER_ERRORS: tuple[type[Exception], ...] = (
    RuntimeError,
    SQLAlchemyError,
    TypeError,
    ValueError,
)


@dataclass(frozen=True)
class TransactionListParams:
    """Query parameters for transaction listing."""

    page: Annotated[int, Query(gt=0)] = 1
    page_size: Annotated[int, Query(gt=0, le=100)] = 10
    sort_field: Annotated[
        str,
        Query(pattern="^(date|description|amount|type)$"),
    ] = "date"
    sort_direction: Annotated[str, Query(pattern="^(asc|desc)$")] = "desc"
    search: Annotated[
        str | None,
        Query(description="Search term for description/counterparty"),
    ] = None
    category: Annotated[
        str | None,
        Query(description="Category filter (expense or income)"),
    ] = None
    classification_status: Annotated[
        str,
        Query(pattern="^(all|classified|unclassified)$"),
    ] = "all"
    start_date: Annotated[
        str | None,
        Query(description="Start date (YYYY-MM-DD)"),
    ] = None
    end_date: Annotated[
        str | None,
        Query(description="End date (YYYY-MM-DD)"),
    ] = None


TransactionListDependency: object = Annotated[TransactionListParams, Depends()]


def _raise_http_error(status_code: int, detail: str) -> NoReturn:
    raise HTTPException(status_code=status_code, detail=detail)


def _raise_server_error(message: str, exc: Exception) -> NoReturn:
    logger.exception(message)
    raise HTTPException(status_code=500, detail=str(exc)) from exc


def _parse_iso_date(value: str | None, *, field_name: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {field_name} format. Use YYYY-MM-DD",
        ) from exc


def _require_transaction(db: Session, transaction_id: int) -> Transaction:
    transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if transaction is None:
        _raise_http_error(status_code=404, detail="Transaction not found")
    return transaction


def _serialize_transaction_for_response(
    transaction: Transaction,
    *,
    conversion_service: CurrencyConversionService,
    reporting_currency: str,
) -> dict[str, object]:
    return schemas.build_transaction_response_payload_for_reporting_currency(
        transaction,
        conversion_service=conversion_service,
        reporting_currency=reporting_currency,
    )


def _enum_category_filters(category: str) -> list[ColumnElement[bool]]:
    filters: list[ColumnElement[bool]] = []
    try:
        expense_enum = ExpenseCategory(category)
    except ValueError:
        expense_enum = None
    try:
        income_enum = IncomeCategory(category)
    except ValueError:
        income_enum = None
    try:
        transfer_enum = TransferCategory(category)
    except ValueError:
        transfer_enum = None

    if expense_enum is not None:
        filters.append(Transaction.expense_category == expense_enum)
    if income_enum is not None:
        filters.append(Transaction.income_category == income_enum)
    if transfer_enum is not None:
        filters.append(Transaction.transfer_category == transfer_enum)
    return filters


def _apply_search_filter(
    query: OrmQuery[Transaction],
    search: str | None,
) -> OrmQuery[Transaction]:
    if not search:
        return query

    ilike_str = f"%{search.lower()}%"
    return query.filter(
        or_(
            func.lower(Transaction.description).ilike(ilike_str),
            func.lower(Transaction.counterparty_name).ilike(ilike_str),
        )
    )


def _apply_category_filter(
    query: OrmQuery[Transaction],
    category: str | None,
) -> OrmQuery[Transaction]:
    if not category or category == "all":
        return query

    filters = _enum_category_filters(category)
    if not filters:
        return query.filter(false())
    if len(filters) == 1:
        return query.filter(filters[0])
    return query.filter(or_(*filters))


def _apply_date_filters(
    query: OrmQuery[Transaction],
    params: TransactionListParams,
) -> OrmQuery[Transaction]:
    start = _parse_iso_date(params.start_date, field_name="start date")
    end = _parse_iso_date(params.end_date, field_name="end date")
    if start is not None:
        query = query.filter(Transaction.transaction_date >= start)
    if end is not None:
        query = query.filter(Transaction.transaction_date <= end)
    return query


def _apply_classification_filter(
    query: OrmQuery[Transaction],
    classification_status: str,
) -> OrmQuery[Transaction]:
    classified_filter = or_(
        and_(
            Transaction.transaction_type == TransactionType.EXPENSE,
            Transaction.expense_category.isnot(None),
        ),
        and_(
            Transaction.transaction_type == TransactionType.INCOME,
            Transaction.income_category.isnot(None),
        ),
        and_(
            Transaction.transaction_type == TransactionType.TRANSFER,
            Transaction.transfer_category.isnot(None),
        ),
    )
    unclassified_filter = or_(
        and_(
            Transaction.transaction_type == TransactionType.EXPENSE,
            Transaction.expense_category.is_(None),
        ),
        and_(
            Transaction.transaction_type == TransactionType.INCOME,
            Transaction.income_category.is_(None),
        ),
        and_(
            Transaction.transaction_type == TransactionType.TRANSFER,
            Transaction.transfer_category.is_(None),
        ),
    )

    if classification_status == "classified":
        return query.filter(classified_filter)
    if classification_status == "unclassified":
        return query.filter(unclassified_filter)
    return query


def _apply_sorting(
    query: OrmQuery[Transaction],
    params: TransactionListParams,
) -> OrmQuery[Transaction]:
    db_sort_field = SORT_FIELD_MAPPING.get(params.sort_field, "transaction_date")
    sort_attribute = getattr(Transaction, db_sort_field)
    sort_column = (
        sort_attribute.asc()
        if params.sort_direction == "asc"
        else sort_attribute.desc()
    )
    return query.order_by(sort_column)


def _build_transaction_query(
    db: Session,
    params: TransactionListParams,
) -> OrmQuery[Transaction]:
    query = db.query(Transaction)
    query = _apply_search_filter(query, params.search)
    query = _apply_category_filter(query, params.category)
    query = _apply_date_filters(query, params)
    query = _apply_classification_filter(query, params.classification_status)
    return _apply_sorting(query, params)


def _transaction_page_payload(
    *,
    db: Session,
    query: OrmQuery[Transaction],
    params: TransactionListParams,
    reporting_currency: str,
) -> dict[str, object]:
    total_count = query.count()
    offset = (params.page - 1) * params.page_size
    transactions = query.offset(offset).limit(params.page_size).all()
    conversion_service = CurrencyConversionService(db)
    serialized_transactions = [
        _serialize_transaction_for_response(
            transaction,
            conversion_service=conversion_service,
            reporting_currency=reporting_currency,
        )
        for transaction in transactions
    ]

    return {
        "items": serialized_transactions,
        "total": total_count,
        "page": params.page,
        "page_size": params.page_size,
        "total_pages": (total_count + params.page_size - 1) // params.page_size,
    }


@router.get("/", response_model=schemas.TransactionPage)
def get_transactions(
    params: TransactionListDependency,
    db: DbSession,
    reporting_currency: ReportingCurrency,
) -> dict[str, object]:
    """Return transactions."""
    try:
        query = _build_transaction_query(db, params)
        response = _transaction_page_payload(
            db=db,
            query=query,
            params=params,
            reporting_currency=reporting_currency,
        )
    except HTTPException:
        raise
    except TRANSACTION_ROUTER_ERRORS as exc:
        _raise_server_error("Error fetching transactions", exc)
    return response


@router.delete("/{transaction_id}")
async def delete_transaction(transaction_id: int, db: DbSession) -> dict[str, str]:
    """Delete transaction."""
    transaction = _require_transaction(db, transaction_id)

    transaction_date = transaction.transaction_date
    seeded_pattern_ids = [
        pattern.id for pattern in transaction.seeded_recurrence_patterns
    ]

    if seeded_pattern_ids:
        (
            db.query(Transaction)
            .filter(Transaction.recurrence_pattern_id.in_(seeded_pattern_ids))
            .update(
                {Transaction.recurrence_pattern_id: None}, synchronize_session=False
            )
        )

    # Delete associated anomaly records first to avoid foreign key constraint violation
    db.query(TransactionAnomaly).filter(
        TransactionAnomaly.transaction_id == transaction_id
    ).delete()

    for pattern in list(transaction.seeded_recurrence_patterns):
        db.delete(pattern)

    for session in list(transaction.classification_sessions):
        db.delete(session)

    # Delete the transaction
    db.delete(transaction)

    # Commit deletion before updating statistics
    db.commit()

    # Update statistics for the affected period
    StatisticsService.update_statistics(db, transaction_date)

    return {"message": "Transaction deleted successfully"}


@router.patch("/{transaction_id}/category")
def update_transaction_category(
    transaction_id: int,
    category: CategoryQuery,
    transaction_type: TransactionTypeQuery,
    db: DbSession,
    reporting_currency: ReportingCurrency,
) -> dict[str, object]:
    """Update transaction category."""
    transaction = _require_transaction(db, transaction_id)

    try:
        updated_transaction = commit_category_change(
            db=db,
            transaction=transaction,
            change=CategoryChangeRequest(
                transaction_type=transaction_type,
                category=category,
                classification_source="manual",
                recurrence_pattern_id=transaction.recurrence_pattern_id,
            ),
        )
        conversion_service = CurrencyConversionService(db)
        return _serialize_transaction_for_response(
            updated_transaction,
            conversion_service=conversion_service,
            reporting_currency=reporting_currency,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/restore", response_model=schemas.Transaction)
def restore_transaction(
    transaction_data: schemas.TransactionRestore,
    db: DbSession,
    reporting_currency: ReportingCurrency,
) -> dict[str, object]:
    """Handle restore transaction."""
    try:
        # Create a new transaction with the provided data
        # The ID will be auto-generated, which is fine for our purpose
        new_transaction = Transaction(**transaction_data.model_dump(exclude={"id"}))
        db.add(new_transaction)
        db.commit()
        db.refresh(new_transaction)

        # Update statistics for the affected period
        StatisticsService.update_statistics(db, new_transaction.transaction_date)

        # Run anomaly detection on restored transaction
        try:
            AnomalyDetectionService.detect_anomalies(
                db=db, transaction_ids=[new_transaction.id], force_redetection=False
            )
        except TRANSACTION_ROUTER_ERRORS:
            logger.warning(
                "Anomaly detection failed for restored transaction",
                exc_info=True,
            )

        conversion_service = CurrencyConversionService(db)
        response = _serialize_transaction_for_response(
            new_transaction,
            conversion_service=conversion_service,
            reporting_currency=reporting_currency,
        )

    except TRANSACTION_ROUTER_ERRORS as exc:
        logger.exception("Error restoring transaction")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return response
