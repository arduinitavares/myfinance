import logging

from sqlalchemy.orm import Session

from ..models.transaction import ExpenseCategory, IncomeCategory, Transaction, TransactionType
from ..routers.suggestions import category_suggestion_service
from .statistics_service import StatisticsService


logger = logging.getLogger(__name__)


def commit_category_change(
    *,
    db: Session,
    transaction: Transaction,
    transaction_type: TransactionType,
    category: str,
    classification_source: str | None,
    recurrence_pattern_id: int | None,
) -> Transaction:
    transaction.transaction_type = transaction_type
    transaction.classification_source = classification_source
    transaction.recurrence_pattern_id = recurrence_pattern_id

    if transaction_type == TransactionType.EXPENSE:
        transaction.expense_category = ExpenseCategory(category)
        transaction.income_category = None
    elif transaction_type == TransactionType.INCOME:
        transaction.income_category = IncomeCategory(category)
        transaction.expense_category = None
    else:
        if transaction.amount < 0:
            transaction.expense_category = ExpenseCategory.INTERNAL_TRANSFER
            transaction.income_category = None
        else:
            transaction.income_category = IncomeCategory.INTERNAL_TRANSFER
            transaction.expense_category = None

    db.add(transaction)
    db.flush()
    StatisticsService.update_statistics(db, transaction.transaction_date)
    db.commit()
    db.refresh(transaction)

    if transaction.transaction_type in {TransactionType.EXPENSE, TransactionType.INCOME}:
        try:
            category_suggestion_service.add_transaction(transaction)
        except Exception as exc:
            logger.warning(
                "Failed to update suggestion index for transaction %s: %s",
                transaction.id,
                exc,
            )

    return transaction
