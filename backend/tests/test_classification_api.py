from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


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
