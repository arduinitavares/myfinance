import json

import pytest

from app.config import settings
from app.imports.artifacts import ArtifactStore
from app.imports.contracts import ExtractionResult, RawEvidence
from app.imports.pipeline import ImportPipelineService
from app.imports.state_machine import ImportSessionStatus
from app.imports.workflow import ImportApprovalConflictError, ImportSessionStateError, ImportWorkflowService
from app.models.imports import ImportIssue, ImportSession, ImportStatementDraft, ImportTransactionDraft
from app.models.transaction import Transaction
from tests.imports.fixtures.beobank_mastercard_pages import SANITIZED_BEOBANK_PAGE_TEXTS


def _successful_result(session_id: int, attempt_number: int) -> tuple[RawEvidence, ExtractionResult]:
    return (
        RawEvidence(
            text_blocks=[{"page_number": 1, "raw_text": "BEOBANK\nMASTERCARD\n", "lines": ["BEOBANK", "MASTERCARD"]}],
            ocr_blocks=[],
            snippets=[],
        ),
        ExtractionResult(
            extractor_id="beobank_mastercard_pdf_v1",
            raw_artifact_ref=f"imports/{session_id}/attempts/{attempt_number}/evidence/raw.json",
            source_metadata={"provider_hint": "beobank", "file_type": "pdf"},
            statement_metadata={
                "statement_period_start": "2025-12-15",
                "statement_period_end": "2026-01-14",
                "card_number_hint": "xxxx xxxx xxxx 1111",
                "currency": "EUR",
            },
            transactions=[],
            issues=[],
            overall_confidence=1.0,
        ),
    )


def test_extract_detected_session_moves_pdf_statement_to_awaiting_review_and_persists_drafts(
    db_session, monkeypatch
):
    monkeypatch.setattr("app.imports.pdf_statement.read_pdf_page_text", lambda _: SANITIZED_BEOBANK_PAGE_TEXTS)
    session, _ = ImportPipelineService(db_session).start_upload(
        filename="statement.pdf",
        content_type="application/pdf",
        file_bytes=b"%PDF-1.7\nstub",
    )

    extracted_session = ImportWorkflowService(db_session).extract_detected_session(session.id)

    assert extracted_session.status == ImportSessionStatus.AWAITING_REVIEW.value
    assert extracted_session.extractor_id == "beobank_mastercard_pdf_v1"
    assert extracted_session.raw_artifact_ref == f"imports/{session.id}/attempts/1/evidence/raw.json"

    statement_draft = db_session.query(ImportStatementDraft).one()
    assert statement_draft.import_session_id == session.id
    assert statement_draft.attempt_number == 1
    assert statement_draft.statement_period_start.isoformat() == "2025-12-15"
    assert statement_draft.statement_period_end.isoformat() == "2026-01-14"
    assert statement_draft.card_number_hint == "xxxx xxxx xxxx 1111"
    assert statement_draft.currency == "EUR"
    assert statement_draft.transaction_count == 5
    assert statement_draft.review_status == "awaiting_review"

    transaction_drafts = db_session.query(ImportTransactionDraft).order_by(ImportTransactionDraft.id).all()
    assert len(transaction_drafts) == 5
    assert transaction_drafts[0].transaction_date.isoformat() == "2025-12-20"
    assert transaction_drafts[0].source_description == "MERCADO EXTRA-1776 PRAIA GRANDE BR"
    assert transaction_drafts[0].signed_amount == -18.19
    assert transaction_drafts[0].currency == "EUR"
    assert transaction_drafts[0].debit_credit == "debit"
    assert transaction_drafts[0].source_locator == "pdf:p2:l4"
    assert transaction_drafts[0].edit_source == "deterministic_extracted"
    assert json.loads(transaction_drafts[0].field_confidence) == {}
    assert json.loads(transaction_drafts[0].raw_fields)["source_locator"] == "pdf:p2:l4"

    assert db_session.query(ImportIssue).count() == 0

    attempt_dir = settings.imports_dir / str(session.id) / "attempts" / "1"
    raw_payload = json.loads((attempt_dir / "evidence" / "raw.json").read_text(encoding="utf-8"))
    normalized_payload = json.loads(
        (attempt_dir / "normalized" / "extraction_result.json").read_text(encoding="utf-8")
    )

    assert raw_payload["text_blocks"][0] == {
        "page_number": 1,
        "raw_text": SANITIZED_BEOBANK_PAGE_TEXTS[0],
        "lines": [
            "BEOBANK",
            "MASTERCARD",
            "Uittreksel van uw kredietkaart",
            "Periode 15/12/2025 - 14/01/2026",
            "15/12/2025 Vorig saldo 999,99",
        ],
    }
    assert normalized_payload["extractor_id"] == "beobank_mastercard_pdf_v1"
    assert normalized_payload["raw_artifact_ref"] == f"imports/{session.id}/attempts/1/evidence/raw.json"
    assert not (attempt_dir / "ai" / "request.json").exists()
    assert not (attempt_dir / "ai" / "response.json").exists()

    meta_payload = json.loads((settings.imports_dir / str(session.id) / "meta.json").read_text(encoding="utf-8"))
    assert meta_payload["state"] == ImportSessionStatus.AWAITING_REVIEW.value
    assert meta_payload["attempt_count"] == 1


