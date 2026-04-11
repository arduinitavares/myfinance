import json

import pytest

from app.config import settings
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
