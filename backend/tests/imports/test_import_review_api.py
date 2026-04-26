"""Module for backend tests imports test_import_review_api."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
from app.config import settings
from app.imports.state_machine import ImportSessionStatus
from app.main import app
from app.models.fx import FXDailyReferenceRate
from app.models.imports import (
    ImportIssue,
    ImportSession,
    ImportStatementDraft,
    ImportTransactionDraft,
)
from app.models.statistics import FinancialStatistics, StatisticsPeriod
from app.models.transaction import (
    ExpenseCategory,
    Transaction,
    TransactionType,
    TransferCategory,
)
from app.routers import imports as imports_router
from app.services.ecb_exchange_rates import (
    FXConversionCoverageRequest,
    FXConversionCoverageResult,
    FXConversionCoverageStatus,
)
from fastapi.testclient import TestClient
from tests.imports.fixtures.beobank_mastercard_pages import SANITIZED_BEOBANK_PAGE_TEXTS
from tests.imports.fixtures.nexo_csv import build_nexo_csv_bytes, nexo_row

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session

HTTP_OK: int = 200
HTTP_CONFLICT: int = 409
EXPECTED_REVIEW_TRANSACTION_COUNT: int = 5
EXPECTED_NEXO_TRANSACTION_COUNT: int = 3
REVIEW_RECURRENCE_PATTERN_ID: int = 17
RETRY_ATTEMPT_COUNT: int = 2
EUR_TRANSACTION_AMOUNT: float = -18.19
USD_DISPLAY_AMOUNT: float = -21.83
USD_DISPLAY_RATE: float = 1.2
NEXO_EUR_DISPLAY_AMOUNT: float = -9.87
EUR_PER_USD_RATE: float = 0.8

client: TestClient = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_upload_rate_limit() -> Iterator[None]:
    imports_router._upload_attempts.clear()
    yield
    imports_router._upload_attempts.clear()


def _store_rate(
    db_session: Session,
    *,
    rate_date: date,
    quoted_currency: str,
    units_per_base: str,
) -> None:
    db_session.add(
        FXDailyReferenceRate(
            rate_date=rate_date,
            base_currency="EUR",
            quoted_currency=quoted_currency,
            units_per_base=Decimal(units_per_base),
            source_name="ECB_EXR",
            fetched_at=datetime(2026, 4, 17, 8, 30, tzinfo=UTC),
            updated_at=datetime(2026, 4, 17, 8, 30, tzinfo=UTC),
        )
    )
    db_session.commit()


def _upload_pdf(
    monkeypatch: pytest.MonkeyPatch,
    page_texts: list[str],
    *,
    file_bytes: bytes = b"%PDF-1.7\nstub",
    expected_status: int = HTTP_OK,
) -> dict[str, Any]:
    monkeypatch.setattr(
        "app.imports.pdf_statement.read_pdf_page_text", lambda _: page_texts
    )
    response = client.post(
        "/imports/upload",
        files={"file": ("statement.pdf", file_bytes, "application/pdf")},
    )
    assert response.status_code == expected_status
    return response.json()


def _upload_nexo_csv(*, expected_status: int = HTTP_OK) -> dict[str, Any]:
    response = client.post(
        "/imports/upload",
        files={
            "file": (
                "nexo.csv",
                build_nexo_csv_bytes(
                    nexo_row(
                        "NXT1001",
                        "Nexo Card Purchase",
                        "xUSD",
                        "-12.34",
                        "approved / Coffee Shop",
                        "2026-04-10 09:15:30",
                    ),
                    nexo_row(
                        "NXT1002",
                        "Nexo Card Transaction Fee",
                        "xUSD",
                        "-0.16",
                        "approved / Card fee",
                        "2026-04-10 09:15:31",
                    ),
                    nexo_row(
                        "NXT1003",
                        "Transfer Out",
                        "EUR",
                        "-250.00",
                        "approved / Bank transfer to BE6800000000000000",
                        "2026-04-11 11:22:33",
                    ),
                ),
                "text/csv",
            )
        },
    )
    assert response.status_code == expected_status
    return response.json()


def test_upload_endpoint_returns_reviewable_session_shape(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify upload endpoint returns reviewable session shape."""
    _ = db_session
    payload = _upload_pdf(monkeypatch, SANITIZED_BEOBANK_PAGE_TEXTS)

    assert payload["status"] == "awaiting_review"
    assert payload["strategy_key"] == "pdf_statement"
    assert payload["attempt_count"] == 1
    assert payload["extractor_id"] == "beobank_mastercard_pdf_v1"
    assert payload["error_stage"] is None
    assert payload["error_message"] is None


