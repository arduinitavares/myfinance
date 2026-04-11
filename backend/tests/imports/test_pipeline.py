import json
from datetime import datetime

import pytest

from app.config import settings
from app.imports.artifacts import ArtifactStore
from app.imports.pipeline import ImportPipelineService
from app.imports.state_machine import ImportSessionStatus
from app.models.imports import ImportSession


def test_pipeline_creates_session_persists_upload_and_records_detection(db_session):
    service = ImportPipelineService(db_session)
    session, detection = service.start_upload(
        filename="statement.pdf",
        content_type="application/pdf",
        file_bytes=b"%PDF-1.7\nhello",
    )

    assert session.status == ImportSessionStatus.DETECTED.value
    assert session.strategy_key == detection.strategy_key.value
    assert session.file_name == "statement.pdf"

    session_dir = settings.imports_dir / str(session.id)
    assert (session_dir / "original" / "statement.pdf").read_bytes() == b"%PDF-1.7\nhello"
    assert (session_dir / "detection.json").exists()

    meta = json.loads((session_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["state"] == ImportSessionStatus.DETECTED.value
    assert meta["attempt_count"] == 1
    assert meta["detection"]["strategy_key"] == "pdf_statement"
    assert meta["detection"]["password_protected"] is False
    assert isinstance(meta["stage_timestamps"]["uploaded"], str)
    datetime.fromisoformat(meta["stage_timestamps"]["uploaded"])


def test_pipeline_marks_session_failed_when_artifact_write_rejects_filename(db_session):
    service = ImportPipelineService(db_session)

    with pytest.raises(ValueError):
        service.start_upload(
            filename="../statement.pdf",
            content_type="application/pdf",
            file_bytes=b"%PDF-1.7\nhello",
        )

    session = db_session.query(ImportSession).one()
    assert session.status == ImportSessionStatus.FAILED.value
    assert session.error_stage == "artifact_write"
    assert "unsafe filename" in session.error_message

    session_dir = settings.imports_dir / str(session.id)
    meta = json.loads((session_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["state"] == ImportSessionStatus.FAILED.value
    assert isinstance(meta["stage_timestamps"]["uploaded"], str)
    datetime.fromisoformat(meta["stage_timestamps"]["uploaded"])


def test_pipeline_marks_session_failed_when_manifest_write_fails_late(db_session):
    class FailingManifestArtifactStore(ArtifactStore):
        def __init__(self):
            super().__init__()
            self.write_meta_calls = 0

        def write_meta(self, session_id: str, payload: dict) -> None:
            self.write_meta_calls += 1
            if self.write_meta_calls == 2:
                raise RuntimeError("manifest write failed")
            super().write_meta(session_id, payload)

    service = ImportPipelineService(db_session, artifacts=FailingManifestArtifactStore())

    with pytest.raises(RuntimeError, match="manifest write failed"):
        service.start_upload(
            filename="statement.pdf",
            content_type="application/pdf",
            file_bytes=b"%PDF-1.7\nhello",
        )

    session = db_session.query(ImportSession).one()
    assert session.status == ImportSessionStatus.FAILED.value
    assert session.error_stage == "manifest_write"
    assert "manifest write failed" in session.error_message

    session_dir = settings.imports_dir / str(session.id)
    meta = json.loads((session_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["state"] == ImportSessionStatus.FAILED.value
    assert meta["detection"]["strategy_key"] == "pdf_statement"
    assert isinstance(meta["stage_timestamps"]["uploaded"], str)
    assert isinstance(meta["stage_timestamps"]["detected"], str)
    datetime.fromisoformat(meta["stage_timestamps"]["uploaded"])
    datetime.fromisoformat(meta["stage_timestamps"]["detected"])


def test_pipeline_rolls_back_and_marks_failed_when_detected_commit_fails(db_session, monkeypatch):
    service = ImportPipelineService(db_session)
    real_commit = db_session.commit
    commit_calls = {"count": 0}

    def flaky_commit():
        commit_calls["count"] += 1
        if commit_calls["count"] == 2:
            raise RuntimeError("detected commit failed")
        return real_commit()

    monkeypatch.setattr(db_session, "commit", flaky_commit)

    with pytest.raises(RuntimeError, match="detected commit failed"):
        service.start_upload(
            filename="statement.pdf",
            content_type="application/pdf",
            file_bytes=b"%PDF-1.7\nhello",
        )

    session = db_session.query(ImportSession).one()
    assert session.status == ImportSessionStatus.FAILED.value
    assert session.error_stage == "db_commit"
    assert "detected commit failed" in session.error_message

    session_dir = settings.imports_dir / str(session.id)
    meta = json.loads((session_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["state"] == ImportSessionStatus.FAILED.value
    assert meta["detection"]["strategy_key"] == "pdf_statement"
    assert isinstance(meta["stage_timestamps"]["uploaded"], str)
    assert isinstance(meta["stage_timestamps"]["detected"], str)
    datetime.fromisoformat(meta["stage_timestamps"]["uploaded"])
    datetime.fromisoformat(meta["stage_timestamps"]["detected"])
