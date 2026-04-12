from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ImportSessionResponse(BaseModel):
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
    confidence: float | None = None
    field_confidence: dict[str, float] | None = None
    raw_fields: dict[str, Any] | None = None
    edit_source: str


class ImportIssueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    attempt_number: int
    severity: str
    blocking: bool
    issue_code: str
    issue_message: str
    transaction_ref: str | None = None


class ImportReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session: ImportSessionResponse
    statement: ImportStatementDraftResponse | None = None
    transactions: list[ImportTransactionDraftResponse] = Field(default_factory=list)
    issues: list[ImportIssueResponse] = Field(default_factory=list)
    evidence: dict[str, Any] | None = None
