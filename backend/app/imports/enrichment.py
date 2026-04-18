from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy.orm import Session

from app.models.classification import RecurrencePattern
from app.models.imports import ImportTransactionDraft
from app.models.transaction import TransactionType
from app.routers.suggestions import category_suggestion_service
from app.services.classification_session_service import recurrence_pattern_matches_transaction
from app.utils.text_normalization import normalize_for_matching


def effective_transaction_type(draft: ImportTransactionDraft) -> TransactionType:
    if draft.proposed_transaction_type:
        return TransactionType(draft.proposed_transaction_type)
    if draft.proposed_transfer_category:
        return TransactionType.TRANSFER
    if draft.proposed_expense_category:
        return TransactionType.EXPENSE
    if draft.proposed_income_category:
        return TransactionType.INCOME
    return TransactionType.EXPENSE if draft.signed_amount < 0 else TransactionType.INCOME


def find_matching_recurrence_pattern(
    db: Session,
    *,
    draft: ImportTransactionDraft,
    source_bank: str,
) -> RecurrencePattern | None:
    transaction_type = effective_transaction_type(draft)
    transaction_stub = SimpleNamespace(
        description=draft.source_description,
        currency=draft.currency,
        amount=draft.signed_amount,
        source_bank=source_bank,
        transaction_type=transaction_type,
    )
    normalized_description_key = normalize_for_matching(draft.source_description)
    candidates = (
        db.query(RecurrencePattern)
        .filter(
            RecurrencePattern.active.is_(True),
            RecurrencePattern.normalized_description_key == normalized_description_key,
            RecurrencePattern.currency == draft.currency,
        )
        .order_by(RecurrencePattern.id.asc())
        .all()
    )

    def _priority(pattern: RecurrencePattern) -> tuple[int, int]:
        if pattern.source_bank == source_bank:
            return (0, pattern.id)
        return (1, pattern.id)

    for candidate in sorted(candidates, key=_priority):
        if recurrence_pattern_matches_transaction(candidate, transaction_stub):
            return candidate
    return None


def _apply_recurrence_pattern(draft: ImportTransactionDraft, pattern: RecurrencePattern) -> None:
    if draft.proposed_transaction_type is None:
        draft.proposed_transaction_type = pattern.transaction_type.value

    if pattern.transaction_type == TransactionType.EXPENSE and draft.proposed_expense_category is None:
        draft.proposed_expense_category = pattern.category
    elif pattern.transaction_type == TransactionType.INCOME and draft.proposed_income_category is None:
        draft.proposed_income_category = pattern.category
    elif pattern.transaction_type == TransactionType.TRANSFER and draft.proposed_transfer_category is None:
        draft.proposed_transfer_category = pattern.category

    if draft.classification_source is None:
        draft.classification_source = "recurrence_pattern"
    if draft.recurrence_pattern_id is None:
        draft.recurrence_pattern_id = pattern.id


def _apply_upload_suggestions(draft: ImportTransactionDraft) -> None:
    if (
        draft.proposed_expense_category is not None
        or draft.proposed_income_category is not None
        or draft.proposed_transfer_category is not None
    ):
        return

    transaction_type = effective_transaction_type(draft)
    if transaction_type == TransactionType.TRANSFER:
        return

    suggestions = category_suggestion_service.suggest_category(
        draft.source_description,
        draft.signed_amount,
        transaction_type,
    )
    if not suggestions or suggestions[0][1] <= 0.5:
        return

    category, _confidence = suggestions[0]
    if draft.proposed_transaction_type is None:
        draft.proposed_transaction_type = transaction_type.value

    if transaction_type == TransactionType.EXPENSE and draft.proposed_expense_category is None:
        draft.proposed_expense_category = category
    elif transaction_type == TransactionType.INCOME and draft.proposed_income_category is None:
        draft.proposed_income_category = category
    else:
        return

    if draft.classification_source is None:
        draft.classification_source = "upload_suggester"


def enrich_draft_proposals(
    db: Session,
    *,
    draft: ImportTransactionDraft,
    source_bank: str,
) -> None:
    recurrence_pattern = find_matching_recurrence_pattern(db, draft=draft, source_bank=source_bank)
    if recurrence_pattern is not None:
        _apply_recurrence_pattern(draft, recurrence_pattern)
    _apply_upload_suggestions(draft)

