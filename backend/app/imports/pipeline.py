"""Module for backend app imports pipeline."""

import hashlib
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.imports.artifacts import ArtifactStore
from app.imports.contracts import DetectionResult
from app.imports.dedupe import (
    choose_canonical_import_session,
    get_import_sessions_by_file_hash,
    is_replaceable_duplicate_owner,
    rewrite_import_session_as_legacy_duplicate,
)
from app.imports.detection import ImportDetector
from app.imports.state_machine import ImportSessionStatus, assert_transition_allowed
from app.models.imports import ImportSession


class ImportUploadDuplicateError(Exception):
    """Represent import upload duplicate error."""

    def __init__(self, *, file_hash: str, existing_session_id: int) -> None:
        """Initialize the instance."""
        super().__init__("Import session with this file hash already exists.")
        self.file_hash = file_hash
        self.existing_session_id = existing_session_id


class ImportUploadSessionCreationError(Exception):
    """Represent import upload session creation error."""

    def __init__(self, *, file_hash: str, attempts: int) -> None:
        """Initialize the instance."""
        super().__init__(
            "Unable to create import session after duplicate resolution retries."
        )
        self.file_hash = file_hash
        self.attempts = attempts


class ImportPipelineService:
    """Represent import pipeline service."""

    def __init__(
        self,
        db: Session,
        detector: ImportDetector | None = None,
        artifacts: ArtifactStore | None = None,
    ) -> None:
        """Initialize the instance."""
        self.db = db
        self.detector = detector or ImportDetector()
        self.artifacts = artifacts or ArtifactStore()

    def start_upload(
        self, *, filename: str, content_type: str, file_bytes: bytes
    ) -> tuple[ImportSession, DetectionResult]:
        """Handle start upload."""
        file_hash = hashlib.sha256(file_bytes).hexdigest()
        session = self._create_upload_session(
            filename=filename,
            content_type=content_type,
            file_hash=file_hash,
        )

        session_id = str(session.id)
        stage = "artifact_write"
        stage_timestamps = {"uploaded": self._stage_timestamp()}
        detection: DetectionResult | None = None
        try:
            self.artifacts.init_session(session_id)
            self.artifacts.write_original_file(session_id, filename, file_bytes)
            self.artifacts.write_meta(
                session_id,
                self._build_meta_payload(
                    state=session.status,
                    stage_timestamps=stage_timestamps,
                ),
            )

            stage = "detection"
            detection = self.detector.detect(
                filename=filename,
                content_type=content_type,
                sample=file_bytes[:4096],
            )
            stage = "session_update"
            assert_transition_allowed(
                ImportSessionStatus(session.status), ImportSessionStatus.DETECTED
            )
            session.status = ImportSessionStatus.DETECTED.value
            session.strategy_key = detection.strategy_key.value
            session.provider_hint = detection.provider_hint
            session.language_hint = detection.language_hint
            session.charset_hint = detection.charset_hint
            stage_timestamps["detected"] = self._stage_timestamp()
            stage = "manifest_write"
            self.artifacts.write_detection(session_id, detection)
            self.artifacts.write_meta(
                session_id,
                self._build_meta_payload(
                    state=session.status,
                    detection=detection,
                    stage_timestamps=stage_timestamps,
                ),
            )
            stage = "db_commit"
            self.db.commit()
            self.db.refresh(session)
        except Exception as exc:
            self.db.rollback()
            persisted_session = self.db.get(ImportSession, session.id)
            if persisted_session is None:
                raise

            persisted_session.status = ImportSessionStatus.FAILED.value
            persisted_session.error_stage = stage
            persisted_session.error_message = str(exc)
            self.db.commit()
            self.db.refresh(persisted_session)

            self.artifacts.write_meta(
                session_id,
                self._build_meta_payload(
                    state=persisted_session.status,
                    detection=detection,
                    stage_timestamps=stage_timestamps,
                ),
            )
            raise
        else:
            if detection is None:
                msg = "Import detection did not produce a result."
                raise RuntimeError(msg)
            return session, detection

    def _create_upload_session(
        self, *, filename: str, content_type: str, file_hash: str
    ) -> ImportSession:
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            existing_session = self._resolve_existing_upload_session(file_hash)
            if existing_session is not None:
                if not is_replaceable_duplicate_owner(
                    existing_session, self.artifacts.root
                ):
                    raise ImportUploadDuplicateError(
                        file_hash=file_hash,
                        existing_session_id=existing_session.id,
                    )
                rewrite_import_session_as_legacy_duplicate(existing_session)

            session = ImportSession(
                file_name=filename,
                file_hash=file_hash,
                mime_type=content_type,
                status=ImportSessionStatus.UPLOADED.value,
            )
            self.db.add(session)

            try:
                self.db.commit()
                self.db.refresh(session)
            except IntegrityError:
                self.db.rollback()
                if attempt == max_attempts:
                    break
            else:
                return session

        raise ImportUploadSessionCreationError(
            file_hash=file_hash, attempts=max_attempts
        )

    def _resolve_existing_upload_session(self, file_hash: str) -> ImportSession | None:
        sessions = get_import_sessions_by_file_hash(self.db, file_hash)
        if not sessions:
            return None
        return choose_canonical_import_session(sessions, self.artifacts.root)

    @staticmethod
    def _build_meta_payload(
        *,
        state: str,
        stage_timestamps: dict[str, str],
        detection: DetectionResult | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "state": state,
            "attempt_count": 1,
            "stage_timestamps": stage_timestamps,
        }
        if detection is not None:
            payload["detection"] = detection.model_dump(mode="json")
        return payload

    @staticmethod
    def _stage_timestamp() -> str:
        return datetime.now(UTC).isoformat(timespec="seconds")
