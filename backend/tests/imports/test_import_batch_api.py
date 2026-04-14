import json
from dataclasses import replace
from datetime import datetime, timezone

from fastapi.testclient import TestClient

import app.config as config_module
from app.imports.contracts import DetectionResult, ImportStrategyKey
from app.imports.batch_folder import ImportBatchFolderService
from app.main import app
from app.models.imports import ImportBatchItem, ImportBatchRun, ImportSession
from tests.imports.fixtures.beobank_mastercard_pages import SANITIZED_BEOBANK_PAGE_TEXTS


client = TestClient(app)


def _configure_batch_dir(monkeypatch, batch_dir):
    patched_settings = replace(config_module.settings, batch_import_dir=batch_dir.resolve())
    monkeypatch.setattr("app.config.settings", patched_settings)
    monkeypatch.setattr("app.imports.batch_folder.settings", patched_settings)


def test_batch_folder_endpoint_processes_pdf_and_reports_unsupported_csv(db_session, monkeypatch, tmp_path):
    batch_dir = tmp_path / "bank_files"
    batch_dir.mkdir()
    (batch_dir / "b-transactions.csv").write_text("date,amount\n2026-01-01,10\n", encoding="utf-8")
    (batch_dir / "A-statement.PDF").write_bytes(b"%PDF-1.7\nstub")
    _configure_batch_dir(monkeypatch, batch_dir)
    monkeypatch.setattr("app.imports.pdf_statement.read_pdf_page_text", lambda _: SANITIZED_BEOBANK_PAGE_TEXTS)
    seen_batch_statuses = []
    original_process_file = ImportBatchFolderService._process_file

    def wrapped_process_file(self, batch_run, item, file_path):
        seen_batch_statuses.append(batch_run.status)
        return original_process_file(self, batch_run, item, file_path)

    monkeypatch.setattr(ImportBatchFolderService, "_process_file", wrapped_process_file)

    response = client.post("/imports/batch-folder")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["message"] == "Batch import completed."
    assert payload["total_files"] == 2
    assert payload["processed_count"] == 1
    assert payload["skipped_existing_count"] == 0
    assert payload["unsupported_count"] == 1
    assert payload["failed_count"] == 0
    assert seen_batch_statuses == ["running", "running"]
    assert [item["filename"] for item in payload["items"]] == ["A-statement.PDF", "b-transactions.csv"]

    pdf_item, csv_item = payload["items"]
    assert pdf_item["id"] is not None
    assert pdf_item["status"] == "processed"
    assert pdf_item["session_id"] is not None
    assert pdf_item["session_status"] == "awaiting_review"
    assert pdf_item["existing_session_id"] is None
    assert pdf_item["strategy_key"] == "pdf_statement"
    assert pdf_item["extractor_id"] == "beobank_mastercard_pdf_v1"
    assert pdf_item["started_at"] is not None
    assert pdf_item["completed_at"] is not None

    assert csv_item["id"] is not None
    assert csv_item["status"] == "unsupported"
    assert csv_item["message"] == "Unsupported batch file type: .csv"
    assert csv_item["session_id"] is None
    assert csv_item["session_status"] is None
    assert csv_item["existing_session_id"] is None
    assert csv_item["existing_session_status"] is None
    assert csv_item["strategy_key"] is None
    assert csv_item["extractor_id"] is None
    assert csv_item["started_at"] is not None
    assert csv_item["completed_at"] is not None

    db_session.expire_all()
    assert db_session.query(ImportSession).count() == 1
    persisted_batch = db_session.get(ImportBatchRun, payload["id"])
    assert persisted_batch is not None
    assert db_session.query(ImportBatchItem).filter(ImportBatchItem.batch_run_id == payload["id"]).count() == 2

    persisted_response = client.get(f"/imports/batches/{payload['id']}")
    assert persisted_response.status_code == 200
    assert persisted_response.json()["id"] == payload["id"]
    assert persisted_response.json()["items"][0]["id"] == pdf_item["id"]


def test_batch_folder_latest_returns_persisted_failed_run(db_session):
    session = ImportSession(
        file_name="statement.pdf",
        file_hash="abc123",
        mime_type="application/pdf",
        status="failed",
    )
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)

    batch_run = ImportBatchRun(
        folder_path="/tmp/bank_files",
        status="failed",
        message="Batch import failed unexpectedly.",
        total_files=2,
        processed_count=1,
        skipped_existing_count=0,
        unsupported_count=0,
        failed_count=1,
        completed_at=datetime(2026, 4, 12, 9, 30, tzinfo=timezone.utc),
    )
    db_session.add(batch_run)
    db_session.commit()
    db_session.refresh(batch_run)

    batch_item = ImportBatchItem(
        batch_run_id=batch_run.id,
        filename="statement.pdf",
        file_hash="abc123",
        status="failed",
        message="The current file failed after batch creation.",
        session_id=session.id,
        session_status="failed",
        existing_session_id=None,
        existing_session_status=None,
        strategy_key="pdf_statement",
        extractor_id=None,
        started_at=datetime(2026, 4, 12, 9, 25, tzinfo=timezone.utc),
        completed_at=datetime(2026, 4, 12, 9, 30, tzinfo=timezone.utc),
    )
    db_session.add(batch_item)
    db_session.commit()

    response = client.get("/imports/batches/latest")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == batch_run.id
    assert payload["status"] == "failed"
    assert payload["message"] == "Batch import failed unexpectedly."
    assert payload["completed_at"] == "2026-04-12T09:30:00"
    assert payload["items"][0]["id"] == batch_item.id
    assert payload["items"][0]["filename"] == "statement.pdf"
    assert payload["items"][0]["status"] == "failed"
    assert payload["items"][0]["session_id"] == session.id
    assert payload["items"][0]["session_status"] == "failed"


