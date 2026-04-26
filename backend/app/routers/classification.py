"""Module for backend app routers classification."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.classification import ClassificationSession
from ..schemas.classification import (
    AcceptClassificationRequest,
    AcceptClassificationResponse,
    ApplyBatchRequest,
    ApplyBatchResponse,
    ClassificationProposalResponse,
    ClassificationSessionResponse,
    CreateClassificationSessionRequest,
    SimilarPreviewResponse,
    SubmitFeedbackRequest,
)
from ..services.classification_session_service import ClassificationSessionService
from ..services.reporting_currency import get_reporting_currency

router: Any = APIRouter(prefix="/classification", tags=["classification"])
DbSession: object = Annotated[Session, Depends(get_db)]
ReportingCurrency: object = Annotated[str, Depends(get_reporting_currency)]


@router.post("/sessions", response_model=ClassificationSessionResponse)
def create_classification_session(
    request: CreateClassificationSessionRequest,
    db: DbSession,
) -> ClassificationSession:
    """Create classification session."""
    return ClassificationSessionService.create_or_resume_session(
        db, request.transaction_id
    )


@router.post(
    "/sessions/{session_id}/propose", response_model=ClassificationProposalResponse
)
def propose_classification(
    session_id: int,
    db: DbSession,
) -> ClassificationProposalResponse:
    """Handle propose classification."""
    return ClassificationSessionService.propose(db, session_id)


@router.post(
    "/sessions/{session_id}/feedback", response_model=ClassificationProposalResponse
)
def submit_feedback(
    session_id: int,
    request: SubmitFeedbackRequest,
    db: DbSession,
) -> ClassificationProposalResponse:
    """Handle submit feedback."""
    return ClassificationSessionService.record_feedback(db, session_id, request)


@router.post(
    "/sessions/{session_id}/accept", response_model=AcceptClassificationResponse
)
def accept_classification(
    session_id: int,
    request: AcceptClassificationRequest,
    db: DbSession,
    reporting_currency: ReportingCurrency,
) -> AcceptClassificationResponse:
    """Handle accept classification."""
    return ClassificationSessionService.accept(
        db,
        session_id,
        request,
        reporting_currency=reporting_currency,
    )


@router.post(
    "/sessions/{session_id}/similar-preview", response_model=SimilarPreviewResponse
)
def preview_similar_transactions(
    session_id: int,
    db: DbSession,
) -> SimilarPreviewResponse:
    """Handle preview similar transactions."""
    return ClassificationSessionService.preview_similar(db, session_id)


@router.post("/sessions/{session_id}/apply-batch", response_model=ApplyBatchResponse)
def apply_batch_classification(
    session_id: int,
    request: ApplyBatchRequest,
    db: DbSession,
) -> ApplyBatchResponse:
    """Handle apply batch classification."""
    return ClassificationSessionService.apply_batch(db, session_id, request)
