from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..services.reporting_currency import get_reporting_currency
from ..schemas.classification import (
    ApplyBatchRequest,
    ApplyBatchResponse,
    AcceptClassificationRequest,
    AcceptClassificationResponse,
    ClassificationProposalResponse,
    ClassificationSessionResponse,
    CreateClassificationSessionRequest,
    SimilarPreviewResponse,
    SubmitFeedbackRequest,
)
from ..services.classification_session_service import ClassificationSessionService


router = APIRouter(prefix="/classification", tags=["classification"])


@router.post("/sessions", response_model=ClassificationSessionResponse)
def create_classification_session(
    request: CreateClassificationSessionRequest,
    db: Session = Depends(get_db),
):
    return ClassificationSessionService.create_or_resume_session(db, request.transaction_id)


@router.post("/sessions/{session_id}/propose", response_model=ClassificationProposalResponse)
def propose_classification(session_id: int, db: Session = Depends(get_db)):
    return ClassificationSessionService.propose(db, session_id)


@router.post("/sessions/{session_id}/feedback", response_model=ClassificationProposalResponse)
def submit_feedback(
    session_id: int,
    request: SubmitFeedbackRequest,
    db: Session = Depends(get_db),
):
    return ClassificationSessionService.record_feedback(db, session_id, request)


@router.post("/sessions/{session_id}/accept", response_model=AcceptClassificationResponse)
def accept_classification(
    session_id: int,
    request: AcceptClassificationRequest,
    db: Session = Depends(get_db),
    reporting_currency: str = Depends(get_reporting_currency),
):
    return ClassificationSessionService.accept(
        db,
        session_id,
        request,
        reporting_currency=reporting_currency,
    )


@router.post("/sessions/{session_id}/similar-preview", response_model=SimilarPreviewResponse)
def preview_similar_transactions(session_id: int, db: Session = Depends(get_db)):
    return ClassificationSessionService.preview_similar(db, session_id)


@router.post("/sessions/{session_id}/apply-batch", response_model=ApplyBatchResponse)
def apply_batch_classification(
    session_id: int,
    request: ApplyBatchRequest,
    db: Session = Depends(get_db),
):
    return ClassificationSessionService.apply_batch(db, session_id, request)
