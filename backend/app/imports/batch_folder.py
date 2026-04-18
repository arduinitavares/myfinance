from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.imports.pipeline import ImportPipelineService, ImportUploadDuplicateError
from app.imports.state_machine import ImportSessionStatus
from app.imports.workflow import ImportWorkflowService
from app.models.imports import ImportBatchItem, ImportBatchRun, ImportSession

from .contracts import ImportStrategyKey


logger = logging.getLogger(__name__)

MAX_BATCH_FILES = 200
MAX_SUPPORTED_PDFS = 50
MAX_BATCH_FILE_SIZE_BYTES = 5 * 1024 * 1024
REVIEWABLE_BATCH_STRATEGIES = {
    ImportStrategyKey.PDF_STATEMENT,
    ImportStrategyKey.BELFIUS_CSV,
    ImportStrategyKey.BEOBANK_CSV,
    ImportStrategyKey.NEXO_CSV,
}


class ImportBatchRunNotFoundError(Exception):
    pass


class ImportBatchFolderService:
    def __init__(
        self,
        db: Session,
        pipeline: ImportPipelineService | None = None,
        workflow: ImportWorkflowService | None = None,
    ) -> None:
        self.db = db
        self.pipeline = pipeline or ImportPipelineService(db)
        self.workflow = workflow or ImportWorkflowService(db)

    def process_configured_folder(self) -> dict:
        folder_path, files = self._preflight_batch_folder()
        batch_run = self._create_batch_run(folder_path, total_files=len(files))
        batch_run_id = batch_run.id

        if not files:
            batch_run.status = "completed"
            batch_run.message = "No files found in the configured batch import folder."
            batch_run.completed_at = self._utcnow()
            self.db.commit()
            self.db.refresh(batch_run)
            return self._serialize_batch_run(batch_run.id)

        current_item: ImportBatchItem | None = None
        try:
            for file_path in files:
                current_item = self._start_batch_item(batch_run.id, file_path.name)
                self._process_file(batch_run, current_item, file_path)
                current_item = None

            self._refresh_batch_counts(batch_run)
            batch_run.status = "completed"
            batch_run.message = "Batch import completed."
            batch_run.completed_at = self._utcnow()
            self.db.commit()
            self.db.refresh(batch_run)
            return self._serialize_batch_run(batch_run.id)
        except Exception as exc:
            self.db.rollback()
            logger.exception("Batch import run %s failed unexpectedly", batch_run_id)
            self._fail_batch_run(batch_run, exc, current_item)
            raise

    def get_batch_run(self, batch_id: int) -> dict:
        batch_run = self.db.get(ImportBatchRun, batch_id)
        if batch_run is None:
            raise ImportBatchRunNotFoundError(f"Import batch run {batch_id} was not found.")
        return self._serialize_batch_run(batch_run.id)

    def get_latest_batch_run(self) -> dict:
        batch_run = self.db.query(ImportBatchRun).order_by(ImportBatchRun.created_at.desc(), ImportBatchRun.id.desc()).first()
        if batch_run is None:
            raise ImportBatchRunNotFoundError("No import batch runs were found.")
        return self._serialize_batch_run(batch_run.id)

    def _preflight_batch_folder(self) -> tuple[Path, list[Path]]:
        folder_path = settings.batch_import_dir
        if not folder_path.exists():
            raise ValueError(f"Configured batch import folder does not exist: {folder_path}")
        if not folder_path.is_dir():
            raise ValueError(f"Configured batch import folder is not a directory: {folder_path}")

        files = sorted(
            [
                child
                for child in folder_path.iterdir()
                if child.is_file() and not self._is_ignored_batch_file(child)
            ],
            key=lambda child: (child.name.casefold(), child.name),
        )
        if len(files) > MAX_BATCH_FILES:
            raise ValueError(f"Configured batch import folder contains too many files: {len(files)} > {MAX_BATCH_FILES}")

        supported_pdfs = [file_path for file_path in files if self._is_supported_pdf(file_path)]
        if len(supported_pdfs) > MAX_SUPPORTED_PDFS:
            raise ValueError(f"Configured batch import folder contains too many PDF files: {len(supported_pdfs)} > {MAX_SUPPORTED_PDFS}")

        supported_files = [file_path for file_path in files if self._is_supported_batch_file(file_path)]
        oversized_file = next(
            (file_path for file_path in supported_files if file_path.stat().st_size > MAX_BATCH_FILE_SIZE_BYTES),
            None,
        )
        if oversized_file is not None:
            raise ValueError(
                f"Batch import file exceeds the 5 MB limit: {oversized_file.name}"
            )

        return folder_path, files

    def _create_batch_run(self, folder_path: Path, *, total_files: int) -> ImportBatchRun:
        batch_run = ImportBatchRun(
            folder_path=str(folder_path),
            status="running",
            message=None,
            total_files=total_files,
            processed_count=0,
            skipped_existing_count=0,
            unsupported_count=0,
            failed_count=0,
        )
        self.db.add(batch_run)
        self.db.commit()
        self.db.refresh(batch_run)
        return batch_run

    def _start_batch_item(self, batch_run_id: int, filename: str) -> ImportBatchItem:
        item = ImportBatchItem(
            batch_run_id=batch_run_id,
            filename=filename,
            status="failed",
            started_at=self._utcnow(),
        )
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item

    def _process_file(self, batch_run: ImportBatchRun, item: ImportBatchItem, file_path: Path) -> None:
        if not self._is_supported_batch_file(file_path):
            suffix = file_path.suffix.lower() or "(no extension)"
            self._finalize_item(
                batch_run,
                item,
                status="unsupported",
                message=f"Unsupported batch file type: {suffix}",
            )
            return

        try:
            file_bytes = file_path.read_bytes()
            session, detection = self.pipeline.start_upload(
                filename=file_path.name,
                content_type=self._content_type_for_batch_file(file_path),
                file_bytes=file_bytes,
            )
        except ImportUploadDuplicateError as exc:
            existing_session = self.workflow.get_session_snapshot(exc.existing_session_id)
            self._finalize_item(
                batch_run,
                item,
                file_hash=exc.file_hash,
                status="skipped_existing",
                message=str(exc),
                existing_session_id=existing_session["id"],
                existing_session_status=existing_session["status"],
            )
            return
        except Exception as exc:
            self._finalize_item(
                batch_run,
                item,
                status="failed",
                message=str(exc),
            )
            return

        if detection.strategy_key not in REVIEWABLE_BATCH_STRATEGIES:
            session = self.workflow.fail_session(
                session.id,
                stage="detection",
                message=f"Unsupported import strategy for batch import: {detection.strategy_key.value}",
            )
            snapshot = self.workflow.get_session_snapshot(session.id)
            self._finalize_item(
                batch_run,
                item,
                file_hash=session.file_hash,
                status="failed",
                message=snapshot["error_message"],
                session_id=session.id,
                session_status=snapshot["status"],
                strategy_key=detection.strategy_key.value,
                extractor_id=snapshot["extractor_id"],
            )
            return

        try:
            session = self.workflow.extract_detected_session(session.id)
        except Exception:
            logger.warning("Import extraction crashed during batch run for session %s", session.id, exc_info=True)

        snapshot = self.workflow.get_session_snapshot(session.id)
        item_status = "processed" if snapshot["status"] == ImportSessionStatus.AWAITING_REVIEW.value else "failed"
        self._finalize_item(
            batch_run,
            item,
            file_hash=session.file_hash,
            status=item_status,
            message=None if item_status == "processed" else snapshot["error_message"],
            session_id=session.id,
            session_status=snapshot["status"],
            strategy_key=snapshot["strategy_key"],
            extractor_id=snapshot["extractor_id"],
        )

    def _finalize_item(
        self,
        batch_run: ImportBatchRun,
        item: ImportBatchItem,
        *,
        status: str,
        message: str | None = None,
        file_hash: str | None = None,
        session_id: int | None = None,
        session_status: str | None = None,
        existing_session_id: int | None = None,
        existing_session_status: str | None = None,
        strategy_key: str | None = None,
        extractor_id: str | None = None,
    ) -> None:
        item.file_hash = file_hash
        item.status = status
        item.message = message
        item.session_id = session_id
        item.session_status = session_status
        item.existing_session_id = existing_session_id
        item.existing_session_status = existing_session_status
        item.strategy_key = strategy_key
        item.extractor_id = extractor_id
        item.completed_at = self._utcnow()
        self.db.commit()
        self.db.refresh(item)
        self._refresh_batch_counts(batch_run)

    def _refresh_batch_counts(self, batch_run: ImportBatchRun) -> None:
        counts = dict(
            self.db.query(ImportBatchItem.status, func.count(ImportBatchItem.id))
            .filter(ImportBatchItem.batch_run_id == batch_run.id)
            .group_by(ImportBatchItem.status)
            .all()
        )
        batch_run.processed_count = counts.get("processed", 0)
        batch_run.skipped_existing_count = counts.get("skipped_existing", 0)
        batch_run.unsupported_count = counts.get("unsupported", 0)
        batch_run.failed_count = counts.get("failed", 0)
        self.db.commit()
        self.db.refresh(batch_run)

    def _fail_batch_run(self, batch_run: ImportBatchRun, exc: Exception, current_item: ImportBatchItem | None) -> None:
        if current_item is not None:
            persisted_current_item = self.db.get(ImportBatchItem, current_item.id)
            if persisted_current_item is not None and persisted_current_item.completed_at is None:
                session_status = persisted_current_item.session_status
                if persisted_current_item.session_id is not None and session_status is None:
                    session = self.db.get(ImportSession, persisted_current_item.session_id)
                    session_status = session.status if session is not None else None
                persisted_current_item.status = "failed"
                persisted_current_item.message = str(exc)
                persisted_current_item.session_status = session_status
                persisted_current_item.completed_at = self._utcnow()

        counts = dict(
            self.db.query(ImportBatchItem.status, func.count(ImportBatchItem.id))
            .filter(ImportBatchItem.batch_run_id == batch_run.id)
            .group_by(ImportBatchItem.status)
            .all()
        )
        self.db.query(ImportBatchRun).filter(ImportBatchRun.id == batch_run.id).update(
            {
                ImportBatchRun.processed_count: counts.get("processed", 0),
                ImportBatchRun.skipped_existing_count: counts.get("skipped_existing", 0),
                ImportBatchRun.unsupported_count: counts.get("unsupported", 0),
                ImportBatchRun.failed_count: counts.get("failed", 0),
                ImportBatchRun.status: "failed",
                ImportBatchRun.message: str(exc),
                ImportBatchRun.completed_at: self._utcnow(),
            },
            synchronize_session=False,
        )
        self.db.commit()

    def _serialize_batch_run(self, batch_id: int) -> dict:
        batch_run = self.db.get(ImportBatchRun, batch_id)
        if batch_run is None:
            raise ImportBatchRunNotFoundError(f"Import batch run {batch_id} was not found.")
        items = (
            self.db.query(ImportBatchItem)
            .filter(ImportBatchItem.batch_run_id == batch_id)
            .order_by(ImportBatchItem.id.asc())
            .all()
        )
        return {
            "id": batch_run.id,
            "folder_path": batch_run.folder_path,
            "status": batch_run.status,
            "message": batch_run.message,
            "total_files": batch_run.total_files,
            "processed_count": batch_run.processed_count,
            "skipped_existing_count": batch_run.skipped_existing_count,
            "unsupported_count": batch_run.unsupported_count,
            "failed_count": batch_run.failed_count,
            "created_at": batch_run.created_at,
            "completed_at": batch_run.completed_at,
            "items": [
                {
                    "id": item.id,
                    "filename": item.filename,
                    "file_hash": item.file_hash,
                    "status": item.status,
                    "message": item.message,
                    "session_id": item.session_id,
                    "session_status": item.session_status,
                    "existing_session_id": item.existing_session_id,
                    "existing_session_status": item.existing_session_status,
                    "strategy_key": item.strategy_key,
                    "extractor_id": item.extractor_id,
                    "started_at": item.started_at,
                    "completed_at": item.completed_at,
                }
                for item in items
                if batch_run.status != "running" or item.completed_at is not None
            ],
        }

    @staticmethod
    def _is_supported_batch_file(file_path: Path) -> bool:
        return ImportBatchFolderService._is_supported_pdf(file_path) or ImportBatchFolderService._is_supported_csv(file_path)

    @staticmethod
    def _is_supported_pdf(file_path: Path) -> bool:
        return file_path.suffix.lower() == ".pdf"

    @staticmethod
    def _is_supported_csv(file_path: Path) -> bool:
        return file_path.suffix.lower() == ".csv"

    @staticmethod
    def _content_type_for_batch_file(file_path: Path) -> str:
        return "text/csv" if ImportBatchFolderService._is_supported_csv(file_path) else "application/pdf"

    @staticmethod
    def _is_ignored_batch_file(file_path: Path) -> bool:
        lowered_name = file_path.name.casefold()
        return (
            lowered_name in {".ds_store", "thumbs.db", "desktop.ini"}
            or lowered_name.startswith("._")
        )

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.utcnow()
