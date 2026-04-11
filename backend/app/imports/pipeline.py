import hashlib

from sqlalchemy.orm import Session

from app.imports.artifacts import ArtifactStore
from app.imports.detection import ImportDetector
from app.imports.state_machine import ImportSessionStatus, assert_transition_allowed
from app.models.imports import ImportSession


class ImportPipelineService:
    def __init__(
        self,
        db: Session,
        detector: ImportDetector | None = None,
        artifacts: ArtifactStore | None = None,
    ) -> None:
        self.db = db
        self.detector = detector or ImportDetector()
        self.artifacts = artifacts or ArtifactStore()

    def start_upload(self, *, filename: str, content_type: str, file_bytes: bytes):
        session = ImportSession(
            file_name=filename,
            file_hash=hashlib.sha256(file_bytes).hexdigest(),
            mime_type=content_type,
            status=ImportSessionStatus.UPLOADED.value,
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)

        session_id = str(session.id)
        stage = "artifact_write"
        stage_timestamps = {"uploaded": True}
        detection = None
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
            assert_transition_allowed(ImportSessionStatus(session.status), ImportSessionStatus.DETECTED)
            session.status = ImportSessionStatus.DETECTED.value
            session.strategy_key = detection.strategy_key.value
            session.provider_hint = detection.provider_hint
            session.language_hint = detection.language_hint
            session.charset_hint = detection.charset_hint
            stage_timestamps["detected"] = True
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
            return session, detection
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

    @staticmethod
    def _build_meta_payload(*, state: str, stage_timestamps: dict[str, bool], detection=None) -> dict:
        payload = {
            "state": state,
            "attempt_count": 1,
            "stage_timestamps": stage_timestamps,
        }
        if detection is not None:
            payload["detection"] = detection.model_dump(mode="json")
        return payload
