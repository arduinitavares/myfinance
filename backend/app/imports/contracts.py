from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class ImportStrategyKey(str, Enum):
    BELFIUS_CSV = "belfius_csv"
    BEOBANK_CSV = "beobank_csv"
    PDF_STATEMENT = "pdf_statement"
    UNKNOWN = "unknown"


class ImportIssue(BaseModel):
    code: str
    message: str
    blocking: bool
    transaction_ref: str | None = None


class DetectionResult(BaseModel):
    strategy_key: ImportStrategyKey
    provider_hint: str | None = None
    language_hint: str | None = None
    charset_hint: str | None = None
    confidence: float = 0.0
    page_count: int | None = None
    password_protected: bool = False
    notes: list[str] = Field(default_factory=list)


class RawEvidence(BaseModel):
    text_blocks: list[JsonValue] = Field(default_factory=list)
    ocr_blocks: list[JsonValue] = Field(default_factory=list)
    snippets: list[JsonValue] = Field(default_factory=list)


class ExtractedTransaction(BaseModel):
    transaction_date: str
    source_description: str
    canonical_description_en: str | None = None
    signed_amount: float
    currency: str
    debit_credit: str
    inferred_category: str | None = None
    category_source: str | None = None
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