def test_extract_detected_session_fails_closed_on_unsupported_layout(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.imports.pdf_statement.read_pdf_page_text",
        lambda _: [
            "Uittreksel van uw kredietkaart\nPeriode 15/12/2025 - 14/01/2026\n",
            "Some other bank\n21/12/2025 SHOP 12,34\n",
        ],
    )
    session, _ = ImportPipelineService(db_session).start_upload(
        filename="statement.pdf",
        content_type="application/pdf",
        file_bytes=b"%PDF-1.7\nstub",
    )

    extracted_session = ImportWorkflowService(db_session).extract_detected_session(session.id)

    assert extracted_session.status == ImportSessionStatus.FAILED.value
    issues = db_session.query(ImportIssue).all()
    assert [(issue.issue_code, issue.blocking, issue.severity) for issue in issues] == [
        ("unsupported_beobank_mastercard_layout", True, "error")
    ]
    assert db_session.query(ImportStatementDraft).count() == 0
    assert db_session.query(ImportTransactionDraft).count() == 0

    attempt_dir = settings.imports_dir / str(session.id) / "attempts" / "1"
    assert (attempt_dir / "evidence" / "raw.json").exists()
    assert (attempt_dir / "normalized" / "extraction_result.json").exists()
    meta_payload = json.loads((settings.imports_dir / str(session.id) / "meta.json").read_text(encoding="utf-8"))
    assert meta_payload["state"] == ImportSessionStatus.FAILED.value
    assert meta_payload["attempt_count"] == 1


def test_extract_detected_session_fails_closed_on_parser_blocking_issue(db_session, monkeypatch):
    broken_pages = list(SANITIZED_BEOBANK_PAGE_TEXTS)
    broken_pages[2] = "Kaart xxxx xxxx xxxx 1111\nUw transacties\n21/12/2025 ONLINE SHOP BRUSSEL BE 1.234,56\n"
    monkeypatch.setattr("app.imports.pdf_statement.read_pdf_page_text", lambda _: broken_pages)
    session, _ = ImportPipelineService(db_session).start_upload(
        filename="statement.pdf",
        content_type="application/pdf",
        file_bytes=b"%PDF-1.7\nstub",
    )

    extracted_session = ImportWorkflowService(db_session).extract_detected_session(session.id)

    assert extracted_session.status == ImportSessionStatus.FAILED.value
    issues = db_session.query(ImportIssue).order_by(ImportIssue.id).all()
    assert any(issue.issue_code == "unclassifiable_table_line" and issue.blocking for issue in issues)
    assert db_session.query(ImportStatementDraft).count() == 0
    assert db_session.query(ImportTransactionDraft).count() == 0


