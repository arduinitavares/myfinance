"""Module for backend tests test_classification_api."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Never, cast

import pytest
from app.config import settings as app_settings
from app.database import SessionLocal
from app.main import app
from app.models.classification import (
    ClassificationSession,
    ClassificationSessionStatus,
    RecurrencePattern,
)
from app.models.fx import FXDailyReferenceRate
from app.models.transaction import (
    ExpenseCategory,
    Transaction,
    TransactionType,
    TransferCategory,
)
from app.routers.suggestions import category_suggestion_service
from app.services import classification_session_service
from app.services.classifier_providers import ClassificationProposal
from fastapi.testclient import TestClient
from qdrant_client.http import models

client: Any = TestClient(app)

HTTP_OK: int = 200
HTTP_BAD_REQUEST: int = 400
HTTP_CONFLICT: int = 409
HTTP_SERVICE_UNAVAILABLE: int = 503
DEFAULT_TRANSACTION_AMOUNT: float = -49.99
EXPECTED_STUB_CONFIDENCE: float = 0.91
EXPECTED_FEEDBACK_CONFIDENCE: float = 0.5
DISPLAY_AMOUNT_USD: float = -62.49
DISPLAY_FX_RATE: float = 1.25
PROVIDER_CONFIG_CONFIDENCE: float = 0.87
HIGH_SIMILARITY_SCORE: float = 0.95
FX_TIMESTAMP: datetime = datetime(2026, 4, 17, 8, 30, 0, tzinfo=UTC)


def _clear_vector_collections() -> None:
    category_suggestion_service.client.recreate_collection(
        collection_name="expense_embeddings",
        vectors_config=models.VectorParams(size=384, distance=models.Distance.COSINE),
    )
    category_suggestion_service.client.recreate_collection(
        collection_name="income_embeddings",
        vectors_config=models.VectorParams(size=384, distance=models.Distance.COSINE),
    )


@pytest.fixture(autouse=True)
def _enable_runtime_stub_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        classification_session_service,
        "settings",
        replace(app_settings, provider_config_path=app_settings.provider_example_path),
    )


def _reset_database() -> None:
    response = client.post("/debug/reset-database")
    assert response.status_code == HTTP_OK
    _clear_vector_collections()


def _restore_transaction(
    **fields: object,
) -> dict[str, Any]:
    description = fields.pop("description")
    amount = fields.pop("amount", DEFAULT_TRANSACTION_AMOUNT)
    transaction_type = fields.pop("transaction_type", None)
    expense_category = fields.pop("expense_category", None)
    income_category = fields.pop("income_category", None)
    transfer_category = fields.pop("transfer_category", None)
    assert fields == {}
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
    assert response.status_code == HTTP_OK
    return response.json()


def _store_rate(
    *,
    rate_date: date,
    quoted_currency: str,
    units_per_base: str,
) -> None:
    db = SessionLocal()
    try:
        db.add(
            FXDailyReferenceRate(
                rate_date=rate_date,
                base_currency="EUR",
                quoted_currency=quoted_currency,
                units_per_base=Decimal(units_per_base),
                source_name="ECB_EXR",
                fetched_at=FX_TIMESTAMP,
                updated_at=FX_TIMESTAMP,
            )
        )
        db.commit()
    finally:
        db.close()


def test_create_session_returns_open_session() -> None:
    """Verify create session returns open session."""
    _reset_database()
    transaction = _restore_transaction(description="PROXIMUS telecom invoice")

    response = client.post(
        "/classification/sessions", json={"transaction_id": transaction["id"]}
    )

    assert response.status_code == HTTP_OK
    payload = response.json()
    assert payload["transaction_id"] == transaction["id"]
    assert payload["status"] == "open"


def test_create_session_reuses_existing_open_session() -> None:
    """Verify create session reuses existing open session."""
    _reset_database()
    transaction = _restore_transaction(description="PROXIMUS telecom invoice")

    first_response = client.post(
        "/classification/sessions", json={"transaction_id": transaction["id"]}
    )
    second_response = client.post(
        "/classification/sessions", json={"transaction_id": transaction["id"]}
    )

    assert first_response.status_code == HTTP_OK
    assert second_response.status_code == HTTP_OK
    assert second_response.json()["id"] == first_response.json()["id"]


def test_create_session_replaces_stale_open_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify create session replaces stale open session."""
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

    response = client.post(
        "/classification/sessions", json={"transaction_id": transaction["id"]}
    )

    assert response.status_code == HTTP_OK
    payload = response.json()
    assert payload["id"] != stale_session_id

    db = SessionLocal()
    try:
        cancelled = (
            db.query(ClassificationSession)
            .filter(ClassificationSession.id == stale_session_id)
            .first()
        )
        replacement = (
            db.query(ClassificationSession)
            .filter(ClassificationSession.id == payload["id"])
            .first()
        )
    finally:
        db.close()

    assert cancelled is not None
    assert cancelled.status == ClassificationSessionStatus.CANCELLED
    assert replacement is not None
    assert replacement.provider_name == "openrouter"


