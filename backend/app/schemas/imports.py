"""Module for backend app schemas imports."""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.imports import ImportTransactionDraft

from ..services.currency_conversion import DisplayMoney
from .transaction import serialize_display_money


class ImportSessionResponse(BaseModel):
    """Represent import session response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    file_name: str
    mime_type: str
    status: str
    strategy_key: str | None = None
    provider_hint: str | None = None
    language_hint: str | None = None
    charset_hint: str | None = None
    extractor_id: str | None = None
    raw_artifact_ref: str | None = None
    error_stage: str | None = None
    error_message: str | None = None
    attempt_count: int = 0
    created_at: datetime
    updated_at: datetime


class ImportStatementDraftResponse(BaseModel):
    """Represent import statement draft response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    attempt_number: int
    statement_period_start: date | None = None
    statement_period_end: date | None = None
    transaction_count: int | None = None
    account_number_hint: str | None = None
    card_number_hint: str | None = None
    currency: str | None = None
    overall_confidence: float
    review_status: str


class ImportTransactionDraftResponse(BaseModel):
    """Represent import transaction draft response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    transaction_date: date | None = None
    source_description: str
    canonical_description_en: str | None = None
    signed_amount: float
    currency: str
    debit_credit: str | None = None
    source_locator: str
    inferred_category: str | None = None
    category_source: str | None = None
    proposed_transaction_type: str | None = None
    proposed_expense_category: str | None = None
    proposed_income_category: str | None = None
    proposed_transfer_category: str | None = None
    classification_source: str | None = None
    recurrence_pattern_id: int | None = None
    confidence: float | None = None
    field_confidence: dict[str, float] | None = None
    raw_fields: dict[str, Any] | None = None
    edit_source: str
    display_amount: float | None = None
    display_currency: str | None = None
    display_fx_rate: float | None = None
    display_rate_date: date | None = None
    display_is_available: bool | None = None
    display_unavailable_reason: str | None = None


class ImportIssueResponse(BaseModel):
    """Represent import issue response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    attempt_number: int
    severity: str
    blocking: bool
    issue_code: str
    issue_message: str
    transaction_ref: str | None = None


class ImportReviewResponse(BaseModel):
    """Represent import review response."""

    model_config = ConfigDict(from_attributes=True)

    session: ImportSessionResponse
    statement: ImportStatementDraftResponse | None = None
    transactions: list[ImportTransactionDraftResponse] = Field(default_factory=list)
    issues: list[ImportIssueResponse] = Field(default_factory=list)
    evidence: dict[str, Any] | None = None


class ImportUploadConflictResponse(BaseModel):
    """Represent import upload conflict response."""

    message: str
    file_hash: str
    existing_session: ImportSessionResponse


class ImportBatchItemResponse(BaseModel):
    """Represent import batch item response."""

    id: int
    filename: str
    file_hash: str | None = None
    status: str
    message: str | None = None
    session_id: int | None = None
    session_status: str | None = None
    existing_session_id: int | None = None
    existing_session_status: str | None = None
    strategy_key: str | None = None
    extractor_id: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ImportBatchRunResponse(BaseModel):
    """Represent import batch run response."""

    id: int
    folder_path: str
    status: str
    message: str | None = None
    total_files: int
    processed_count: int
    skipped_existing_count: int
    unsupported_count: int
    failed_count: int
    created_at: datetime
    completed_at: datetime | None = None
    items: list[ImportBatchItemResponse] = Field(default_factory=list)


def build_import_transaction_draft_response_payload(
    transaction_draft: ImportTransactionDraft,
    display_money: DisplayMoney,
) -> dict[str, object]:
    """Build import transaction draft response payload."""
    payload: dict[str, object] = {
        "id": transaction_draft.id,
        "transaction_date": transaction_draft.transaction_date,
        "source_description": transaction_draft.source_description,
        "canonical_description_en": transaction_draft.canonical_description_en,
        "signed_amount": transaction_draft.signed_amount,
        "currency": transaction_draft.currency,
        "debit_credit": transaction_draft.debit_credit,
        "source_locator": transaction_draft.source_locator,
        "inferred_category": transaction_draft.inferred_category,
        "category_source": transaction_draft.category_source,
        "proposed_transaction_type": transaction_draft.proposed_transaction_type,
        "proposed_expense_category": transaction_draft.proposed_expense_category,
        "proposed_income_category": transaction_draft.proposed_income_category,
        "proposed_transfer_category": transaction_draft.proposed_transfer_category,
        "classification_source": transaction_draft.classification_source,
        "recurrence_pattern_id": transaction_draft.recurrence_pattern_id,
        "confidence": transaction_draft.confidence,
        "field_confidence": None,
        "raw_fields": None,
        "edit_source": transaction_draft.edit_source,
    }
    payload.update(serialize_display_money(display_money))
    return payload
