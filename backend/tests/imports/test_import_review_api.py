import hashlib

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.models.imports import ImportIssue, ImportSession, ImportStatementDraft
from app.models.statistics import FinancialStatistics, StatisticsPeriod
from app.models.transaction import Transaction, TransactionType
from app.imports.state_machine import ImportSessionStatus
from tests.imports.fixtures.beobank_mastercard_pages import SANITIZED_BEOBANK_PAGE_TEXTS


client = TestClient(app)


def _upload_pdf(monkeypatch, page_texts, *, file_bytes=b"%PDF-1.7\nstub", expected_status=200):
    monkeypatch.setattr("app.imports.pdf_statement.read_pdf_page_text", lambda _: page_texts)
    response = client.post(
        "/imports/upload",
        files={"file": ("statement.pdf", file_bytes, "application/pdf")},
    )
    assert response.status_code == expected_status
    return response.json()


def test_upload_endpoint_returns_reviewable_session_shape(db_session, monkeypatch):
    payload = _upload_pdf(monkeypatch, SANITIZED_BEOBANK_PAGE_TEXTS)

    assert payload["status"] == "awaiting_review"
    assert payload["strategy_key"] == "pdf_statement"
    assert payload["attempt_count"] == 1
    assert payload["extractor_id"] == "beobank_mastercard_pdf_v1"
    assert payload["error_stage"] is None
    assert payload["error_message"] is None


def test_upload_endpoint_returns_failed_session_shape_when_extraction_is_not_reviewable(db_session, monkeypatch):
    payload = _upload_pdf(
        monkeypatch,
        [
            "Uittreksel van uw kredietkaart\nPeriode 15/12/2025 - 14/01/2026\n",
            "Some other bank\n21/12/2025 SHOP 12,34\n",
        ],
    )

    assert payload["status"] == "failed"
    assert payload["strategy_key"] == "pdf_statement"
    assert payload["attempt_count"] == 1
    assert payload["error_stage"] == "extraction"
    assert "supported Beobank Mastercard layout" in payload["error_message"]


def test_upload_endpoint_returns_duplicate_conflict_for_usable_existing_pdf_session(db_session, monkeypatch):
    first_session = _upload_pdf(monkeypatch, SANITIZED_BEOBANK_PAGE_TEXTS)

    response = client.post(
        "/imports/upload",
        files={"file": ("statement.pdf", b"%PDF-1.7\nstub", "application/pdf")},
    )

    assert response.status_code == 409
    payload = response.json()
    expected_file_hash = hashlib.sha256(b"%PDF-1.7\nstub").hexdigest()
    assert payload["message"] == "Import session with this file hash already exists."
    assert payload["file_hash"] == expected_file_hash
    assert payload["existing_session"]["id"] == first_session["id"]
    assert payload["existing_session"]["status"] == "awaiting_review"