def test_propose_returns_structured_stub_proposal_for_proximus() -> None:
    """Verify propose returns structured stub proposal for proximus."""
    _reset_database()
    transaction = _restore_transaction(description="PROXIMUS telecom invoice")
    session = client.post(
        "/classification/sessions", json={"transaction_id": transaction["id"]}
    ).json()

    response = client.post(f"/classification/sessions/{session['id']}/propose")

    assert response.status_code == HTTP_OK
    payload = response.json()
    assert payload["turn_index"] == 0
    assert payload["transaction_type"] == "Expense"
    assert payload["category"] == "Utilities"
    assert payload["confidence"] == EXPECTED_STUB_CONFIDENCE
    assert payload["recurrence_frequency"] == "monthly"
    assert payload["follow_up_question"] is None


def test_feedback_creates_another_turn_and_returns_follow_up_question() -> None:
    """Verify feedback creates another turn and returns follow up question."""
    _reset_database()
    transaction = _restore_transaction(description="Transfer to savings account")
    session = client.post(
        "/classification/sessions", json={"transaction_id": transaction["id"]}
    ).json()

    propose_response = client.post(f"/classification/sessions/{session['id']}/propose")
    assert propose_response.status_code == HTTP_OK

    feedback_response = client.post(
        f"/classification/sessions/{session['id']}/feedback",
        json={
            "feedback_tag": "needs_review",
            "feedback_note": "This may be my own account",
        },
    )

    assert feedback_response.status_code == HTTP_OK
    payload = feedback_response.json()
    assert payload["turn_index"] == 1
    assert payload["transaction_type"] == "Expense"
    assert payload["confidence"] == EXPECTED_FEEDBACK_CONFIDENCE
    assert "own account" in payload["follow_up_question"].lower()


