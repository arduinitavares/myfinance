from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from ..models.classification import ClassificationSessionStatus
from ..models.transaction import TransactionType
from .transaction import Transaction as TransactionSchema


class CreateClassificationSessionRequest(BaseModel):
    transaction_id: int


class SubmitFeedbackRequest(BaseModel):
    feedback_tag: str
    feedback_note: Optional[str] = None


class RecurrenceDecision(BaseModel):
    is_recurrent: bool = False
    frequency: Optional[str] = None


class AcceptClassificationRequest(BaseModel):
    transaction_type: TransactionType
    category: str
    classification_source: str
    confirm_type_change: bool = False
    recurrence: RecurrenceDecision = Field(default_factory=RecurrenceDecision)


class ApplyBatchRequest(BaseModel):
    transaction_ids: list[int]


class ClassificationSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: int
    transaction_id: int
    status: ClassificationSessionStatus
    provider_name: str
    model_name: str
    final_transaction_type: Optional[TransactionType] = None
    final_category: Optional[str] = None
    final_recurrence_frequency: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ClassificationProposalResponse(BaseModel):
    id: int
    session_id: int
    turn_index: int
    transaction_type: str
    category: str
    confidence: float
    recurrence_frequency: Optional[str] = None
    rationale: Optional[str] = None
    follow_up_question: Optional[str] = None
    feedback_tag: Optional[str] = None
    feedback_note: Optional[str] = None
    prompt_tokens: int
    completion_tokens: int
    created_at: datetime


class AcceptClassificationResponse(BaseModel):
    session: ClassificationSessionResponse
    transaction: TransactionSchema
    recurrence_pattern_id: Optional[int] = None
