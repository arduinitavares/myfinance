import logging
import time
from pathlib import Path
from typing import Dict, List

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..imports.batch_folder import ImportBatchFolderService, ImportBatchRunNotFoundError
from ..imports.contracts import ImportStrategyKey
from ..imports.csv_support import (
    BELFIUS_HEADER,
    BEOBANK_COMPACT_HEADER,
    BEOBANK_DEBIT_CREDIT_HEADER,
    NEXO_HEADER,
    build_dict_rows,
    decode_csv_bytes,
    find_header_row,
)
from ..imports.detection import ImportDetector
from ..imports.pipeline import ImportPipelineService, ImportUploadDuplicateError
from ..imports.workflow import (
    ImportApprovalConflictError,
    ImportSessionNotFoundError,
    ImportSessionStateError,
    ImportWorkflowService,
)
from ..services.reporting_currency import get_reporting_currency
from ..schemas.imports import (
    ImportBatchRunResponse,
    ImportReviewResponse,
    ImportSessionResponse,
    ImportUploadConflictResponse,
)


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/imports", tags=["imports"])

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_ROWS_PER_UPLOAD = 5000
ALLOWED_CSV_CONTENT_TYPES = {
    "text/csv",
    "application/csv",
    "application/vnd.ms-excel",
    "application/octet-stream",
    "text/plain",
    "",
}
ALLOWED_PDF_CONTENT_TYPES = {
    "application/pdf",
    "application/octet-stream",
    "",
}
AUTO_EXTRACT_STRATEGIES = {
    ImportStrategyKey.PDF_STATEMENT,
    ImportStrategyKey.BELFIUS_CSV,
    ImportStrategyKey.BEOBANK_CSV,
    ImportStrategyKey.NEXO_CSV,
}
CSV_LAYOUTS = {
    ImportStrategyKey.BELFIUS_CSV: [(";", BELFIUS_HEADER)],
    ImportStrategyKey.BEOBANK_CSV: [
        (";", BEOBANK_COMPACT_HEADER),
        (";", BEOBANK_DEBIT_CREDIT_HEADER),
        (",", BEOBANK_DEBIT_CREDIT_HEADER),
    ],
    ImportStrategyKey.NEXO_CSV: [(",", NEXO_HEADER)],
}
RATE_LIMIT_WINDOW_SECONDS = 60
MAX_UPLOADS_PER_WINDOW = 3
_upload_attempts: Dict[str, List[float]] = {}


def _check_rate_limit(client_ip: str) -> None:
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW_SECONDS
    timestamps = [timestamp for timestamp in _upload_attempts.get(client_ip, []) if timestamp >= window_start]
    if len(timestamps) >= MAX_UPLOADS_PER_WINDOW:
        raise HTTPException(status_code=429, detail="Too many uploads. Please wait a minute and try again.")
    timestamps.append(now)
    _upload_attempts[client_ip] = timestamps


def _validate_upload_request(file: UploadFile) -> str:
    filename = file.filename or "upload.bin"
    suffix = Path(filename).suffix.casefold()
    if suffix not in {".csv", ".pdf"}:
        raise HTTPException(status_code=400, detail="Invalid file format. Please upload a CSV or PDF file.")

    content_type = file.content_type or ""
    allowed_types = ALLOWED_CSV_CONTENT_TYPES if suffix == ".csv" else ALLOWED_PDF_CONTENT_TYPES
    if content_type not in allowed_types:
        raise HTTPException(
            status_code=415,
            detail="Unsupported media type. Please upload a CSV or PDF file.",
        )
    return suffix


def _count_supported_csv_rows(file_bytes: bytes, strategy_key: ImportStrategyKey) -> int:
    raw_text, _ = decode_csv_bytes(file_bytes)
    lines = raw_text.splitlines()
    for delimiter, expected_header in CSV_LAYOUTS.get(strategy_key, []):
        header_match = find_header_row(lines, delimiter=delimiter, expected_header=expected_header)
        if header_match is None:
            continue
        header_row_index, _ = header_match
        return sum(
            1
            for _, row in build_dict_rows(lines, delimiter=delimiter, header_row_index=header_row_index)
            if any(value for value in row.values())
        )
    return 0


@router.post("/batch-folder", response_model=ImportBatchRunResponse)
def import_batch_folder(
    db: Session = Depends(get_db),
):
    service = ImportBatchFolderService(db)
    try:
        return service.process_configured_folder()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/batches/latest", response_model=ImportBatchRunResponse)
def get_latest_import_batch(
    db: Session = Depends(get_db),
):
    service = ImportBatchFolderService(db)
    try:
        return service.get_latest_batch_run()
    except ImportBatchRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/batches/{batch_id}", response_model=ImportBatchRunResponse)
def get_import_batch(
    batch_id: int,
    db: Session = Depends(get_db),
):
    service = ImportBatchFolderService(db)
    try:
        return service.get_batch_run(batch_id)
    except ImportBatchRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/upload",
    response_model=ImportSessionResponse,
    responses={409: {"model": ImportUploadConflictResponse}},
)
async def upload_import(
    file: UploadFile = File(...),
    request: Request = None,
    db: Session = Depends(get_db),
):
    filename = file.filename or "upload.bin"
    suffix = _validate_upload_request(file)

    if suffix == ".csv":
        client_ip = request.client.host if request and request.client else "unknown"
        _check_rate_limit(client_ip)

    file_bytes = await file.read()
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large. Max allowed size is 5 MB.")

    if suffix == ".csv":
        preliminary_detection = ImportDetector().detect(
            filename=filename,
            content_type=file.content_type or "application/octet-stream",
            sample=file_bytes[:4096],
        )
        if preliminary_detection.strategy_key in CSV_LAYOUTS:
            row_count = _count_supported_csv_rows(file_bytes, preliminary_detection.strategy_key)
            if row_count > MAX_ROWS_PER_UPLOAD:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"CSV contains {row_count} rows. "
                        f"The maximum allowed per upload is {MAX_ROWS_PER_UPLOAD}."
                    ),
                )

    pipeline = ImportPipelineService(db)
    workflow = ImportWorkflowService(db)

    try:
        session, detection = pipeline.start_upload(
            filename=filename,
            content_type=file.content_type or "application/octet-stream",
            file_bytes=file_bytes,
        )
    except ImportUploadDuplicateError as exc:
        workflow = ImportWorkflowService(db)
        return JSONResponse(
            status_code=409,
            content=ImportUploadConflictResponse(
                message=str(exc),
                file_hash=exc.file_hash,
                existing_session=ImportSessionResponse.model_validate(
                    workflow.get_session_snapshot(exc.existing_session_id)
                ),
            ).model_dump(mode="json"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Import upload failed before extraction")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if detection.strategy_key in AUTO_EXTRACT_STRATEGIES:
        try:
            session = workflow.extract_detected_session(session.id)
        except Exception:
            logger.warning("Import extraction crashed for session %s", session.id, exc_info=True)
    else:
        session = workflow.fail_session(
            session.id,
            stage="detection",
            message=f"Unsupported import strategy: {detection.strategy_key.value}",
        )

    return workflow.get_session_snapshot(session.id)


@router.get("/{session_id}", response_model=ImportReviewResponse)
def get_import_review(
    session_id: int,
    db: Session = Depends(get_db),
    reporting_currency: str = Depends(get_reporting_currency),
):
    workflow = ImportWorkflowService(db)
    try:
        return workflow.get_review_payload(session_id, reporting_currency=reporting_currency)
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