def test_feedback_passes_conversation_history_to_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify feedback passes conversation history to provider."""
    _reset_database()
    transaction = _restore_transaction(description="Transfer to savings account")
    seen_history_lengths: list[int] = []

    class SpyProvider:
        name = "stub"
        model_name = "stub-classifier-v1"

        def propose(self, **kwargs: object) -> ClassificationProposal:
            history = kwargs["conversation_history"]
            seen_history_lengths.append(len(cast("list[object]", history)))
            return ClassificationProposal(
                transaction_type="Expense",
                category="Others",
                confidence=0.42,
                rationale="Fallback stub proposal.",
                follow_up_question="Could this be an internal transfer?",
            )

    def build_spy_provider(
        _cls: object,
        _provider_name: str | None = None,
        _model_name: str | None = None,
    ) -> SpyProvider:
        return SpyProvider()

    monkeypatch.setattr(
        classification_session_service.ClassificationSessionService,
        "_build_provider",
        classmethod(build_spy_provider),
    )

    session = client.post(
        "/classification/sessions", json={"transaction_id": transaction["id"]}
    ).json()

    propose_response = client.post(f"/classification/sessions/{session['id']}/propose")
    assert propose_response.status_code == HTTP_OK

    feedback_response = client.post(
        f"/classification/sessions/{session['id']}/feedback",
        json={
            "feedback_tag": "missing_context",
            "feedback_note": "This may be my own account",
        },
    )

    assert feedback_response.status_code == HTTP_OK
    assert seen_history_lengths == [0, 1]


def test_accept_requires_confirmation_for_type_change() -> None:
    """Verify accept requires confirmation for type change."""
    _reset_database()
    transaction = _restore_transaction(
        description="Payroll correction", amount=-1200.00
    )
    session = client.post(
        "/classification/sessions", json={"transaction_id": transaction["id"]}
    ).json()

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

    assert response.status_code == HTTP_BAD_REQUEST
    assert response.json()["detail"] == "Type change requires confirmation"


def test_accept_commits_transaction_and_marks_session_accepted() -> None:
    """Verify accept commits transaction and marks session accepted."""
    _reset_database()
    transaction = _restore_transaction(description="PROXIMUS telecom invoice")
    session = client.post(
        "/classification/sessions", json={"transaction_id": transaction["id"]}
    ).json()

    propose_response = client.post(f"/classification/sessions/{session['id']}/propose")
    assert propose_response.status_code == HTTP_OK

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

    assert response.status_code == HTTP_OK
    payload = response.json()
    assert payload["session"]["status"] == "accepted"
    assert payload["transaction"]["transaction_type"] == "Expense"
    assert payload["transaction"]["expense_category"] == "Utilities"
    assert payload["transaction"]["classification_source"] == "assistant"
    assert payload["transaction"]["recurrence_pattern_id"] is not None


def test_accept_returns_display_fields_for_reporting_currency() -> None:
    """Verify accept returns display fields for reporting currency."""
    _reset_database()
    _store_rate(
        rate_date=date(2025, 1, 15),
        quoted_currency="USD",
        units_per_base="1.2500",
    )
    transaction = _restore_transaction(description="PROXIMUS telecom invoice")
    session = client.post(
        "/classification/sessions", json={"transaction_id": transaction["id"]}
    ).json()

    propose_response = client.post(f"/classification/sessions/{session['id']}/propose")
    assert propose_response.status_code == HTTP_OK

    response = client.post(
        f"/classification/sessions/{session['id']}/accept",
        json={
            "transaction_type": "Expense",
            "category": "Utilities",
            "classification_source": "assistant",
            "confirm_type_change": False,
            "recurrence": {"is_recurrent": False},
        },
        headers={"X-Reporting-Currency": "USD"},
    )

    assert response.status_code == HTTP_OK
    payload = response.json()
    assert payload["transaction"]["amount"] == DEFAULT_TRANSACTION_AMOUNT
    assert payload["transaction"]["currency"] == "EUR"
    assert payload["transaction"]["display_amount"] == DISPLAY_AMOUNT_USD
    assert payload["transaction"]["display_currency"] == "USD"
    assert payload["transaction"]["display_fx_rate"] == DISPLAY_FX_RATE
    assert payload["transaction"]["display_rate_date"] == "2025-01-15"
    assert payload["transaction"]["display_is_available"] is True
    assert payload["transaction"]["display_unavailable_reason"] is None


def test_propose_returns_503_when_runtime_provider_config_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify propose returns 503 when runtime provider config is missing."""
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

    assert response.status_code == HTTP_SERVICE_UNAVAILABLE
    detail = response.json()["detail"]
    assert detail["message"] == "Classification provider unavailable"
    assert detail["suggestions"] == []