def test_extract_detected_session_uses_new_attempt_number_after_rolled_back_artifact_write(db_session):
    class StubExtractor:
        def __init__(self):
            self.calls = 0

        def extract(self, *, file_path, session_id, attempt_number):
            self.calls += 1
            return _successful_result(int(session_id), attempt_number)

    class FlakyArtifactStore(ArtifactStore):
        def __init__(self):
            super().__init__()
            self.write_normalized_calls = 0

        def write_normalized_result(self, session_id: str, attempt_number: int, result: ExtractionResult) -> None:
            super().write_normalized_result(session_id, attempt_number, result)
            self.write_normalized_calls += 1
            if self.write_normalized_calls == 1:
                raise RuntimeError("normalized write follow-up failed")

    session, _ = ImportPipelineService(db_session).start_upload(
        filename="statement.pdf",
        content_type="application/pdf",
        file_bytes=b"%PDF-1.7\nstub",
    )
    extractor = StubExtractor()
    artifacts = FlakyArtifactStore()
    service = ImportWorkflowService(db_session, pdf_statement_extractor=extractor, artifacts=artifacts)

    with pytest.raises(RuntimeError, match="normalized write follow-up failed"):
        service.extract_detected_session(session.id)

    first_attempt_dir = settings.imports_dir / str(session.id) / "attempts" / "1"
    assert (first_attempt_dir / "evidence" / "raw.json").exists()
    assert (first_attempt_dir / "normalized" / "extraction_result.json").exists()

    failed_session = db_session.get(ImportSession, session.id)
    failed_session.status = ImportSessionStatus.DETECTED.value
    failed_session.error_stage = None
    failed_session.error_message = None
    db_session.commit()

    retried_session = service.extract_detected_session(session.id)

    assert retried_session.status == ImportSessionStatus.AWAITING_REVIEW.value
    assert retried_session.raw_artifact_ref == f"imports/{session.id}/attempts/2/evidence/raw.json"
    second_attempt_dir = settings.imports_dir / str(session.id) / "attempts" / "2"
    assert (second_attempt_dir / "evidence" / "raw.json").exists()
    assert (second_attempt_dir / "normalized" / "extraction_result.json").exists()

    statement_draft = db_session.query(ImportStatementDraft).one()
    assert statement_draft.attempt_number == 2

    meta_payload = json.loads((settings.imports_dir / str(session.id) / "meta.json").read_text(encoding="utf-8"))
    assert meta_payload["state"] == ImportSessionStatus.AWAITING_REVIEW.value
    assert meta_payload["attempt_count"] == 2


def test_extract_detected_session_clears_stale_refs_when_retry_crashes_before_new_result(db_session):
    class CrashingExtractor:
        def extract(self, *, file_path, session_id, attempt_number):
            raise RuntimeError("pdf extraction crashed")

    session, _ = ImportPipelineService(db_session).start_upload(
        filename="statement.pdf",
        content_type="application/pdf",
        file_bytes=b"%PDF-1.7\nstub",
    )
    persisted_session = db_session.get(ImportSession, session.id)
    persisted_session.extractor_id = "stale_extractor"
    persisted_session.raw_artifact_ref = "imports/999/attempts/9/evidence/raw.json"
    db_session.commit()

    with pytest.raises(RuntimeError, match="pdf extraction crashed"):
        ImportWorkflowService(db_session, pdf_statement_extractor=CrashingExtractor()).extract_detected_session(session.id)

    failed_session = db_session.get(ImportSession, session.id)
    assert failed_session.status == ImportSessionStatus.FAILED.value
    assert failed_session.extractor_id is None
    assert failed_session.raw_artifact_ref is None

    meta_payload = json.loads((settings.imports_dir / str(session.id) / "meta.json").read_text(encoding="utf-8"))
    assert meta_payload["state"] == ImportSessionStatus.FAILED.value
    assert meta_payload["attempt_count"] == 1


