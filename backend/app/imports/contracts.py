from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from ..models.transaction import (
    ExpenseCategory,
    IncomeCategory,
    TransactionType,
    TransferCategory,
)


class ImportStrategyKey(str, Enum):
    BELFIUS_CSV = "belfius_csv"
    BEOBANK_CSV = "beobank_csv"
    NEXO_CSV = "nexo_csv"
    PDF_STATEMENT = "pdf_statement"
    UNKNOWN = "unknown"


class ImportIssue(BaseModel):
    code: str
    message: str
    blocking: bool
    transaction_ref: Optional[str] = None


class DetectionResult(BaseModel):
    strategy_key: ImportStrategyKey
    provider_hint: Optional[str] = None
    language_hint: Optional[str] = None
    charset_hint: Optional[str] = None
    confidence: float = 0.0
    page_count: Optional[int] = None
    password_protected: bool = False
    notes: list[str] = Field(default_factory=list)


class RawEvidence(BaseModel):
    text_blocks: list[JsonValue] = Field(default_factory=list)
    ocr_blocks: list[JsonValue] = Field(default_factory=list)
    snippets: list[JsonValue] = Field(default_factory=list)


class ExtractedTransaction(BaseModel):
    transaction_date: str
    source_description: str
    canonical_description_en: Optional[str] = None
    signed_amount: float
    currency: str
    debit_credit: str
    inferred_category: Optional[str] = None
    category_source: Optional[str] = None
    proposed_transaction_type: Optional[TransactionType | str] = None
    proposed_expense_category: Optional[ExpenseCategory | str] = None
    proposed_income_category: Optional[IncomeCategory | str] = None
    proposed_transfer_category: Optional[TransferCategory | str] = None
    proposal_source: Optional[Literal["deterministic_extracted", "ai_extracted"]] = None
    classification_source: Optional[str] = None
    recurrence_pattern_id: Optional[int] = None
    confidence: dict[str, float] = Field(default_factory=dict)
    source_locator: str
    edit_source: Literal["deterministic_extracted", "ai_extracted", "user_edited"] = "ai_extracted"


class ExtractionResult(BaseModel):
    extractor_id: str
    raw_artifact_ref: str
    source_metadata: dict[str, Any]
    statement_metadata: dict[str, Any]
    transactions: list[ExtractedTransaction]
    issues: list[ImportIssue] = Field(default_factory=list)
    overall_confidence: float = 0.0


class ProviderDescription(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    provider_name: str
    model_name: str
    schema_version: str
    prompt_fingerprint: str