def test_propose_uses_next_available_provider_when_primary_remote_provider_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify propose falls back when primary remote provider fails."""
    _reset_database()
    transaction = _restore_transaction(description="PROXIMUS telecom invoice")

    class ExplodingProvider:
        name = "openai"
        model_name = "gpt-4o-mini"

        def propose(self, **_kwargs: object) -> Never:
            msg = "provider boom"
            raise RuntimeError(msg)

    class FallbackProvider:
        name = "openrouter"
        model_name = "openai/gpt-4.1-mini"

        def propose(self, **_kwargs: object) -> ClassificationProposal:
            return ClassificationProposal(
                transaction_type="Expense",
                category="Utilities",
                confidence=PROVIDER_CONFIG_CONFIDENCE,
                rationale="Fallback provider classified this as utilities.",
                follow_up_question=None,
            )

    def fake_build_provider(
        _cls: object,
        provider_name: str | None = None,
        _model_name: str | None = None,
    ) -> ExplodingProvider | FallbackProvider:
        if provider_name in (None, "openai"):
            return ExplodingProvider()
        if provider_name == "openrouter":
            return FallbackProvider()
        msg = f"unexpected provider: {provider_name}"
        raise AssertionError(msg)

    monkeypatch.setattr(
        classification_session_service.ClassificationSessionService,
        "_build_provider",
        classmethod(fake_build_provider),
    )
    def fallback_provider_names(_cls: object, _provider_name: str) -> list[str]:
        return ["openrouter"]

    monkeypatch.setattr(
        classification_session_service.ClassificationSessionService,
        "_fallback_provider_names",
        classmethod(fallback_provider_names),
    )

    session_response = client.post(
        "/classification/sessions", json={"transaction_id": transaction["id"]}
    )
    session_id = session_response.json()["id"]

    response = client.post(f"/classification/sessions/{session_id}/propose")

    assert response.status_code == HTTP_OK
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


def test_propose_returns_degraded_suggestions_when_remote_provider_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify propose returns degraded suggestions when remote provider fails."""
    _reset_database()
    transaction = _restore_transaction(description="PROXIMUS telecom invoice")

    class ExplodingProvider:
        name = "openai"
        model_name = "gpt-4o-mini"

        def propose(self, **_kwargs: object) -> Never:
            msg = "provider boom"
            raise RuntimeError(msg)

    def build_exploding_provider(
        _cls: object,
        _provider_name: str | None = None,
        _model_name: str | None = None,
    ) -> ExplodingProvider:
        return ExplodingProvider()

    monkeypatch.setattr(
        classification_session_service.ClassificationSessionService,
        "_build_provider",
        classmethod(build_exploding_provider),
    )

    session_response = client.post(
        "/classification/sessions", json={"transaction_id": transaction["id"]}
    )
    session_id = session_response.json()["id"]

    response = client.post(f"/classification/sessions/{session_id}/propose")

    assert response.status_code == HTTP_SERVICE_UNAVAILABLE
    assert response.json()["detail"]["message"] == (
        "Classification provider unavailable"
    )
    assert response.json()["detail"]["suggestions"] == []


def test_accept_transfer_persists_first_class_transfer_category_everywhere() -> None:
    """Verify accept transfer persists first class transfer category everywhere."""
    _reset_database()
    transaction = _restore_transaction(
        description="Move to savings account", amount=-200.00
    )
    session = client.post(
        "/classification/sessions", json={"transaction_id": transaction["id"]}
    ).json()

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

    assert response.status_code == HTTP_OK
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
        stored_session = (
            db.query(ClassificationSession)
            .filter(ClassificationSession.id == session["id"])
            .first()
        )
        stored_pattern = (
            db.query(RecurrencePattern)
            .filter(RecurrencePattern.id == payload["recurrence_pattern_id"])
            .first()
        )
        stored_transaction = (
            db.query(Transaction).filter(Transaction.id == transaction["id"]).first()
        )
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


def test_propose_returns_409_for_expired_session() -> None:
    """Verify propose returns 409 for expired session."""
    _reset_database()
    transaction = _restore_transaction(description="PROXIMUS telecom invoice")
    session = client.post(
        "/classification/sessions", json={"transaction_id": transaction["id"]}
    ).json()

    db = SessionLocal()
    try:
        stored_session = (
            db.query(ClassificationSession)
            .filter(ClassificationSession.id == session["id"])
            .first()
        )
        assert stored_session is not None
        stored_session.updated_at = datetime.now(UTC) - timedelta(hours=25)
        db.commit()
    finally:
        db.close()

    response = client.post(f"/classification/sessions/{session['id']}/propose")

    assert response.status_code == HTTP_CONFLICT
    assert response.json()["detail"] == "Session expired"


def test_delete_transaction_removes_classification_rows() -> None:
    """Verify delete transaction removes linked classification rows."""
    _reset_database()
    seed = _restore_transaction(description="PROXIMUS telecom invoice")
    follower = _restore_transaction(
        description="PROXIMUS telecom invoice", amount=-49.99
    )

    session = client.post(
        "/classification/sessions", json={"transaction_id": seed["id"]}
    ).json()
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
        follower_row = (
            db.query(Transaction).filter(Transaction.id == follower["id"]).first()
        )
        assert follower_row is not None
        follower_row.recurrence_pattern_id = accepted["recurrence_pattern_id"]
        db.commit()
    finally:
        db.close()

    response = client.delete(f"/transactions/{seed['id']}")

    assert response.status_code == HTTP_OK

    db = SessionLocal()
    try:
        assert (
            db.query(Transaction).filter(Transaction.id == seed["id"]).first() is None
        )
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
        refreshed_follower = (
            db.query(Transaction).filter(Transaction.id == follower["id"]).first()
        )
        assert refreshed_follower is not None
        assert refreshed_follower.recurrence_pattern_id is None
    finally:
        db.close()


