"""Module for backend app services classification_commit_service."""

import logging
from dataclasses import dataclass

from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
from sqlalchemy.orm import Session

from ..models.classification import RecurrencePattern
from ..models.transaction import (
    ExpenseCategory,
    IncomeCategory,
    Transaction,
    TransactionType,
    TransferCategory,
)
from ..routers.suggestions import category_suggestion_service
from .statistics_service import StatisticsService

logger: logging.Logger = logging.getLogger(__name__)

SUGGESTION_INDEX_ERRORS: tuple[type[Exception], ...] = (
    ResponseHandlingException,
    UnexpectedResponse,
    RuntimeError,
    ValueError,
)


@dataclass(frozen=True)
class CategoryChangeRequest:
    """Represent a requested transaction category change."""

    transaction_type: TransactionType
    category: str
    classification_source: str | None
    recurrence_pattern_id: int | None


def normalized_category_for(
    *,
    transaction_type: TransactionType,
    category: str,
) -> str:
    """Handle normalized category for."""
    if transaction_type == TransactionType.TRANSFER:
        return TransferCategory(category).value
    return category


def commit_category_change(
    *,
    db: Session,
    transaction: Transaction,
    change: CategoryChangeRequest,
    commit: bool = True,
) -> Transaction:
    """Handle commit category change."""
    normalized_category = normalized_category_for(
        transaction_type=change.transaction_type,
        category=change.category,
    )

    if (
        change.classification_source == "manual"
        and change.recurrence_pattern_id is not None
        and transaction.recurrence_pattern_id == change.recurrence_pattern_id
    ):
        recurrence_pattern = (
            db.query(RecurrencePattern)
            .filter(
                RecurrencePattern.id == change.recurrence_pattern_id,
                RecurrencePattern.active.is_(True),
            )
            .first()
        )
        if recurrence_pattern and recurrence_pattern.category != normalized_category:
            logger.warning(
                "Manual category %s contradicts active recurrence pattern %s for "
                "transaction %s; keeping pattern active",
                normalized_category,
                change.recurrence_pattern_id,
                transaction.id,
            )

    transaction.transaction_type = change.transaction_type
    transaction.classification_source = change.classification_source
    transaction.recurrence_pattern_id = change.recurrence_pattern_id

    if change.transaction_type == TransactionType.EXPENSE:
        transaction.expense_category = ExpenseCategory(normalized_category)
        transaction.income_category = None
        transaction.transfer_category = None
    elif change.transaction_type == TransactionType.INCOME:
        transaction.income_category = IncomeCategory(normalized_category)
        transaction.expense_category = None
        transaction.transfer_category = None
    else:
        transaction.transfer_category = TransferCategory(normalized_category)
        transaction.expense_category = None
        transaction.income_category = None

    db.add(transaction)
    db.flush()
    if commit:
        StatisticsService.update_statistics(db, transaction.transaction_date)
        db.commit()
        db.refresh(transaction)

        try:
            category_suggestion_service.sync_transaction(transaction)
        except SUGGESTION_INDEX_ERRORS as exc:
            logger.warning(
                "Failed to update suggestion index for transaction %s: %s",
                transaction.id,
                exc,
            )

    return transaction