def test_extract_detected_session_still_marks_failed_when_manifest_sync_blows_up_in_rescue(db_session):
    class CrashingExtractor:
        def extract(self, *, file_path, session_id, attempt_number):
            raise RuntimeError("pdf extraction crashed")

    class BrokenManifestArtifactStore(ArtifactStore):
        def read_meta(self, session_id: str) -> dict:
            raise RuntimeError("manifest sync crashed")

    session, _ = ImportPipelineService(db_session).start_upload(
        filename="statement.pdf",
        content_type="application/pdf",
        file_bytes=b"%PDF-1.7\nstub",
    )
    persisted_session = db_session.get(ImportSession, session.id)
    persisted_session.extractor_id = "stale_extractor"
    persisted_session.raw_artifact_ref = "imports/999/attempts/9/evidence/raw.json"
    db_session.commit()

    with pytest.raises(RuntimeError, match="pdf extraction crashed"):
        ImportWorkflowService(
            db_session,
            pdf_statement_extractor=CrashingExtractor(),
            artifacts=BrokenManifestArtifactStore(),
        ).extract_detected_session(session.id)

    failed_session = db_session.get(ImportSession, session.id)
    assert failed_session.status == ImportSessionStatus.FAILED.value
    assert failed_session.error_stage == "extraction"
    assert failed_session.error_message == "pdf extraction crashed"
    assert failed_session.extractor_id is None
    assert failed_session.raw_artifact_ref is None


def test_retry_failed_session_without_attempt_artifacts_uses_next_attempt_number(db_session):
    class StubExtractor:
        def extract(self, *, file_path, session_id, attempt_number):
            return _successful_result(int(session_id), attempt_number)

    session, _ = ImportPipelineService(db_session).start_upload(
        filename="statement.pdf",
        content_type="application/pdf",
        file_bytes=b"%PDF-1.7\nstub",
    )
    persisted_session = db_session.get(ImportSession, session.id)
    persisted_session.status = ImportSessionStatus.FAILED.value
    persisted_session.error_stage = "extraction"
    persisted_session.error_message = "first attempt failed before artifacts"
    db_session.commit()

    meta_path = settings.imports_dir / str(session.id) / "meta.json"
    meta_payload = json.loads(meta_path.read_text(encoding="utf-8"))
    meta_payload["state"] = ImportSessionStatus.FAILED.value
    meta_payload["attempt_count"] = 1
    meta_payload["stage_timestamps"]["failed"] = "2026-04-12T10:00:00+00:00"
    meta_path.write_text(json.dumps(meta_payload, indent=2, sort_keys=True), encoding="utf-8")

    retried_session = ImportWorkflowService(
        db_session,
        pdf_statement_extractor=StubExtractor(),
    ).retry_session(session.id)

    assert retried_session.status == ImportSessionStatus.AWAITING_REVIEW.value
    assert retried_session.raw_artifact_ref == f"imports/{session.id}/attempts/2/evidence/raw.json"

    statement_draft = db_session.query(ImportStatementDraft).one()
    assert statement_draft.attempt_number == 2

    attempt_dir = settings.imports_dir / str(session.id) / "attempts" / "2"
    assert (attempt_dir / "evidence" / "raw.json").exists()
    assert (attempt_dir / "normalized" / "extraction_result.json").exists()

    updated_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert updated_meta["attempt_count"] == 2
    assert updated_meta["state"] == ImportSessionStatus.AWAITING_REVIEW.value


