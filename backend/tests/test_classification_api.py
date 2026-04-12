from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings as app_settings
from app.database import SessionLocal
from app.models.classification import ClassificationSession, ClassificationSessionStatus, RecurrencePattern
from app.models.transaction import ExpenseCategory, Transaction, TransactionType, TransferCategory
from app.main import app
from app.services.classifier_providers import ClassificationProposal
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


def _restore_transaction(
    *,
    description: str,
    amount: float = -49.99,
    transaction_type: str | None = None,
    expense_category: str | None = None,
    income_category: str | None = None,
    transfer_category: str | None = None,
):
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
    if expense_category is not None:
        payload["expense_category"] = expense_category
    if income_category is not None:
        payload["income_category"] = income_category
    if transfer_category is not None:
        payload["transfer_category"] = transfer_category

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


def test_create_session_replaces_stale_open_session_when_provider_is_no_longer_available(
    tmp_path, monkeypatch
):
    _reset_database()
    transaction = _restore_transaction(description="PROXIMUS telecom invoice")

    config_path = tmp_path / "classification-providers.yaml"
    config_path.write_text(
        """
classification_assistant:
  order:
    - openrouter
  providers:
    stub:
      enabled: false
      kind: stub
      model: stub-classifier-v1
    openrouter:
      enabled: true
      kind: openai_compatible
      model: openai/gpt-4.1-mini
      base_url: https://openrouter.ai/api/v1
      api_key_env: OPENROUTER_API_KEY
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.setattr(
        classification_session_service,
        "settings",
        replace(app_settings, provider_config_path=Path(config_path)),
    )

    db = SessionLocal()
    try:
        stale_session = ClassificationSession(
            transaction_id=transaction["id"],
            status=ClassificationSessionStatus.OPEN,
            provider_name="stub",
            model_name="stub-classifier-v1",
        )
        db.add(stale_session)
        db.commit()
        db.refresh(stale_session)
        stale_session_id = stale_session.id
    finally:
        db.close()

    response = client.post("/classification/sessions", json={"transaction_id": transaction["id"]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] != stale_session_id

    db = SessionLocal()
    try:
        cancelled = db.query(ClassificationSession).filter(ClassificationSession.id == stale_session_id).first()
        replacement = db.query(ClassificationSession).filter(ClassificationSession.id == payload["id"]).first()
    finally:
        db.close()

    assert cancelled is not None
    assert cancelled.status == ClassificationSessionStatus.CANCELLED
    assert replacement is not None
    assert replacement.provider_name == "openrouter"


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


def test_feedback_passes_conversation_history_to_provider(monkeypatch):
    _reset_database()
    transaction = _restore_transaction(description="Transfer to savings account")
    seen_history_lengths: list[int] = []

    class SpyProvider:
        name = "stub"
        model_name = "stub-classifier-v1"

        def propose(self, **kwargs):
            seen_history_lengths.append(len(kwargs["conversation_history"]))
            return ClassificationProposal(
                transaction_type="Expense",
                category="Others",
                confidence=0.42,
                rationale="Fallback stub proposal.",
                follow_up_question="Could this be an internal transfer?",
            )

    monkeypatch.setattr(
        classification_session_service.ClassificationSessionService,
        "_build_provider",
        classmethod(lambda cls, provider_name=None, model_name=None: SpyProvider()),
    )

    session = client.post("/classification/sessions", json={"transaction_id": transaction["id"]}).json()

    propose_response = client.post(f"/classification/sessions/{session['id']}/propose")
    assert propose_response.status_code == 200

    feedback_response = client.post(
        f"/classification/sessions/{session['id']}/feedback",
        json={"feedback_tag": "missing_context", "feedback_note": "This may be my own account"},
    )

    assert feedback_response.status_code == 200
    assert seen_history_lengths == [0, 1]


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
    detail = response.json()["detail"]
    assert detail["message"] == "Classification provider unavailable"
    assert detail["suggestions"] == []


def test_propose_uses_next_available_provider_when_primary_remote_provider_fails(monkeypatch):
    _reset_database()
    transaction = _restore_transaction(description="PROXIMUS telecom invoice")

    class ExplodingProvider:
        name = "openai"
        model_name = "gpt-4o-mini"

        def propose(self, **kwargs):
            raise RuntimeError("provider boom")

    class FallbackProvider:
        name = "openrouter"
        model_name = "openai/gpt-4.1-mini"

        def propose(self, **kwargs):
            return ClassificationProposal(
                transaction_type="Expense",
                category="Utilities",
                confidence=0.87,
                rationale="Fallback provider classified this as utilities.",
                follow_up_question=None,
            )

    def fake_build_provider(cls, provider_name=None, model_name=None):
        if provider_name in (None, "openai"):
            return ExplodingProvider()
        if provider_name == "openrouter":
            return FallbackProvider()
        raise AssertionError(f"unexpected provider: {provider_name}")

    monkeypatch.setattr(
        classification_session_service.ClassificationSessionService,
        "_build_provider",
        classmethod(fake_build_provider),
    )
    monkeypatch.setattr(
        classification_session_service.ClassificationSessionService,
        "_fallback_provider_names",
        classmethod(lambda cls, provider_name: ["openrouter"]),
    )

    session_response = client.post("/classification/sessions", json={"transaction_id": transaction["id"]})
    session_id = session_response.json()["id"]

    response = client.post(f"/classification/sessions/{session_id}/propose")

    assert response.status_code == 200
    assert response.json()["category"] == "Utilities"

    db = SessionLocal()
    try:
        stored_session = (
            db.query(ClassificationSession)
            .filter(ClassificationSession.id == session_id)
            .first()
        )
        assert stored_session is not None
        assert stored_session.provider_name == "openrouter"
        assert stored_session.model_name == "openai/gpt-4.1-mini"
    finally:
        db.close()


def test_propose_returns_degraded_suggestions_when_remote_provider_fails(monkeypatch):
    _reset_database()
    transaction = _restore_transaction(description="PROXIMUS telecom invoice")

    class ExplodingProvider:
        name = "openai"
        model_name = "gpt-4o-mini"

        def propose(self, **kwargs):
            raise RuntimeError("provider boom")

    monkeypatch.setattr(
        classification_session_service.ClassificationSessionService,
        "_build_provider",
        classmethod(lambda cls, provider_name=None, model_name=None: ExplodingProvider()),
    )

    session_response = client.post("/classification/sessions", json={"transaction_id": transaction["id"]})
    session_id = session_response.json()["id"]

    response = client.post(f"/classification/sessions/{session_id}/propose")

    assert response.status_code == 503
    assert response.json()["detail"]["message"] == "Classification provider unavailable"
    assert response.json()["detail"]["suggestions"] == []


def test_accept_transfer_persists_first_class_transfer_category_everywhere():
    _reset_database()
    transaction = _restore_transaction(description="Move to savings account", amount=-200.00)
    session = client.post("/classification/sessions", json={"transaction_id": transaction["id"]}).json()

    response = client.post(
        f"/classification/sessions/{session['id']}/accept",
        json={
            "transaction_type": "Transfer",
            "category": TransferCategory.INTERNAL_TRANSFER.value,
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
    assert payload["transaction"]["transfer_category"] == "Internal Transfer"
    assert payload["transaction"]["expense_category"] is None
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
    assert stored_transaction.transfer_category == TransferCategory.INTERNAL_TRANSFER
    assert stored_transaction.expense_category is None
    assert stored_transaction.income_category is None
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


def test_delete_transaction_removes_classification_rows_and_cleans_linked_recurrence_references():
    _reset_database()
    seed = _restore_transaction(description="PROXIMUS telecom invoice")
    follower = _restore_transaction(description="PROXIMUS telecom invoice", amount=-49.99)

    session = client.post("/classification/sessions", json={"transaction_id": seed["id"]}).json()
    accepted = client.post(
        f"/classification/sessions/{session['id']}/accept",
        json={
            "transaction_type": "Expense",
            "category": "Utilities",
            "classification_source": "assistant",
            "confirm_type_change": False,
            "recurrence": {"is_recurrent": True, "frequency": "monthly"},
        },
    ).json()

    db = SessionLocal()
    try:
        follower_row = db.query(Transaction).filter(Transaction.id == follower["id"]).first()
        assert follower_row is not None
        follower_row.recurrence_pattern_id = accepted["recurrence_pattern_id"]
        db.commit()
    finally:
        db.close()

    response = client.delete(f"/transactions/{seed['id']}")

    assert response.status_code == 200

    db = SessionLocal()
    try:
        assert db.query(Transaction).filter(Transaction.id == seed["id"]).first() is None
        assert (
            db.query(ClassificationSession)
            .filter(ClassificationSession.transaction_id == seed["id"])
            .count()
            == 0
        )
        assert (
            db.query(RecurrencePattern)
            .filter(RecurrencePattern.seed_transaction_id == seed["id"])
            .count()
            == 0
        )
        refreshed_follower = db.query(Transaction).filter(Transaction.id == follower["id"]).first()
        assert refreshed_follower is not None
        assert refreshed_follower.recurrence_pattern_id is None
    finally:
        db.close()


def test_preview_similar_excludes_transfer_like_candidates_for_bill_seed(monkeypatch):
    _reset_database()
    seed = _restore_transaction(description="PROXIMUS telecom invoice")
    transfer_like = _restore_transaction(description="Bancontact transfer Arne P2P MOBILE", amount=-4.0)
    utility_like = _restore_transaction(description="PROXIMUS telecom invoice April", amount=-86.99)

    session = client.post("/classification/sessions", json={"transaction_id": seed["id"]}).json()
    accept_response = client.post(
        f"/classification/sessions/{session['id']}/accept",
        json={
            "transaction_type": "Expense",
            "category": "Utilities",
            "classification_source": "assistant",
            "confirm_type_change": False,
            "recurrence": {"is_recurrent": False},
        },
    )
    assert accept_response.status_code == 200

    scores = {
        utility_like["description"].lower(): 0.92,
        transfer_like["description"].lower(): 0.89,
    }

    def fake_similarity_score(left: str, right: str) -> float:
        return scores.get(right, 0.0)

    monkeypatch.setattr(
        classification_session_service.category_suggestion_service,
        "similarity_score",
        fake_similarity_score,
    )

    response = client.post(f"/classification/sessions/{session['id']}/similar-preview")

    assert response.status_code == 200
    payload = response.json()
    match_ids = {match["transaction_id"] for match in payload["matches"]}
    assert utility_like["id"] in match_ids
    assert transfer_like["id"] not in match_ids


def test_preview_similar_skips_already_transfer_classified_candidates(monkeypatch):
    _reset_database()
    seed = _restore_transaction(description="Transfer to savings account", amount=-200.0)
    uncategorized = _restore_transaction(
        description="Transfer to savings account April",
        amount=-205.0,
        transaction_type=TransactionType.TRANSFER.value,
    )
    already_classified = _restore_transaction(
        description="Transfer to savings account March",
        amount=-198.0,
        transaction_type=TransactionType.TRANSFER.value,
        transfer_category=TransferCategory.INTERNAL_TRANSFER.value,
    )

    session = client.post("/classification/sessions", json={"transaction_id": seed["id"]}).json()
    accept_response = client.post(
        f"/classification/sessions/{session['id']}/accept",
        json={
            "transaction_type": TransactionType.TRANSFER.value,
            "category": TransferCategory.INTERNAL_TRANSFER.value,
            "classification_source": "assistant",
            "confirm_type_change": True,
            "recurrence": {"is_recurrent": False},
        },
    )
    assert accept_response.status_code == 200

    scores = {
        uncategorized["description"].lower(): 0.93,
        already_classified["description"].lower(): 0.92,
    }

    monkeypatch.setattr(
        classification_session_service.category_suggestion_service,
        "similarity_score",
        lambda left, right: scores.get(right, 0.0),
    )

    response = client.post(f"/classification/sessions/{session['id']}/similar-preview")

    assert response.status_code == 200
    match_ids = {match["transaction_id"] for match in response.json()["matches"]}
    assert uncategorized["id"] in match_ids
    assert already_classified["id"] not in match_ids


def test_apply_batch_skips_already_transfer_classified_candidates(monkeypatch):
    _reset_database()
    seed = _restore_transaction(description="Transfer to savings account", amount=-200.0)
    uncategorized = _restore_transaction(
        description="Transfer to savings account April",
        amount=-205.0,
        transaction_type=TransactionType.TRANSFER.value,
    )
    already_classified = _restore_transaction(
        description="Transfer to savings account March",
        amount=-198.0,
        transaction_type=TransactionType.TRANSFER.value,
        transfer_category=TransferCategory.INTERNAL_TRANSFER.value,
    )

    session = client.post("/classification/sessions", json={"transaction_id": seed["id"]}).json()
    accept_response = client.post(
        f"/classification/sessions/{session['id']}/accept",
        json={
            "transaction_type": TransactionType.TRANSFER.value,
            "category": TransferCategory.CREDIT_CARD_SETTLEMENT.value,
            "classification_source": "assistant",
            "confirm_type_change": True,
            "recurrence": {"is_recurrent": False},
        },
    )
    assert accept_response.status_code == 200

    scores = {
        uncategorized["description"].lower(): 0.93,
        already_classified["description"].lower(): 0.92,
    }

    monkeypatch.setattr(
        classification_session_service.category_suggestion_service,
        "similarity_score",
        lambda left, right: scores.get(right, 0.0),
    )

    response = client.post(
        f"/classification/sessions/{session['id']}/apply-batch",
        json={"transaction_ids": [uncategorized["id"], already_classified["id"]]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["applied_transaction_ids"] == [uncategorized["id"]]
    assert payload["skipped_transaction_ids"] == [already_classified["id"]]

    db = SessionLocal()
    try:
        refreshed_uncategorized = db.query(Transaction).filter(Transaction.id == uncategorized["id"]).first()
        refreshed_classified = db.query(Transaction).filter(Transaction.id == already_classified["id"]).first()
    finally:
        db.close()

    assert refreshed_uncategorized is not None
    assert refreshed_uncategorized.transfer_category == TransferCategory.CREDIT_CARD_SETTLEMENT
    assert refreshed_uncategorized.expense_category is None
    assert refreshed_uncategorized.income_category is None
    assert refreshed_classified is not None
    assert refreshed_classified.transfer_category == TransferCategory.INTERNAL_TRANSFER


def test_get_transactions_category_filter_matches_transfer_category():
    _reset_database()
    transfer = _restore_transaction(
        description="Belfius card settlement",
        amount=-240.0,
        transaction_type=TransactionType.TRANSFER.value,
        transfer_category=TransferCategory.CREDIT_CARD_SETTLEMENT.value,
    )
    _restore_transaction(
        description="PROXIMUS telecom invoice",
        amount=-49.99,
        transaction_type=TransactionType.EXPENSE.value,
        expense_category=ExpenseCategory.UTILITIES.value,
    )

    response = client.get(
        "/transactions/",
        params={"category": TransferCategory.CREDIT_CARD_SETTLEMENT.value, "page_size": 20},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert [item["id"] for item in payload["items"]] == [transfer["id"]]
    assert payload["items"][0]["transfer_category"] == TransferCategory.CREDIT_CARD_SETTLEMENT.value