def test_upload_endpoint_returns_failed_shape_when_extraction_not_reviewable(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify upload returns failed session shape when not reviewable."""
    _ = db_session
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
    assert "supported deterministic PDF layout" in payload["error_message"]


def test_upload_endpoint_returns_duplicate_conflict_for_usable_existing_pdf_session(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify upload returns duplicate conflict for usable pdf session."""
    _ = db_session
    first_session = _upload_pdf(monkeypatch, SANITIZED_BEOBANK_PAGE_TEXTS)

    response = client.post(
        "/imports/upload",
        files={"file": ("statement.pdf", b"%PDF-1.7\nstub", "application/pdf")},
    )

    assert response.status_code == HTTP_CONFLICT
    payload = response.json()
    expected_file_hash = hashlib.sha256(b"%PDF-1.7\nstub").hexdigest()
    assert payload["message"] == "Import session with this file hash already exists."
    assert payload["file_hash"] == expected_file_hash
    assert payload["existing_session"]["id"] == first_session["id"]
    assert payload["existing_session"]["status"] == "awaiting_review"


def test_upload_endpoint_replaces_non_retryable_existing_pdf_session(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify upload endpoint replaces non retryable existing pdf session."""
    first_session = _upload_pdf(monkeypatch, SANITIZED_BEOBANK_PAGE_TEXTS)
    persisted_session = db_session.get(ImportSession, first_session["id"])
    assert persisted_session is not None
    persisted_session.status = ImportSessionStatus.FAILED.value
    db_session.commit()

    original_file = (
        settings.imports_dir / str(first_session["id"]) / "original" / "statement.pdf"
    )
    original_file.unlink()

    response = client.post(
        "/imports/upload",
        files={"file": ("statement.pdf", b"%PDF-1.7\nstub", "application/pdf")},
    )

    assert response.status_code == HTTP_OK
    payload = response.json()
    assert payload["id"] != first_session["id"]
    assert payload["status"] == "awaiting_review"

    db_session.expire_all()
    replaced_session = db_session.get(ImportSession, first_session["id"])
    new_session = db_session.get(ImportSession, payload["id"])
    assert replaced_session is not None
    assert new_session is not None
    expected_file_hash = hashlib.sha256(b"%PDF-1.7\nstub").hexdigest()
    assert (
        replaced_session.file_hash
        == f"{expected_file_hash}#legacy-duplicate#{first_session['id']}"
    )
    assert replaced_session.status == ImportSessionStatus.SUPERSEDED.value
    assert new_session.file_hash == expected_file_hash


def test_upload_endpoint_returns_reviewable_nexo_csv_session_shape(
    db_session: Session,
) -> None:
    """Verify upload endpoint returns reviewable nexo csv session shape."""
    _ = db_session
    payload = _upload_nexo_csv()

    assert payload["status"] == "awaiting_review"
    assert payload["strategy_key"] == "nexo_csv"
    assert payload["provider_hint"] == "nexo"
    assert payload["extractor_id"] == "nexo_csv_v1"
    assert payload["attempt_count"] == 1
    assert payload["error_stage"] is None
    assert payload["error_message"] is None


def test_get_review_payload_returns_statement_transactions_issues_and_evidence(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify get review payload returns statement transactions issues and evidence."""
    _ = db_session
    session = _upload_pdf(monkeypatch, SANITIZED_BEOBANK_PAGE_TEXTS)

    response = client.get(f"/imports/{session['id']}")

    assert response.status_code == HTTP_OK
    payload = response.json()
    assert payload["session"]["id"] == session["id"]
    assert payload["session"]["status"] == "awaiting_review"
    assert payload["statement"]["attempt_number"] == 1
    assert payload["statement"]["card_number_hint"] == "xxxx xxxx xxxx 1111"
    assert payload["statement"]["currency"] == "EUR"
    assert len(payload["transactions"]) == EXPECTED_REVIEW_TRANSACTION_COUNT
    assert payload["transactions"][0]["source_locator"] == "pdf:p2:l4"
    assert payload["transactions"][0]["raw_fields"]["source_locator"] == "pdf:p2:l4"
    assert payload["issues"] == []
    assert payload["evidence"]["text_blocks"][0]["page_number"] == 1


def test_get_review_payload_returns_persisted_review_time_proposals(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify get review payload returns persisted review time proposals."""
    session = _upload_pdf(monkeypatch, SANITIZED_BEOBANK_PAGE_TEXTS)

    statement_draft = (
        db_session.query(ImportStatementDraft)
        .filter_by(import_session_id=session["id"])
        .one()
    )
    first_draft = (
        db_session.query(ImportTransactionDraft)
        .filter_by(import_statement_draft_id=statement_draft.id)
        .order_by(ImportTransactionDraft.id.asc())
        .first()
    )
    assert first_draft is not None
    first_draft.proposed_transaction_type = "Expense"
    first_draft.proposed_expense_category = "Groceries"
    first_draft.proposed_income_category = None
    first_draft.proposed_transfer_category = None
    first_draft.classification_source = "deterministic"
    first_draft.recurrence_pattern_id = REVIEW_RECURRENCE_PATTERN_ID
    db_session.commit()

    response = client.get(f"/imports/{session['id']}")

    assert response.status_code == HTTP_OK
    payload = response.json()
    first_transaction = payload["transactions"][0]
    assert first_transaction["proposed_transaction_type"] == "Expense"
    assert first_transaction["proposed_expense_category"] == "Groceries"
    assert first_transaction["proposed_income_category"] is None
    assert first_transaction["proposed_transfer_category"] is None
    assert first_transaction["classification_source"] == "deterministic"
    assert first_transaction["recurrence_pattern_id"] == REVIEW_RECURRENCE_PATTERN_ID


def test_get_review_payload_includes_display_fields_for_selected_reporting_currency(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify review payload includes selected reporting currency fields."""
    _store_rate(
        db_session,
        rate_date=date(2025, 12, 20),
        quoted_currency="USD",
        units_per_base="1.2000",
    )
    session = _upload_pdf(monkeypatch, SANITIZED_BEOBANK_PAGE_TEXTS)

    response = client.get(
        f"/imports/{session['id']}",
        headers={"X-Reporting-Currency": "USD"},
    )

    assert response.status_code == HTTP_OK
    payload = response.json()
    first_transaction = payload["transactions"][0]
    assert first_transaction["signed_amount"] == EUR_TRANSACTION_AMOUNT
    assert first_transaction["currency"] == "EUR"
    assert first_transaction["display_amount"] == USD_DISPLAY_AMOUNT
    assert first_transaction["display_currency"] == "USD"
    assert first_transaction["display_fx_rate"] == USD_DISPLAY_RATE
    assert first_transaction["display_rate_date"] == "2025-12-20"
    assert first_transaction["display_is_available"] is True
    assert first_transaction["display_unavailable_reason"] is None


def test_get_review_payload_keeps_unavailable_display_shape_when_rate_missing(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify get review payload keeps unavailable display shape when rate missing."""
    _ = db_session

    class FakeECBExchangeRateService:
        def __init__(self, db: Session, *, timeout: float = 30.0) -> None:
            self.db = db
            self.timeout = timeout

        def ensure_conversion_coverage(
            self,
            _requests: list[FXConversionCoverageRequest],
            *,
            _lock_timeout_seconds: float,
            _lock_poll_seconds: float,
        ) -> FXConversionCoverageResult:
            return FXConversionCoverageResult(
                status=FXConversionCoverageStatus.FETCH_FAILED,
                required_quotes=("USD",),
                missing_dates=(date(2025, 12, 20),),
                start_date=date(2025, 12, 10),
                end_date=date(2025, 12, 20),
                error="ECB unavailable",
            )

    monkeypatch.setattr(
        "app.imports.workflow.ECBExchangeRateService", FakeECBExchangeRateService
    )

    session = _upload_pdf(monkeypatch, SANITIZED_BEOBANK_PAGE_TEXTS)

    response = client.get(
        f"/imports/{session['id']}",
        headers={"X-Reporting-Currency": "USD"},
    )

    assert response.status_code == HTTP_OK
    payload = response.json()
    first_transaction = payload["transactions"][0]
    assert first_transaction["signed_amount"] == EUR_TRANSACTION_AMOUNT
    assert first_transaction["currency"] == "EUR"
    assert first_transaction["display_amount"] is None
    assert first_transaction["display_currency"] == "USD"
    assert first_transaction["display_fx_rate"] is None
    assert first_transaction["display_rate_date"] is None
    assert first_transaction["display_is_available"] is False
    assert first_transaction["display_unavailable_reason"] == "missing_rate"


def test_get_review_payload_exposes_nexo_proposal_fields(
    db_session: Session,
) -> None:
    """Verify get review payload exposes nexo proposal fields."""
    _ = db_session
    session = _upload_nexo_csv()

    response = client.get(f"/imports/{session['id']}")

    assert response.status_code == HTTP_OK
    payload = response.json()
    assert payload["session"]["status"] == "awaiting_review"
    assert payload["statement"]["account_number_hint"] == "NEXO"
    assert payload["statement"]["review_status"] == "awaiting_review"
    assert len(payload["transactions"]) == EXPECTED_NEXO_TRANSACTION_COUNT
    assert payload["transactions"][0]["source_locator"] == "csv:r2:NXT1001"
    assert payload["transactions"][0]["proposed_transaction_type"] == "Expense"
    assert payload["transactions"][0]["proposed_expense_category"] is None
    assert payload["transactions"][0]["proposed_transfer_category"] is None
    assert payload["transactions"][1]["proposed_expense_category"] == "Financial Fees"
    assert payload["transactions"][2]["proposed_transaction_type"] == "Transfer"
    assert (
        payload["transactions"][2]["proposed_transfer_category"] == "Internal Transfer"
    )
    assert payload["issues"] == []
    assert payload["evidence"]["text_blocks"][0]["page_number"] == 1


def test_get_review_payload_for_failed_session_returns_issues_and_evidence(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify failed session returns issues and evidence without statement."""
    _ = db_session
    session = _upload_pdf(
        monkeypatch,
        [
            "Uittreksel van uw kredietkaart\nPeriode 15/12/2025 - 14/01/2026\n",
            "Some other bank\n21/12/2025 SHOP 12,34\n",
        ],
    )

    response = client.get(f"/imports/{session['id']}")

    assert response.status_code == HTTP_OK
    payload = response.json()
    assert payload["session"]["status"] == "failed"
    assert payload["statement"] is None
    assert payload["transactions"] == []
    assert payload["issues"][0]["issue_code"] == "unsupported_pdf_statement_layout"
    assert payload["evidence"]["text_blocks"][0]["raw_text"].startswith("Uittreksel")


def test_approve_commits_transactions_with_traceability_and_updates_statistics(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify approve commits transactions with traceability and updates statistics."""
    session = _upload_pdf(monkeypatch, SANITIZED_BEOBANK_PAGE_TEXTS)

    response = client.post(f"/imports/{session['id']}/approve")

    assert response.status_code == HTTP_OK
    payload = response.json()
    assert payload["id"] == session["id"]
    assert payload["status"] == "committed"
    assert payload["attempt_count"] == 1

    db_session.expire_all()
    committed_transactions = (
        db_session.query(Transaction).order_by(Transaction.id).all()
    )
    assert len(committed_transactions) == EXPECTED_REVIEW_TRANSACTION_COUNT

    first_transaction = committed_transactions[0]
    assert first_transaction.import_session_id == session["id"]
    assert first_transaction.account_number == "xxxx xxxx xxxx 1111"
    assert first_transaction.transaction_date.isoformat() == "2025-12-20"
    assert first_transaction.amount == EUR_TRANSACTION_AMOUNT
    assert first_transaction.currency == "EUR"
    assert first_transaction.description == "MERCADO EXTRA-1776 PRAIA GRANDE BR"
    assert first_transaction.counterparty_name is None
    assert first_transaction.counterparty_account is None
    assert first_transaction.import_source_locator == "pdf:p2:l4"
    assert (
        first_transaction.import_source_description
        == "MERCADO EXTRA-1776 PRAIA GRANDE BR"
    )
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
        1
        for transaction in committed_transactions
        if transaction.transaction_type == TransactionType.EXPENSE
    )
    expected_total_expenses = sum(
        abs(transaction.amount)
        for transaction in committed_transactions
        if transaction.transaction_type == TransactionType.EXPENSE
    )
    assert all_time_stats.expense_count == expected_expense_count
    assert all_time_stats.total_expenses == expected_total_expenses

    persisted_session = db_session.get(ImportSession, session["id"])
    assert persisted_session is not None
    statement_draft = (
        db_session.query(ImportStatementDraft)
        .filter_by(import_session_id=session["id"])
        .one()
    )
    assert persisted_session.status == "committed"
    assert statement_draft.review_status == "approved"


def test_approve_nexo_import_commits_expense_fee_and_transfer_rows(
    db_session: Session,
) -> None:
    """Verify approve nexo import commits expense fee and transfer rows."""
    session = _upload_nexo_csv()

    response = client.post(f"/imports/{session['id']}/approve")

    assert response.status_code == HTTP_OK
    payload = response.json()
    assert payload["status"] == "committed"

    db_session.expire_all()
    committed_transactions = (
        db_session.query(Transaction).order_by(Transaction.id.asc()).all()
    )
    assert len(committed_transactions) == EXPECTED_NEXO_TRANSACTION_COUNT

    purchase, fee, transfer = committed_transactions
    assert purchase.import_session_id == session["id"]
    assert purchase.transaction_type == TransactionType.EXPENSE
    assert purchase.expense_category is None
    assert purchase.transfer_category is None
    assert purchase.source_bank == "Nexo"

    assert fee.transaction_type == TransactionType.EXPENSE
    assert fee.expense_category == ExpenseCategory.FINANCIAL_FEES
    assert fee.source_bank == "Nexo"

    assert transfer.transaction_type == TransactionType.TRANSFER
    assert transfer.transfer_category == TransferCategory.INTERNAL_TRANSFER
    assert transfer.source_bank == "Nexo"


def test_approve_returns_conflict_when_any_committed_transaction_would_duplicate(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify approve returns conflict for duplicate committed rows."""
    first_session = _upload_pdf(monkeypatch, SANITIZED_BEOBANK_PAGE_TEXTS)
    first_response = client.post(f"/imports/{first_session['id']}/approve")
    assert first_response.status_code == HTTP_OK

    duplicate_session = _upload_pdf(
        monkeypatch,
        SANITIZED_BEOBANK_PAGE_TEXTS,
        file_bytes=b"%PDF-1.7\nstub-approval-conflict",
    )

    response = client.post(f"/imports/{duplicate_session['id']}/approve")

    assert response.status_code == HTTP_CONFLICT
    detail = response.json()["detail"]
    assert (
        detail["message"] == "Approval would create duplicate committed transactions."
    )
    assert (
        detail["duplicates"][0]["source_description"]
        == "MERCADO EXTRA-1776 PRAIA GRANDE BR"
    )

    db_session.expire_all()
    assert db_session.query(Transaction).count() == EXPECTED_REVIEW_TRANSACTION_COUNT
    duplicate_persisted = db_session.get(ImportSession, duplicate_session["id"])
    assert duplicate_persisted is not None
    assert duplicate_persisted.status == "awaiting_review"


def test_approve_returns_conflict_when_latest_attempt_has_blocking_issue(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify approve returns conflict when latest attempt has blocking issue."""
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

    assert response.status_code == HTTP_CONFLICT
    assert "blocking issues" in response.json()["detail"]
    db_session.expire_all()
    statement_draft = (
        db_session.query(ImportStatementDraft)
        .filter_by(import_session_id=session["id"])
        .one()
    )
    persisted_session = db_session.get(ImportSession, session["id"])
    assert persisted_session is not None
    assert persisted_session.status == "awaiting_review"
    assert statement_draft.review_status == "awaiting_review"
    assert db_session.query(Transaction).count() == 0


def test_reject_moves_session_to_rejected(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify reject moves session to rejected."""
    session = _upload_pdf(monkeypatch, SANITIZED_BEOBANK_PAGE_TEXTS)

    response = client.post(f"/imports/{session['id']}/reject")

    assert response.status_code == HTTP_OK
    payload = response.json()
    assert payload["id"] == session["id"]
    assert payload["status"] == "rejected"

    db_session.expire_all()
    statement_draft = (
        db_session.query(ImportStatementDraft)
        .filter_by(import_session_id=session["id"])
        .one()
    )
    persisted_session = db_session.get(ImportSession, session["id"])
    assert persisted_session is not None
    assert persisted_session.status == "rejected"
    assert statement_draft.review_status == "rejected"


def test_retry_reextracts_same_session_and_increments_attempt_number(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify retry reextracts same session and increments attempt number."""
    session = _upload_pdf(monkeypatch, SANITIZED_BEOBANK_PAGE_TEXTS)

    response = client.post(f"/imports/{session['id']}/retry")

    assert response.status_code == HTTP_OK
    payload = response.json()
    assert payload["id"] == session["id"]
    assert payload["status"] == "awaiting_review"
    assert payload["attempt_count"] == RETRY_ATTEMPT_COUNT

    db_session.expire_all()
    statements = (
        db_session.query(ImportStatementDraft)
        .filter(ImportStatementDraft.import_session_id == session["id"])
        .order_by(ImportStatementDraft.attempt_number.asc())
        .all()
    )
    assert [statement.attempt_number for statement in statements] == [
        1,
        RETRY_ATTEMPT_COUNT,
    ]
    assert statements[0].review_status == "superseded"
    assert statements[1].review_status == "awaiting_review"

    review_response = client.get(f"/imports/{session['id']}")
    review_payload = review_response.json()
    assert review_payload["session"]["attempt_count"] == RETRY_ATTEMPT_COUNT
    assert review_payload["statement"]["attempt_number"] == RETRY_ATTEMPT_COUNT


def test_get_review_payload_fetches_missing_supported_fx_before_display(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify get review payload fetches missing supported fx before display."""
    _ = db_session
    coverage_requests: list[list[FXConversionCoverageRequest]] = []

    class FakeECBExchangeRateService:
        def __init__(self, db: Session, *, timeout: float = 30.0) -> None:
            self.db = db
            self.timeout = timeout

        def ensure_conversion_coverage(
            self,
            requests: list[FXConversionCoverageRequest],
            *,
            lock_timeout_seconds: float,
            lock_poll_seconds: float,
        ) -> FXConversionCoverageResult:
            _ = (lock_timeout_seconds, lock_poll_seconds)
            coverage_requests.append(requests)
            self.db.add(
                FXDailyReferenceRate(
                    rate_date=date(2026, 4, 10),
                    base_currency="EUR",
                    quoted_currency="USD",
                    units_per_base=Decimal("1.2500"),
                    source_name="ECB_EXR",
                    fetched_at=datetime(2026, 4, 10, 8, 30, tzinfo=UTC),
                    updated_at=datetime(2026, 4, 10, 8, 30, tzinfo=UTC),
                )
            )
            self.db.commit()
            return FXConversionCoverageResult(
                status=FXConversionCoverageStatus.FETCHED_AND_COVERED,
                required_quotes=("USD",),
                start_date=date(2026, 4, 1),
                end_date=date(2026, 4, 10),
            )

    monkeypatch.setattr(
        "app.imports.workflow.ECBExchangeRateService", FakeECBExchangeRateService
    )

    session = _upload_nexo_csv()

    response = client.get(
        f"/imports/{session['id']}",
        headers={"X-Reporting-Currency": "EUR"},
    )

    assert response.status_code == HTTP_OK
    payload = response.json()
    first_transaction = payload["transactions"][0]
    assert first_transaction["currency"] == "xUSD"
    assert first_transaction["display_amount"] == NEXO_EUR_DISPLAY_AMOUNT
    assert first_transaction["display_currency"] == "EUR"
    assert first_transaction["display_fx_rate"] == EUR_PER_USD_RATE
    assert first_transaction["display_rate_date"] == "2026-04-10"
    assert first_transaction["display_is_available"] is True
    assert first_transaction["display_unavailable_reason"] is None
    assert len(coverage_requests) == 1
    assert {request.raw_currency for request in coverage_requests[0]} == {
        "xUSD",
        "EUR",
    }


def test_get_review_payload_fetches_supported_fx_in_mixed_unsupported_batch(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify get review payload fetches supported fx in mixed unsupported batch."""
    monkeypatch.setattr(
        "app.services.ecb_exchange_rates.ECBExchangeRateService._fetch_series",
        lambda _self, _start_date, _end_date: {
            date(2026, 4, 10): {"USD": Decimal("1.2500")},
        },
    )

    session = _upload_nexo_csv()
    statement = (
        db_session.query(ImportStatementDraft)
        .filter_by(import_session_id=session["id"])
        .one()
    )
    db_session.add(
        ImportTransactionDraft(
            import_statement_draft_id=statement.id,
            transaction_date=date(2026, 4, 10),
            source_description="Nexo loyalty reward",
            signed_amount=3.21,
            currency="NEXO",
            source_locator="csv:r5:NXT1004",
            edit_source="deterministic_extracted",
        )
    )
    db_session.commit()

    response = client.get(
        f"/imports/{session['id']}",
        headers={"X-Reporting-Currency": "EUR"},
    )

    assert response.status_code == HTTP_OK
    payload = response.json()
    transactions_by_locator = {
        transaction["source_locator"]: transaction
        for transaction in payload["transactions"]
    }
    xusd_transaction = transactions_by_locator["csv:r2:NXT1001"]
    nexo_transaction = transactions_by_locator["csv:r5:NXT1004"]

    assert xusd_transaction["currency"] == "xUSD"
    assert xusd_transaction["display_amount"] == NEXO_EUR_DISPLAY_AMOUNT
    assert xusd_transaction["display_currency"] == "EUR"
    assert xusd_transaction["display_fx_rate"] == EUR_PER_USD_RATE
    assert xusd_transaction["display_rate_date"] == "2026-04-10"
    assert xusd_transaction["display_is_available"] is True
    assert xusd_transaction["display_unavailable_reason"] is None
    assert nexo_transaction["currency"] == "NEXO"
    assert nexo_transaction["display_amount"] is None
    assert nexo_transaction["display_currency"] == "EUR"
    assert nexo_transaction["display_fx_rate"] is None
    assert nexo_transaction["display_rate_date"] is None
    assert nexo_transaction["display_is_available"] is False
    assert nexo_transaction["display_unavailable_reason"] == "unsupported_currency"


def test_get_review_payload_keeps_missing_rate_when_review_fx_coverage_fetch_fails(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify review payload keeps missing rate when fetch fails."""
    _ = db_session

    class FakeECBExchangeRateService:
        def __init__(self, db: Session, *, timeout: float = 30.0) -> None:
            self.db = db
            self.timeout = timeout

        def ensure_conversion_coverage(
            self,
            _requests: list[FXConversionCoverageRequest],
            *,
            _lock_timeout_seconds: float,
            _lock_poll_seconds: float,
        ) -> FXConversionCoverageResult:
            return FXConversionCoverageResult(
                status=FXConversionCoverageStatus.FETCH_FAILED,
                required_quotes=("USD",),
                missing_dates=(date(2026, 4, 10),),
                start_date=date(2026, 4, 1),
                end_date=date(2026, 4, 10),
                error="ECB unavailable",
            )

    monkeypatch.setattr(
        "app.imports.workflow.ECBExchangeRateService", FakeECBExchangeRateService
    )

    session = _upload_nexo_csv()

    response = client.get(
        f"/imports/{session['id']}",
        headers={"X-Reporting-Currency": "EUR"},
    )

    assert response.status_code == HTTP_OK
    payload = response.json()
    first_transaction = payload["transactions"][0]
    assert first_transaction["currency"] == "xUSD"
    assert first_transaction["display_amount"] is None
    assert first_transaction["display_currency"] == "EUR"
    assert first_transaction["display_fx_rate"] is None
    assert first_transaction["display_rate_date"] is None
    assert first_transaction["display_is_available"] is False
    assert first_transaction["display_unavailable_reason"] == "missing_rate"