def test_batch_folder_omits_unfinished_items_from_serialized_payload(db_session):
    batch_run = ImportBatchRun(
        folder_path="/tmp/bank_files",
        status="running",
        message=None,
        total_files=2,
        processed_count=0,
        skipped_existing_count=0,
        unsupported_count=0,
        failed_count=0,
    )
    db_session.add(batch_run)
    db_session.commit()
    db_session.refresh(batch_run)

    finished_item = ImportBatchItem(
        batch_run_id=batch_run.id,
        filename="finished.pdf",
        status="processed",
        started_at=datetime(2026, 4, 12, 9, 25, tzinfo=timezone.utc),
        completed_at=datetime(2026, 4, 12, 9, 30, tzinfo=timezone.utc),
    )
    unfinished_item = ImportBatchItem(
        batch_run_id=batch_run.id,
        filename="in-flight.pdf",
        status="failed",
        started_at=datetime(2026, 4, 12, 9, 31, tzinfo=timezone.utc),
        completed_at=None,
    )
    db_session.add_all([finished_item, unfinished_item])
    db_session.commit()

    response = client.get(f"/imports/batches/{batch_run.id}")

    assert response.status_code == 200
    payload = response.json()
    assert [item["filename"] for item in payload["items"]] == ["finished.pdf"]
    assert payload["items"][0]["id"] == finished_item.id
    assert payload["items"][0]["status"] == "processed"


def test_batch_folder_endpoint_rejects_missing_configured_folder(db_session, monkeypatch, tmp_path):
    missing_dir = tmp_path / "missing-bank-files"
    _configure_batch_dir(monkeypatch, missing_dir)

    response = client.post("/imports/batch-folder")

    assert response.status_code == 400
    assert response.json()["detail"] == f"Configured batch import folder does not exist: {missing_dir.resolve()}"


def test_batch_folder_marks_run_failed_when_outer_rescue_handles_pending_rollback(db_session, monkeypatch, tmp_path):
    batch_dir = tmp_path / "bank_files"
    batch_dir.mkdir()
    (batch_dir / "statement.pdf").write_bytes(b"%PDF-1.7\nstub")
    _configure_batch_dir(monkeypatch, batch_dir)
    monkeypatch.setattr("app.imports.pdf_statement.read_pdf_page_text", lambda _: SANITIZED_BEOBANK_PAGE_TEXTS)

    original_refresh_counts = ImportBatchFolderService._refresh_batch_counts
    triggered = {"raised": False}

    def crashing_refresh_counts(self, batch_run):
        if not triggered["raised"]:
            triggered["raised"] = True
            self.db.add(
                ImportBatchItem(
                    batch_run_id=999999,
                    filename="boom.pdf",
                    status="failed",
                )
            )
            self.db.commit()
        return original_refresh_counts(self, batch_run)

    monkeypatch.setattr(ImportBatchFolderService, "_refresh_batch_counts", crashing_refresh_counts)

    response = client.post("/imports/batch-folder")

    assert response.status_code == 500
    assert "FOREIGN KEY constraint failed" in response.json()["detail"]

    latest_response = client.get("/imports/batches/latest")
    assert latest_response.status_code == 200
    latest_payload = latest_response.json()
    assert latest_payload["status"] == "failed"
    assert latest_payload["completed_at"] is not None
    assert latest_payload["items"][0]["status"] == "processed"
    assert latest_payload["items"][0]["completed_at"] is not None

    db_session.rollback()
    db_session.expire_all()
    batch_run = db_session.query(ImportBatchRun).order_by(ImportBatchRun.id.desc()).one()
    assert batch_run.status == "failed"
    assert batch_run.completed_at is not None

    items = db_session.query(ImportBatchItem).filter(ImportBatchItem.batch_run_id == batch_run.id).all()
    assert len(items) == 1
    assert items[0].status == "processed"
    assert items[0].completed_at is not None


def test_batch_folder_marks_unsupported_strategy_session_failed_in_meta(db_session, monkeypatch, tmp_path):
    batch_dir = tmp_path / "bank_files"
    batch_dir.mkdir()
    (batch_dir / "statement.pdf").write_bytes(b"%PDF-1.7\nstub")
    _configure_batch_dir(monkeypatch, batch_dir)
    monkeypatch.setattr(
        "app.imports.detection.ImportDetector.detect",
        lambda self, **_: DetectionResult(strategy_key=ImportStrategyKey.UNKNOWN),
    )

    response = client.post("/imports/batch-folder")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["failed_count"] == 1
    item = payload["items"][0]
    assert item["status"] == "failed"
    assert item["strategy_key"] == "unknown"
    assert item["session_id"] is not None
    assert item["session_status"] == "failed"

    meta_path = config_module.settings.imports_dir / str(item["session_id"]) / "meta.json"
    meta_payload = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta_payload["state"] == "failed"
    assert "failed" in meta_payload["stage_timestamps"]
