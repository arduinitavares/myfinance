import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..database import get_db
from ..imports.contracts import ImportStrategyKey
from ..imports.pipeline import ImportPipelineService
from ..imports.workflow import (
    ImportApprovalConflictError,
    ImportSessionNotFoundError,
    ImportSessionStateError,
    ImportWorkflowService,
)
from ..schemas.imports import ImportReviewResponse, ImportSessionResponse


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/imports", tags=["imports"])


@router.post("/upload", response_model=ImportSessionResponse)
async def upload_import(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    file_bytes = await file.read()
    pipeline = ImportPipelineService(db)
    workflow = ImportWorkflowService(db)

    try:
        session, detection = pipeline.start_upload(
            filename=file.filename or "upload.bin",
            content_type=file.content_type or "application/octet-stream",
            file_bytes=file_bytes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Import upload failed before extraction")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if detection.strategy_key == ImportStrategyKey.PDF_STATEMENT:
        try:
            session = workflow.extract_detected_session(session.id)
        except Exception:
            logger.warning("Import extraction crashed for session %s", session.id, exc_info=True)

    return workflow.get_session_snapshot(session.id)


@router.get("/{session_id}", response_model=ImportReviewResponse)
def get_import_review(
    session_id: int,
    db: Session = Depends(get_db),
):
    workflow = ImportWorkflowService(db)
    try:
        return workflow.get_review_payload(session_id)
    except ImportSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{session_id}/approve", response_model=ImportSessionResponse)
def approve_import(
    session_id: int,
    db: Session = Depends(get_db),
):
    workflow = ImportWorkflowService(db)
    try:
        session = workflow.approve_session(session_id)
        return workflow.get_session_snapshot(session.id)
    except ImportSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ImportApprovalConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(exc),
                "duplicates": exc.duplicates,
            },
        ) from exc
    except ImportSessionStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{session_id}/reject", response_model=ImportSessionResponse)
def reject_import(
    session_id: int,
    db: Session = Depends(get_db),
):
    workflow = ImportWorkflowService(db)
    try:
        session = workflow.reject_session(session_id)
        return workflow.get_session_snapshot(session.id)
    except ImportSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ImportSessionStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{session_id}/retry", response_model=ImportSessionResponse)
def retry_import(
    session_id: int,
    db: Session = Depends(get_db),
):
    workflow = ImportWorkflowService(db)
    try:
        session = workflow.retry_session(session_id)
        return workflow.get_session_snapshot(session.id)
    except ImportSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ImportSessionStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
