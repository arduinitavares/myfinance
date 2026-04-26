"""Module for backend tests imports test_pipeline."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import TYPE_CHECKING, Never

import pytest
from app.config import settings
from app.imports.artifacts import ArtifactStore
from app.imports.contracts import ExtractionResult
from app.imports.pipeline import ImportPipelineService, ImportUploadSessionCreationError
from app.imports.state_machine import ImportSessionStatus
from app.models.imports import ImportSession
from sqlalchemy.exc import IntegrityError
from tests.imports.fixtures.beobank_mastercard_pages import SANITIZED_BEOBANK_PAGE_TEXTS

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

SECOND_META_WRITE_CALL: int = 2
DETECTED_COMMIT_FAILURE_CALL: int = 2
DUPLICATE_RESOLUTION_COMMIT_COUNT: int = 3


def test_pipeline_creates_session_persists_upload_and_records_detection(
    db_session: Session,
) -> None:
    """Verify pipeline creates session persists upload and records detection."""
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
    assert (
        session_dir / "original" / "statement.pdf"
    ).read_bytes() == b"%PDF-1.7\nhello"
    assert (session_dir / "detection.json").exists()

    meta = json.loads((session_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["state"] == ImportSessionStatus.DETECTED.value
    assert meta["attempt_count"] == 1
    assert meta["detection"]["strategy_key"] == "pdf_statement"
    assert meta["detection"]["password_protected"] is False
    assert isinstance(meta["stage_timestamps"]["uploaded"], str)
    datetime.fromisoformat(meta["stage_timestamps"]["uploaded"])


def test_pipeline_marks_session_failed_when_artifact_write_rejects_filename(
    db_session: Session,
) -> None:
    """Verify pipeline marks session failed when artifact write rejects filename."""
    service = ImportPipelineService(db_session)

    with pytest.raises(ValueError, match="unsafe filename"):
        service.start_upload(
            filename="../statement.pdf",
            content_type="application/pdf",
            file_bytes=b"%PDF-1.7\nhello",
        )

    session = db_session.query(ImportSession).one()
    assert session.status == ImportSessionStatus.FAILED.value
    assert session.error_stage == "artifact_write"
    assert session.error_message is not None
    assert "unsafe filename" in session.error_message

    session_dir = settings.imports_dir / str(session.id)
    meta = json.loads((session_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["state"] == ImportSessionStatus.FAILED.value
    assert isinstance(meta["stage_timestamps"]["uploaded"], str)
    datetime.fromisoformat(meta["stage_timestamps"]["uploaded"])


def test_pipeline_marks_session_failed_when_manifest_write_fails_late(
    db_session: Session,
) -> None:
    """Verify pipeline marks session failed when manifest write fails late."""

    class FailingManifestArtifactStore(ArtifactStore):
        def __init__(self) -> None:
            super().__init__()
            self.write_meta_calls = 0

        def write_meta(self, session_id: str, payload: dict) -> None:
            self.write_meta_calls += 1
            if self.write_meta_calls == SECOND_META_WRITE_CALL:
                msg = "manifest write failed"
                raise RuntimeError(msg)
            super().write_meta(session_id, payload)

    service = ImportPipelineService(
        db_session, artifacts=FailingManifestArtifactStore()
    )

    with pytest.raises(RuntimeError, match="manifest write failed"):
        service.start_upload(
            filename="statement.pdf",
            content_type="application/pdf",
            file_bytes=b"%PDF-1.7\nhello",
        )

    session = db_session.query(ImportSession).one()
    assert session.status == ImportSessionStatus.FAILED.value
    assert session.error_stage == "manifest_write"
    assert session.error_message is not None
    assert "manifest write failed" in session.error_message

    session_dir = settings.imports_dir / str(session.id)
    meta = json.loads((session_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["state"] == ImportSessionStatus.FAILED.value
    assert meta["detection"]["strategy_key"] == "pdf_statement"
    assert isinstance(meta["stage_timestamps"]["uploaded"], str)
    assert isinstance(meta["stage_timestamps"]["detected"], str)
    datetime.fromisoformat(meta["stage_timestamps"]["uploaded"])
    datetime.fromisoformat(meta["stage_timestamps"]["detected"])


def test_pipeline_rolls_back_and_marks_failed_when_detected_commit_fails(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify pipeline rolls back and marks failed when detected commit fails."""
    service = ImportPipelineService(db_session)
    real_commit = db_session.commit
    commit_calls = {"count": 0}

    def flaky_commit() -> None:
        commit_calls["count"] += 1
        if commit_calls["count"] == DETECTED_COMMIT_FAILURE_CALL:
            msg = "detected commit failed"
            raise RuntimeError(msg)
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
    assert session.error_message is not None
    assert "detected commit failed" in session.error_message

    session_dir = settings.imports_dir / str(session.id)
    meta = json.loads((session_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["state"] == ImportSessionStatus.FAILED.value
    assert meta["detection"]["strategy_key"] == "pdf_statement"
    assert isinstance(meta["stage_timestamps"]["uploaded"], str)
    assert isinstance(meta["stage_timestamps"]["detected"], str)
    datetime.fromisoformat(meta["stage_timestamps"]["uploaded"])
    datetime.fromisoformat(meta["stage_timestamps"]["detected"])


def test_pipeline_retries_replaceable_owner_after_integrity_error_and_succeeds(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify pipeline retries replaceable owner after integrity error and succeeds."""
    monkeypatch.setattr(
        "app.imports.pdf_statement.read_pdf_page_text",
        lambda _: SANITIZED_BEOBANK_PAGE_TEXTS,
    )
    first_session, _ = ImportPipelineService(db_session).start_upload(
        filename="statement.pdf",
        content_type="application/pdf",
        file_bytes=b"%PDF-1.7\nhello",
    )

    failed_session = db_session.get(ImportSession, first_session.id)
    assert failed_session is not None
    failed_session.status = ImportSessionStatus.FAILED.value
    db_session.commit()

    original_file = (
        settings.imports_dir / str(first_session.id) / "original" / "statement.pdf"
    )
    original_file.unlink()

    real_commit = db_session.commit
    commit_calls = {"count": 0}

    def flaky_commit() -> None:
        commit_calls["count"] += 1
        if commit_calls["count"] == 1:
            msg = "insert"
            raise IntegrityError(msg, {}, Exception("duplicate key"))
        return real_commit()

    monkeypatch.setattr(db_session, "commit", flaky_commit)

    session, detection = ImportPipelineService(db_session).start_upload(
        filename="statement.pdf",
        content_type="application/pdf",
        file_bytes=b"%PDF-1.7\nhello",
    )

    assert session.id != first_session.id
    assert session.status == ImportSessionStatus.DETECTED.value
    assert detection.strategy_key.value == "pdf_statement"
    assert commit_calls["count"] == DUPLICATE_RESOLUTION_COMMIT_COUNT

    db_session.expire_all()
    replaced_session = db_session.get(ImportSession, first_session.id)
    new_session = db_session.get(ImportSession, session.id)
    assert replaced_session is not None
    assert new_session is not None
    expected_file_hash = hashlib.sha256(b"%PDF-1.7\nhello").hexdigest()
    assert (
        replaced_session.file_hash
        == f"{expected_file_hash}#legacy-duplicate#{first_session.id}"
    )
    assert replaced_session.status == ImportSessionStatus.SUPERSEDED.value
    assert new_session.file_hash == expected_file_hash


def test_pipeline_raises_controlled_error_when_duplicate_resolution_keeps_failing(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify pipeline raises controlled error after retry exhaustion."""
    monkeypatch.setattr(
        "app.imports.pdf_statement.read_pdf_page_text",
        lambda _: SANITIZED_BEOBANK_PAGE_TEXTS,
    )
    first_session, _ = ImportPipelineService(db_session).start_upload(
        filename="statement.pdf",
        content_type="application/pdf",
        file_bytes=b"%PDF-1.7\nhello",
    )

    failed_session = db_session.get(ImportSession, first_session.id)
    assert failed_session is not None
    failed_session.status = ImportSessionStatus.FAILED.value
    db_session.commit()

    original_file = (
        settings.imports_dir / str(first_session.id) / "original" / "statement.pdf"
    )
    original_file.unlink()

    def always_fail_commit() -> Never:
        msg = "insert"
        raise IntegrityError(msg, {}, Exception("duplicate key"))

    monkeypatch.setattr(db_session, "commit", always_fail_commit)

    with pytest.raises(
        ImportUploadSessionCreationError,
        match=r"Unable to create import session after duplicate resolution retries\.",
    ):
        ImportPipelineService(db_session).start_upload(
            filename="statement.pdf",
            content_type="application/pdf",
            file_bytes=b"%PDF-1.7\nhello",
        )


def test_artifact_store_writes_normalized_extraction_result_json(
    db_session: Session,
) -> None:
    """Verify artifact store writes normalized extraction result json."""
    _ = db_session
    store = ArtifactStore()
    session_id = "42"
    store.init_session(session_id)

    result = ExtractionResult(
        extractor_id="beobank_mastercard_pdf_v1",
        raw_artifact_ref="imports/42/attempts/1/evidence/raw.json",
        source_metadata={"provider_hint": "beobank"},
        statement_metadata={"currency": "EUR"},
        transactions=[],
        issues=[],
        overall_confidence=1.0,
    )

    store.write_normalized_result(session_id, 1, result)

    payload = json.loads(
        (
            settings.imports_dir
            / session_id
            / "attempts"
            / "1"
            / "normalized"
            / "extraction_result.json"
        ).read_text(encoding="utf-8")
    )
    assert payload["extractor_id"] == "beobank_mastercard_pdf_v1"
    assert payload["raw_artifact_ref"] == "imports/42/attempts/1/evidence/raw.json"
    assert payload["statement_metadata"] == {"currency": "EUR"}