def test_upload_endpoint_replaces_non_retryable_existing_pdf_session(db_session, monkeypatch):
    first_session = _upload_pdf(monkeypatch, SANITIZED_BEOBANK_PAGE_TEXTS)
    persisted_session = db_session.get(ImportSession, first_session["id"])
    persisted_session.status = ImportSessionStatus.FAILED.value
    db_session.commit()

    original_file = settings.imports_dir / str(first_session["id"]) / "original" / "statement.pdf"
    original_file.unlink()

    response = client.post(
        "/imports/upload",
        files={"file": ("statement.pdf", b"%PDF-1.7\nstub", "application/pdf")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] != first_session["id"]
    assert payload["status"] == "awaiting_review"

    db_session.expire_all()
    replaced_session = db_session.get(ImportSession, first_session["id"])
    new_session = db_session.get(ImportSession, payload["id"])
    expected_file_hash = hashlib.sha256(b"%PDF-1.7\nstub").hexdigest()
    assert replaced_session.file_hash == f"{expected_file_hash}#legacy-duplicate#{first_session['id']}"
    assert replaced_session.status == ImportSessionStatus.SUPERSEDED.value
    assert new_session.file_hash == expected_file_hash


def test_get_review_payload_returns_statement_transactions_issues_and_evidence(db_session, monkeypatch):
    session = _upload_pdf(monkeypatch, SANITIZED_BEOBANK_PAGE_TEXTS)

    response = client.get(f"/imports/{session['id']}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["session"]["id"] == session["id"]
    assert payload["session"]["status"] == "awaiting_review"
    assert payload["statement"]["attempt_number"] == 1
    assert payload["statement"]["card_number_hint"] == "xxxx xxxx xxxx 1111"
    assert payload["statement"]["currency"] == "EUR"
    assert len(payload["transactions"]) == 5
    assert payload["transactions"][0]["source_locator"] == "pdf:p2:l4"
    assert payload["transactions"][0]["raw_fields"]["source_locator"] == "pdf:p2:l4"
    assert payload["issues"] == []
    assert payload["evidence"]["text_blocks"][0]["page_number"] == 1


def test_get_review_payload_for_failed_session_returns_issues_and_evidence_without_statement(db_session, monkeypatch):
    session = _upload_pdf(
        monkeypatch,
        [
            "Uittreksel van uw kredietkaart\nPeriode 15/12/2025 - 14/01/2026\n",
            "Some other bank\n21/12/2025 SHOP 12,34\n",
        ],
    )

    response = client.get(f"/imports/{session['id']}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["session"]["status"] == "failed"
    assert payload["statement"] is None
    assert payload["transactions"] == []
    assert payload["issues"][0]["issue_code"] == "unsupported_beobank_mastercard_layout"
    assert payload["evidence"]["text_blocks"][0]["raw_text"].startswith("Uittreksel")


def test_approve_commits_transactions_with_traceability_and_updates_statistics(db_session, monkeypatch):
    session = _upload_pdf(monkeypatch, SANITIZED_BEOBANK_PAGE_TEXTS)

    response = client.post(f"/imports/{session['id']}/approve")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == session["id"]
    assert payload["status"] == "committed"
    assert payload["attempt_count"] == 1

    db_session.expire_all()
    committed_transactions = db_session.query(Transaction).order_by(Transaction.id).all()
    assert len(committed_transactions) == 5

    first_transaction = committed_transactions[0]
    assert first_transaction.import_session_id == session["id"]
    assert first_transaction.account_number == "xxxx xxxx xxxx 1111"
    assert first_transaction.transaction_date.isoformat() == "2025-12-20"
    assert first_transaction.amount == -18.19
    assert first_transaction.currency == "EUR"
    assert first_transaction.description == "MERCADO EXTRA-1776 PRAIA GRANDE BR"
    assert first_transaction.counterparty_name is None
    assert first_transaction.counterparty_account is None
    assert first_transaction.import_source_locator == "pdf:p2:l4"
    assert first_transaction.import_source_description == "MERCADO EXTRA-1776 PRAIA GRANDE BR"
    assert first_transaction.canonical_description_en is None
    assert first_transaction.transaction_type == TransactionType.EXPENSE
    assert first_transaction.classification_source is None
    assert first_transaction.source_bank == "Beobank"

    all_time_stats = (
        db_session.query(FinancialStatistics)
        .filter(FinancialStatistics.period == StatisticsPeriod.ALL_TIME)
        .one()
    )
    expected_expense_count = sum(
        1 for transaction in committed_transactions if transaction.transaction_type == TransactionType.EXPENSE
    )
    expected_total_expenses = sum(
        abs(transaction.amount)
        for transaction in committed_transactions
        if transaction.transaction_type == TransactionType.EXPENSE
    )
    assert all_time_stats.expense_count == expected_expense_count
    assert all_time_stats.total_expenses == expected_total_expenses

    persisted_session = db_session.get(ImportSession, session["id"])
    statement_draft = db_session.query(ImportStatementDraft).filter_by(import_session_id=session["id"]).one()
    assert persisted_session.status == "committed"
    assert statement_draft.review_status == "approved"


def test_approve_returns_conflict_when_any_committed_transaction_would_duplicate(db_session, monkeypatch):
    first_session = _upload_pdf(monkeypatch, SANITIZED_BEOBANK_PAGE_TEXTS)
    first_response = client.post(f"/imports/{first_session['id']}/approve")
    assert first_response.status_code == 200

    duplicate_session = _upload_pdf(
        monkeypatch,
        SANITIZED_BEOBANK_PAGE_TEXTS,
        file_bytes=b"%PDF-1.7\nstub-approval-conflict",
    )

    response = client.post(f"/imports/{duplicate_session['id']}/approve")

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["message"] == "Approval would create duplicate committed transactions."
    assert detail["duplicates"][0]["source_description"] == "MERCADO EXTRA-1776 PRAIA GRANDE BR"

    db_session.expire_all()
    assert db_session.query(Transaction).count() == 5
    assert db_session.get(ImportSession, duplicate_session["id"]).status == "awaiting_review"


def test_approve_returns_conflict_when_latest_attempt_has_blocking_issue(db_session, monkeypatch):
    session = _upload_pdf(monkeypatch, SANITIZED_BEOBANK_PAGE_TEXTS)
    db_session.add(
        ImportIssue(
            import_session_id=session["id"],
            attempt_number=1,
            severity="error",
            blocking=True,
            issue_code="blocking_regression",
            issue_message="Blocking issue requires manual resolution before approval.",
            transaction_ref="pdf:p2:l4",
        )
    )
    db_session.commit()

    response = client.post(f"/imports/{session['id']}/approve")

    assert response.status_code == 409
    assert "blocking issues" in response.json()["detail"]
    db_session.expire_all()
    statement_draft = db_session.query(ImportStatementDraft).filter_by(import_session_id=session["id"]).one()
    assert db_session.get(ImportSession, session["id"]).status == "awaiting_review"
    assert statement_draft.review_status == "awaiting_review"
    assert db_session.query(Transaction).count() == 0


def test_reject_moves_session_to_rejected(db_session, monkeypatch):
    session = _upload_pdf(monkeypatch, SANITIZED_BEOBANK_PAGE_TEXTS)

    response = client.post(f"/imports/{session['id']}/reject")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == session["id"]
    assert payload["status"] == "rejected"

    db_session.expire_all()
    statement_draft = db_session.query(ImportStatementDraft).filter_by(import_session_id=session["id"]).one()
    assert db_session.get(ImportSession, session["id"]).status == "rejected"
    assert statement_draft.review_status == "rejected"


def test_retry_reextracts_same_session_and_increments_attempt_number(db_session, monkeypatch):
    session = _upload_pdf(monkeypatch, SANITIZED_BEOBANK_PAGE_TEXTS)

    response = client.post(f"/imports/{session['id']}/retry")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == session["id"]
    assert payload["status"] == "awaiting_review"
    assert payload["attempt_count"] == 2

    db_session.expire_all()
    statements = (
        db_session.query(ImportStatementDraft)
        .filter(ImportStatementDraft.import_session_id == session["id"])
        .order_by(ImportStatementDraft.attempt_number.asc())
        .all()
    )
    assert [statement.attempt_number for statement in statements] == [1, 2]
    assert statements[0].review_status == "superseded"
    assert statements[1].review_status == "awaiting_review"

    review_response = client.get(f"/imports/{session['id']}")
    review_payload = review_response.json()
    assert review_payload["session"]["attempt_count"] == 2
    assert review_payload["statement"]["attempt_number"] == 2
