"""Module for backend app imports contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from ..models import transaction as transaction_models

if TYPE_CHECKING:
    from ..models.transaction import (
        ExpenseCategory,
        IncomeCategory,
        TransactionType,
        TransferCategory,
    )


class ImportStrategyKey(StrEnum):
    """Represent import strategy key."""

    BELFIUS_CSV = "belfius_csv"
    BEOBANK_CSV = "beobank_csv"
    NEXO_CSV = "nexo_csv"
    PDF_STATEMENT = "pdf_statement"
    UNKNOWN = "unknown"


class ImportIssue(BaseModel):
    """Represent import issue."""

    code: str
    message: str
    blocking: bool
    transaction_ref: str | None = None


class DetectionResult(BaseModel):
    """Represent detection result."""

    strategy_key: ImportStrategyKey
    provider_hint: str | None = None
    language_hint: str | None = None
    charset_hint: str | None = None
    confidence: float = 0.0
    page_count: int | None = None
    password_protected: bool = False
    notes: list[str] = Field(default_factory=list)


class RawEvidence(BaseModel):
    """Represent raw evidence."""

    text_blocks: list[JsonValue] = Field(default_factory=list)
    ocr_blocks: list[JsonValue] = Field(default_factory=list)
    snippets: list[JsonValue] = Field(default_factory=list)


class ExtractedTransaction(BaseModel):
    """Represent extracted transaction."""

    transaction_date: str
    source_description: str
    canonical_description_en: str | None = None
    signed_amount: float
    currency: str
    debit_credit: str
    inferred_category: str | None = None
    category_source: str | None = None
    proposed_transaction_type: TransactionType | str | None = None
    proposed_expense_category: ExpenseCategory | str | None = None
    proposed_income_category: IncomeCategory | str | None = None
    proposed_transfer_category: TransferCategory | str | None = None
    proposal_source: Literal["deterministic_extracted", "ai_extracted"] | None = None
    classification_source: str | None = None
    recurrence_pattern_id: int | None = None
    confidence: dict[str, float] = Field(default_factory=dict)
    source_locator: str
    edit_source: Literal["deterministic_extracted", "ai_extracted", "user_edited"] = (
        "ai_extracted"
    )


class ExtractionResult(BaseModel):
    """Represent extraction result."""

    extractor_id: str
    raw_artifact_ref: str
    source_metadata: dict[str, Any]
    statement_metadata: dict[str, Any]
    transactions: list[ExtractedTransaction]
    issues: list[ImportIssue] = Field(default_factory=list)
    overall_confidence: float = 0.0


class ProviderDescription(BaseModel):
    """Represent provider description."""

    model_config = ConfigDict(protected_namespaces=())

    provider_name: str
    model_name: str
    schema_version: str
    prompt_fingerprint: str


def _rebuild_import_contract_models() -> None:
    types_namespace: dict[str, object] = {
        "ExpenseCategory": transaction_models.ExpenseCategory,
        "IncomeCategory": transaction_models.IncomeCategory,
        "TransactionType": transaction_models.TransactionType,
        "TransferCategory": transaction_models.TransferCategory,
    }
    ExtractedTransaction.model_rebuild(
        force=True, _types_namespace=types_namespace
    )
    ExtractionResult.model_rebuild(force=True, _types_namespace=types_namespace)


_rebuild_import_contract_models()