@pytest.mark.parametrize(
    ("operation_name", "prepare_session", "expected_status"),
    [
        (
            "approve",
            lambda session: None,
            ImportSessionStatus.AWAITING_REVIEW.value,
        ),
        (
            "reject",
            lambda session: None,
            ImportSessionStatus.AWAITING_REVIEW.value,
        ),
        (
            "retry",
            lambda session: None,
            ImportSessionStatus.AWAITING_REVIEW.value,
        ),
    ],
)
def test_review_state_meta_does_not_advance_when_db_commit_fails(
    db_session, monkeypatch, operation_name, prepare_session, expected_status
):
    monkeypatch.setattr("app.imports.pdf_statement.read_pdf_page_text", lambda _: SANITIZED_BEOBANK_PAGE_TEXTS)
    session, _ = ImportPipelineService(db_session).start_upload(
        filename="statement.pdf",
        content_type="application/pdf",
        file_bytes=b"%PDF-1.7\nstub",
    )
    ImportWorkflowService(db_session).extract_detected_session(session.id)
    prepare_session(session)

    meta_path = settings.imports_dir / str(session.id) / "meta.json"
    before_meta = json.loads(meta_path.read_text(encoding="utf-8"))

    original_commit = db_session.commit
    commit_calls = {"count": 0}

    def fail_first_commit():
        commit_calls["count"] += 1
        if commit_calls["count"] == 1:
            raise RuntimeError("db commit failed")
        return original_commit()

    monkeypatch.setattr(db_session, "commit", fail_first_commit)
    service = ImportWorkflowService(db_session)

    with pytest.raises(RuntimeError, match="db commit failed"):
        if operation_name == "approve":
            service.approve_session(session.id)
        elif operation_name == "reject":
            service.reject_session(session.id)
        else:
            service.retry_session(session.id)

    db_session.expire_all()
    persisted_session = db_session.get(ImportSession, session.id)
    after_meta = json.loads(meta_path.read_text(encoding="utf-8"))

    assert persisted_session.status == expected_status
    assert after_meta == before_meta
    assert commit_calls["count"] == 1

    if operation_name == "approve":
        assert db_session.query(Transaction).count() == 0


def test_approve_session_rejects_duplicate_committed_transactions(db_session, monkeypatch):
    monkeypatch.setattr("app.imports.pdf_statement.read_pdf_page_text", lambda _: SANITIZED_BEOBANK_PAGE_TEXTS)

    first_session, _ = ImportPipelineService(db_session).start_upload(
        filename="statement.pdf",
        content_type="application/pdf",
        file_bytes=b"%PDF-1.7\nstub",
    )
    ImportWorkflowService(db_session).extract_detected_session(first_session.id)
    ImportWorkflowService(db_session).approve_session(first_session.id)

    duplicate_session, _ = ImportPipelineService(db_session).start_upload(
        filename="statement.pdf",
        content_type="application/pdf",
        file_bytes=b"%PDF-1.7\nstub",
    )
    ImportWorkflowService(db_session).extract_detected_session(duplicate_session.id)

    with pytest.raises(ImportApprovalConflictError) as exc_info:
        ImportWorkflowService(db_session).approve_session(duplicate_session.id)

    assert exc_info.value.duplicates[0]["source_description"] == "MERCADO EXTRA-1776 PRAIA GRANDE BR"
    db_session.expire_all()
    assert db_session.query(Transaction).count() == 5
    assert db_session.get(ImportSession, duplicate_session.id).status == ImportSessionStatus.AWAITING_REVIEW.value


