import logging

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


logger = logging.getLogger(__name__)


def normalized_category_for(
    *,
    transaction_type: TransactionType,
    category: str,
    amount: float,
) -> str:
    if transaction_type == TransactionType.TRANSFER:
        return TransferCategory(category).value
    return category


def commit_category_change(
    *,
    db: Session,
    transaction: Transaction,
    transaction_type: TransactionType,
    category: str,
    classification_source: str | None,
    recurrence_pattern_id: int | None,
    commit: bool = True,
) -> Transaction:
    normalized_category = normalized_category_for(
        transaction_type=transaction_type,
        category=category,
        amount=transaction.amount,
    )

    if (
        classification_source == "manual"
        and recurrence_pattern_id is not None
        and transaction.recurrence_pattern_id == recurrence_pattern_id
    ):
        recurrence_pattern = (
            db.query(RecurrencePattern)
            .filter(RecurrencePattern.id == recurrence_pattern_id, RecurrencePattern.active.is_(True))
            .first()
        )
        if recurrence_pattern and recurrence_pattern.category != normalized_category:
            logger.warning(
                "Manual category %s contradicts active recurrence pattern %s for transaction %s; keeping pattern active",
                normalized_category,
                recurrence_pattern_id,
                transaction.id,
            )

    transaction.transaction_type = transaction_type
    transaction.classification_source = classification_source
    transaction.recurrence_pattern_id = recurrence_pattern_id

    if transaction_type == TransactionType.EXPENSE:
        transaction.expense_category = ExpenseCategory(normalized_category)
        transaction.income_category = None
        transaction.transfer_category = None
    elif transaction_type == TransactionType.INCOME:
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
        except Exception as exc:
            logger.warning(
                "Failed to update suggestion index for transaction %s: %s",
                transaction.id,
                exc,
            )

    return transaction
