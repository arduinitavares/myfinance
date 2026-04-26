"""Module for backend app schemas classification."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from ..models.classification import ClassificationSessionStatus
from ..models.transaction import TransactionType
from .transaction import Transaction as TransactionSchema


class CreateClassificationSessionRequest(BaseModel):
    """Represent create classification session request."""

    transaction_id: int


class SubmitFeedbackRequest(BaseModel):
    """Represent submit feedback request."""

    feedback_tag: str
    feedback_note: str | None = None


class RecurrenceDecision(BaseModel):
    """Represent recurrence decision."""

    is_recurrent: bool = False
    frequency: str | None = None


class AcceptClassificationRequest(BaseModel):
    """Represent accept classification request."""

    transaction_type: TransactionType
    category: str
    classification_source: str
    confirm_type_change: bool = False
    recurrence: RecurrenceDecision = Field(default_factory=RecurrenceDecision)


class ApplyBatchRequest(BaseModel):
    """Represent apply batch request."""

    transaction_ids: list[int]


class ClassificationSessionResponse(BaseModel):
    """Represent classification session response."""

    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: int
    transaction_id: int
    status: ClassificationSessionStatus
    provider_name: str
    model_name: str
    final_transaction_type: TransactionType | None = None
    final_category: str | None = None
    final_recurrence_frequency: str | None = None
    created_at: datetime
    updated_at: datetime


class ClassificationProposalResponse(BaseModel):
    """Represent classification proposal response."""

    id: int
    session_id: int
    turn_index: int
    transaction_type: str
    category: str
    confidence: float
    recurrence_frequency: str | None = None
    rationale: str | None = None
    follow_up_question: str | None = None
    feedback_tag: str | None = None
    feedback_note: str | None = None
    prompt_tokens: int
    completion_tokens: int
    created_at: datetime


class AcceptClassificationResponse(BaseModel):
    """Represent accept classification response."""

    session: ClassificationSessionResponse
    transaction: TransactionSchema
    recurrence_pattern_id: int | None = None


class SimilarTransactionMatchResponse(BaseModel):
    """Represent similar transaction match response."""

    transaction_id: int
    description: str
    amount: float
    currency: str
    score: float


class SimilarPreviewResponse(BaseModel):
    """Represent similar preview response."""

    session: ClassificationSessionResponse
    seed_transaction_id: int
    matches: list[SimilarTransactionMatchResponse]


class ApplyBatchResponse(BaseModel):
    """Represent apply batch response."""

    session: ClassificationSessionResponse
    applied_transaction_ids: list[int]
    skipped_transaction_ids: list[int]