def test_approve_session_rejects_awaiting_review_session_with_blocking_issue(db_session, monkeypatch):
    monkeypatch.setattr("app.imports.pdf_statement.read_pdf_page_text", lambda _: SANITIZED_BEOBANK_PAGE_TEXTS)
    session, _ = ImportPipelineService(db_session).start_upload(
        filename="statement.pdf",
        content_type="application/pdf",
        file_bytes=b"%PDF-1.7\nstub",
    )
    ImportWorkflowService(db_session).extract_detected_session(session.id)

    db_session.add(
        ImportIssue(
            import_session_id=session.id,
            attempt_number=1,
            severity="error",
            blocking=True,
            issue_code="blocking_regression",
            issue_message="Blocking issue requires manual resolution before approval.",
            transaction_ref="pdf:p2:l4",
        )
    )
    db_session.commit()

    with pytest.raises(ImportSessionStateError, match="blocking issues"):
        ImportWorkflowService(db_session).approve_session(session.id)

    db_session.expire_all()
    statement_draft = db_session.query(ImportStatementDraft).filter_by(import_session_id=session.id).one()
    assert db_session.get(ImportSession, session.id).status == ImportSessionStatus.AWAITING_REVIEW.value
    assert statement_draft.review_status == "awaiting_review"
    assert db_session.query(Transaction).count() == 0


def test_approve_session_rolls_back_when_statistics_refresh_fails(db_session, monkeypatch):
    monkeypatch.setattr("app.imports.pdf_statement.read_pdf_page_text", lambda _: SANITIZED_BEOBANK_PAGE_TEXTS)
    session, _ = ImportPipelineService(db_session).start_upload(
        filename="statement.pdf",
        content_type="application/pdf",
        file_bytes=b"%PDF-1.7\nstub",
    )
    ImportWorkflowService(db_session).extract_detected_session(session.id)

    def explode(*args, **kwargs):
        raise RuntimeError("statistics refresh failed")

    monkeypatch.setattr("app.imports.workflow.StatisticsService.calculate_statistics", explode)

    meta_path = settings.imports_dir / str(session.id) / "meta.json"
    before_meta = json.loads(meta_path.read_text(encoding="utf-8"))

    with pytest.raises(RuntimeError, match="statistics refresh failed"):
        ImportWorkflowService(db_session).approve_session(session.id)

    db_session.expire_all()
    persisted_session = db_session.get(ImportSession, session.id)
    statement_draft = db_session.query(ImportStatementDraft).one()

    assert persisted_session.status == ImportSessionStatus.AWAITING_REVIEW.value
    assert statement_draft.review_status == "awaiting_review"
    assert db_session.query(Transaction).count() == 0
    assert json.loads(meta_path.read_text(encoding="utf-8")) == before_meta


def test_retry_failed_session_marks_failed_when_original_upload_is_missing(db_session):
    session, _ = ImportPipelineService(db_session).start_upload(
        filename="statement.pdf",
        content_type="application/pdf",
        file_bytes=b"%PDF-1.7\nstub",
    )
    persisted_session = db_session.get(ImportSession, session.id)
    persisted_session.status = ImportSessionStatus.FAILED.value
    persisted_session.error_stage = "extraction"
    persisted_session.error_message = "previous extraction failed"
    db_session.commit()

    meta_path = settings.imports_dir / str(session.id) / "meta.json"
    meta_payload = json.loads(meta_path.read_text(encoding="utf-8"))
    meta_payload["state"] = ImportSessionStatus.FAILED.value
    meta_payload["attempt_count"] = 1
    meta_payload["stage_timestamps"]["failed"] = "2026-04-12T11:00:00+00:00"
    meta_path.write_text(json.dumps(meta_payload, indent=2, sort_keys=True), encoding="utf-8")

    original_file = settings.imports_dir / str(session.id) / "original" / session.file_name
    original_file.unlink()

    with pytest.raises(FileNotFoundError, match=f"Original upload missing for import session {session.id}"):
        ImportWorkflowService(db_session).retry_session(session.id)

    db_session.expire_all()
    failed_session = db_session.get(ImportSession, session.id)
    meta_payload = json.loads(meta_path.read_text(encoding="utf-8"))

    assert failed_session.status == ImportSessionStatus.FAILED.value
    assert failed_session.error_stage == "extraction"
    assert failed_session.error_message == f"Original upload missing for import session {session.id}."
    assert meta_payload["state"] == ImportSessionStatus.FAILED.value
    assert meta_payload["attempt_count"] == 2