def test_preview_similar_excludes_transfer_like_candidates_for_bill_seed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify preview similar excludes transfer like candidates for bill seed."""
    _reset_database()
    seed = _restore_transaction(description="PROXIMUS telecom invoice")
    transfer_like = _restore_transaction(
        description="Bancontact transfer Arne P2P MOBILE", amount=-4.0
    )
    utility_like = _restore_transaction(
        description="PROXIMUS telecom invoice April", amount=-86.99
    )

    session = client.post(
        "/classification/sessions", json={"transaction_id": seed["id"]}
    ).json()
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
    assert accept_response.status_code == HTTP_OK

    scores = {
        utility_like["description"].lower(): 0.92,
        transfer_like["description"].lower(): 0.89,
    }

    def fake_similarity_scores(
        source_text: str, candidate_texts: list[str]
    ) -> list[float]:
        assert source_text == seed["description"].lower()
        return [scores.get(candidate_text, 0.0) for candidate_text in candidate_texts]

    def fail_similarity_score(*_args: object, **_kwargs: object) -> Never:
        msg = "single-pair similarity_score should not be used"
        raise AssertionError(msg)

    monkeypatch.setattr(
        classification_session_service.category_suggestion_service,
        "similarity_scores",
        fake_similarity_scores,
    )
    monkeypatch.setattr(
        classification_session_service.category_suggestion_service,
        "similarity_score",
        fail_similarity_score,
    )

    response = client.post(f"/classification/sessions/{session['id']}/similar-preview")

    assert response.status_code == HTTP_OK
    payload = response.json()
    match_ids = {match["transaction_id"] for match in payload["matches"]}
    assert utility_like["id"] in match_ids
    assert transfer_like["id"] not in match_ids


def test_preview_similar_raises_when_batched_score_count_mismatches_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify preview similar raises when batched score count mismatches candidates."""
    _reset_database()
    seed = _restore_transaction(description="PROXIMUS telecom invoice")
    _restore_transaction(description="PROXIMUS telecom invoice April", amount=-86.99)

    session = client.post(
        "/classification/sessions", json={"transaction_id": seed["id"]}
    ).json()
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
    assert accept_response.status_code == HTTP_OK

    monkeypatch.setattr(
        classification_session_service.category_suggestion_service,
        "similarity_scores",
        lambda _source_text, _candidate_texts: [],
    )

    with pytest.raises(
        RuntimeError, match="similarity_scores returned 0 scores for 1 candidates"
    ):
        client.post(f"/classification/sessions/{session['id']}/similar-preview")


