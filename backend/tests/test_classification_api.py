from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import settings as app_settings
from app.database import SessionLocal
from app.models.classification import ClassificationSession, ClassificationSessionStatus, RecurrencePattern
from app.models.transaction import Transaction
from app.main import app
from app.services import classification_session_service


client = TestClient(app)


@pytest.fixture(autouse=True)
def _enable_runtime_stub_provider(monkeypatch):
    monkeypatch.setattr(
        classification_session_service,
        "settings",
        replace(app_settings, provider_config_path=app_settings.provider_example_path),
    )


def _reset_database():
    response = client.post("/debug/reset-database")
    assert response.status_code == 200


def _restore_transaction(*, description: str, amount: float = -49.99, transaction_type: str | None = None):
    payload = {
        "account_number": "BE55000000000001",
        "transaction_date": "2025-01-15",
        "amount": amount,
        "currency": "EUR",
        "description": description,
        "counterparty_name": "Counterparty",
        "counterparty_account": "BE99000000000002",
        "source_bank": "ing",
    }
    if transaction_type is not None:
        payload["transaction_type"] = transaction_type

    response = client.post("/transactions/restore", json=payload)
    assert response.status_code == 200
    return response.json()


def test_create_session_returns_open_session():
    _reset_database()
    transaction = _restore_transaction(description="PROXIMUS telecom invoice")

    response = client.post("/classification/sessions", json={"transaction_id": transaction["id"]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["transaction_id"] == transaction["id"]
    assert payload["status"] == "open"


def test_create_session_reuses_existing_open_session():
    _reset_database()
    transaction = _restore_transaction(description="PROXIMUS telecom invoice")

    first_response = client.post("/classification/sessions", json={"transaction_id": transaction["id"]})
    second_response = client.post("/classification/sessions", json={"transaction_id": transaction["id"]})

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert second_response.json()["id"] == first_response.json()["id"]


def test_propose_returns_structured_stub_proposal_for_proximus():
    _reset_database()
    transaction = _restore_transaction(description="PROXIMUS telecom invoice")
    session = client.post("/classification/sessions", json={"transaction_id": transaction["id"]}).json()

    response = client.post(f"/classification/sessions/{session['id']}/propose")

    assert response.status_code == 200
    payload = response.json()
    assert payload["turn_index"] == 0
    assert payload["transaction_type"] == "Expense"
    assert payload["category"] == "Utilities"
    assert payload["confidence"] == 0.91
    assert payload["recurrence_frequency"] == "monthly"
    assert payload["follow_up_question"] is None


def test_feedback_creates_another_turn_and_returns_follow_up_question():
    _reset_database()
    transaction = _restore_transaction(description="Transfer to savings account")
    session = client.post("/classification/sessions", json={"transaction_id": transaction["id"]}).json()

    propose_response = client.post(f"/classification/sessions/{session['id']}/propose")
    assert propose_response.status_code == 200

    feedback_response = client.post(
        f"/classification/sessions/{session['id']}/feedback",
        json={"feedback_tag": "needs_review", "feedback_note": "This may be my own account"},
    )

    assert feedback_response.status_code == 200
    payload = feedback_response.json()
    assert payload["turn_index"] == 1
    assert payload["transaction_type"] == "Expense"
    assert payload["confidence"] == 0.5
    assert "own account" in payload["follow_up_question"].lower()


def test_accept_requires_confirmation_for_type_change():
    _reset_database()
    transaction = _restore_transaction(description="Payroll correction", amount=-1200.00)
    session = client.post("/classification/sessions", json={"transaction_id": transaction["id"]}).json()

    response = client.post(
        f"/classification/sessions/{session['id']}/accept",
        json={
            "transaction_type": "Income",
            "category": "Salary",
            "classification_source": "assistant",
            "confirm_type_change": False,
            "recurrence": {"is_recurrent": False},
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Type change requires confirmation"


def test_accept_commits_transaction_sets_classification_source_and_marks_session_accepted():
    _reset_database()
    transaction = _restore_transaction(description="PROXIMUS telecom invoice")
    session = client.post("/classification/sessions", json={"transaction_id": transaction["id"]}).json()

    propose_response = client.post(f"/classification/sessions/{session['id']}/propose")
    assert propose_response.status_code == 200

    response = client.post(
        f"/classification/sessions/{session['id']}/accept",
        json={
            "transaction_type": "Expense",
            "category": "Utilities",
            "classification_source": "assistant",
            "confirm_type_change": False,
            "recurrence": {"is_recurrent": True, "frequency": "monthly"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["session"]["status"] == "accepted"
    assert payload["transaction"]["transaction_type"] == "Expense"
    assert payload["transaction"]["expense_category"] == "Utilities"
    assert payload["transaction"]["classification_source"] == "assistant"
    assert payload["transaction"]["recurrence_pattern_id"] is not None


def test_propose_returns_503_when_runtime_provider_config_is_missing(tmp_path, monkeypatch):
    _reset_database()
    transaction = _restore_transaction(description="PROXIMUS telecom invoice")

    db = SessionLocal()
    try:
        session = ClassificationSession(
            transaction_id=transaction["id"],
            status=ClassificationSessionStatus.OPEN,
            provider_name="stub",
            model_name="stub-classifier-v1",
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        session_id = session.id
    finally:
        db.close()

    missing_config = tmp_path / "missing-runtime-config.yaml"
    monkeypatch.setattr(
        classification_session_service,
        "settings",
        replace(app_settings, provider_config_path=missing_config),
    )

    response = client.post(f"/classification/sessions/{session_id}/propose")

    assert response.status_code == 503
    assert response.json()["detail"] == "No classification assistant provider configured"


def test_accept_transfer_normalizes_internal_transfer_category_everywhere():
    _reset_database()
    transaction = _restore_transaction(description="Move to savings account", amount=-200.00)
    session = client.post("/classification/sessions", json={"transaction_id": transaction["id"]}).json()

    response = client.post(
        f"/classification/sessions/{session['id']}/accept",
        json={
            "transaction_type": "Transfer",
            "category": "Salary",
            "classification_source": "assistant",
            "confirm_type_change": True,
            "recurrence": {"is_recurrent": True, "frequency": "monthly"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["session"]["status"] == "accepted"
    assert payload["session"]["final_transaction_type"] == "Transfer"
    assert payload["session"]["final_category"] == "Internal Transfer"
    assert payload["transaction"]["transaction_type"] == "Transfer"
    assert payload["transaction"]["expense_category"] == "Internal Transfer"
    assert payload["transaction"]["income_category"] is None

    db = SessionLocal()
    try:
        stored_session = db.query(ClassificationSession).filter(ClassificationSession.id == session["id"]).first()
        stored_pattern = (
            db.query(RecurrencePattern)
            .filter(RecurrencePattern.id == payload["recurrence_pattern_id"])
            .first()
        )
        stored_transaction = db.query(Transaction).filter(Transaction.id == transaction["id"]).first()
    finally:
        db.close()

    assert stored_session is not None
    assert stored_session.final_category == "Internal Transfer"
    assert stored_pattern is not None
    assert stored_pattern.category == "Internal Transfer"
    assert stored_transaction is not None
    assert stored_transaction.recurrence_pattern_id == payload["recurrence_pattern_id"]


def test_propose_returns_409_for_expired_session():
    _reset_database()
    transaction = _restore_transaction(description="PROXIMUS telecom invoice")
    session = client.post("/classification/sessions", json={"transaction_id": transaction["id"]}).json()

    db = SessionLocal()
    try:
        stored_session = db.query(ClassificationSession).filter(ClassificationSession.id == session["id"]).first()
        stored_session.updated_at = datetime.utcnow() - timedelta(hours=25)
        db.commit()
    finally:
        db.close()

    response = client.post(f"/classification/sessions/{session['id']}/propose")

    assert response.status_code == 409
    assert response.json()["detail"] == "Session expired"