def test_preview_similar_skips_already_transfer_classified_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify preview similar skips already transfer classified candidates."""
    _reset_database()
    seed = _restore_transaction(
        description="Transfer to savings account", amount=-200.0
    )
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

    session = client.post(
        "/classification/sessions", json={"transaction_id": seed["id"]}
    ).json()
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
    assert accept_response.status_code == HTTP_OK

    scores = {
        uncategorized["description"].lower(): 0.93,
        already_classified["description"].lower(): 0.92,
    }

    def fake_similarity_scores(
        _source_text: str,
        candidate_texts: list[str],
    ) -> list[float]:
        return [scores.get(candidate_text, 0.0) for candidate_text in candidate_texts]

    monkeypatch.setattr(
        classification_session_service.category_suggestion_service,
        "similarity_scores",
        fake_similarity_scores,
    )

    response = client.post(f"/classification/sessions/{session['id']}/similar-preview")

    assert response.status_code == HTTP_OK
    match_ids = {match["transaction_id"] for match in response.json()["matches"]}
    assert uncategorized["id"] in match_ids
    assert already_classified["id"] not in match_ids


def test_apply_batch_skips_already_transfer_classified_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify apply batch skips already transfer classified candidates."""
    _reset_database()
    seed = _restore_transaction(
        description="Transfer to savings account", amount=-200.0
    )
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

    session = client.post(
        "/classification/sessions", json={"transaction_id": seed["id"]}
    ).json()
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
    assert accept_response.status_code == HTTP_OK

    scores = {
        uncategorized["description"].lower(): 0.93,
        already_classified["description"].lower(): 0.92,
    }

    def fake_similarity_scores(
        _source_text: str,
        candidate_texts: list[str],
    ) -> list[float]:
        return [scores.get(candidate_text, 0.0) for candidate_text in candidate_texts]

    monkeypatch.setattr(
        classification_session_service.category_suggestion_service,
        "similarity_scores",
        fake_similarity_scores,
    )

    response = client.post(
        f"/classification/sessions/{session['id']}/apply-batch",
        json={"transaction_ids": [uncategorized["id"], already_classified["id"]]},
    )

    assert response.status_code == HTTP_OK
    payload = response.json()
    assert payload["applied_transaction_ids"] == [uncategorized["id"]]
    assert payload["skipped_transaction_ids"] == [already_classified["id"]]

    db = SessionLocal()
    try:
        refreshed_uncategorized = (
            db.query(Transaction).filter(Transaction.id == uncategorized["id"]).first()
        )
        refreshed_classified = (
            db.query(Transaction)
            .filter(Transaction.id == already_classified["id"])
            .first()
        )
    finally:
        db.close()

    assert refreshed_uncategorized is not None
    assert (
        refreshed_uncategorized.transfer_category
        == TransferCategory.CREDIT_CARD_SETTLEMENT
    )
    assert refreshed_uncategorized.expense_category is None
    assert refreshed_uncategorized.income_category is None
    assert refreshed_classified is not None
    assert refreshed_classified.transfer_category == TransferCategory.INTERNAL_TRANSFER


def test_apply_batch_can_apply_every_high_confidence_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify apply batch can apply every high confidence match."""
    _reset_database()
    seed = _restore_transaction(description="Uber UBER * PENDING | SAO PAULO | BRA")
    matches = [
        _restore_transaction(
            description=f"Uber UBER * PENDING | SAO PAULO | BRA {index}",
            amount=-2.0 - index,
        )
        for index in range(4)
    ]

    session = client.post(
        "/classification/sessions", json={"transaction_id": seed["id"]}
    ).json()
    accept_response = client.post(
        f"/classification/sessions/{session['id']}/accept",
        json={
            "transaction_type": TransactionType.EXPENSE.value,
            "category": ExpenseCategory.TRANSPORTATION.value,
            "classification_source": "assistant",
            "confirm_type_change": False,
            "recurrence": {"is_recurrent": False},
        },
    )
    assert accept_response.status_code == HTTP_OK

    def high_similarity_scores(
        _source_text: str,
        candidate_texts: list[str],
    ) -> list[float]:
        return [HIGH_SIMILARITY_SCORE for _ in candidate_texts]

    monkeypatch.setattr(
        classification_session_service.category_suggestion_service,
        "similarity_scores",
        high_similarity_scores,
    )

    preview_response = client.post(
        f"/classification/sessions/{session['id']}/similar-preview"
    )

    assert preview_response.status_code == HTTP_OK
    preview_ids = [
        match["transaction_id"] for match in preview_response.json()["matches"]
    ]
    expected_ids = [match["id"] for match in matches]
    assert preview_ids == expected_ids

    apply_response = client.post(
        f"/classification/sessions/{session['id']}/apply-batch",
        json={"transaction_ids": preview_ids},
    )

    assert apply_response.status_code == HTTP_OK
    payload = apply_response.json()
    assert payload["applied_transaction_ids"] == expected_ids
    assert payload["skipped_transaction_ids"] == []


def test_get_transactions_category_filter_matches_transfer_category() -> None:
    """Verify get transactions category filter matches transfer category."""
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
        params={
            "category": TransferCategory.CREDIT_CARD_SETTLEMENT.value,
            "page_size": 20,
        },
    )

    assert response.status_code == HTTP_OK
    payload = response.json()
    assert payload["total"] == 1
    assert [item["id"] for item in payload["items"]] == [transfer["id"]]
    assert (
        payload["items"][0]["transfer_category"]
        == TransferCategory.CREDIT_CARD_SETTLEMENT.value
    )
