"""Module for backend tests test_upload_trust_order."""

import csv
import io
from dataclasses import replace
from typing import Any, Never

import pytest
from app.config import settings as app_settings
from app.database import SessionLocal
from app.imports import enrichment as import_enrichment
from app.imports import workflow as import_workflow
from app.main import app
from app.models.classification import RecurrencePattern
from app.models.transaction import Transaction
from app.routers import imports as imports_router
from app.routers.suggestions import category_suggestion_service
from app.services import classification_session_service
from fastapi.testclient import TestClient
from qdrant_client.http import models

client: Any = TestClient(app)
HTTP_OK: int = 200
DEFAULT_TRANSACTION_AMOUNT: float = -45.99
SUGGESTION_CONFIDENCE: float = 0.91


@pytest.fixture(autouse=True)
def _enable_runtime_stub_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        classification_session_service,
        "settings",
        replace(app_settings, provider_config_path=app_settings.provider_example_path),
    )


def _reset_rate_limiter() -> None:
    try:
        imports_router._upload_attempts.clear()
    except AttributeError:
        return


def _reset_database() -> None:
    response = client.post("/debug/reset-database")
    assert response.status_code == HTTP_OK


def _clear_vector_collections() -> None:
    category_suggestion_service.client.recreate_collection(
        collection_name="expense_embeddings",
        vectors_config=models.VectorParams(size=384, distance=models.Distance.COSINE),
    )
    category_suggestion_service.client.recreate_collection(
        collection_name="income_embeddings",
        vectors_config=models.VectorParams(size=384, distance=models.Distance.COSINE),
    )


def _restore_transaction(
    **fields: object,
) -> dict[str, Any]:
    description = fields.pop("description")
    tx_date = fields.pop("tx_date")
    amount = fields.pop("amount", DEFAULT_TRANSACTION_AMOUNT)
    transaction_type = fields.pop("transaction_type", "Expense")
    source_bank = fields.pop("source_bank", "Belfius")
    expense_category = fields.pop("expense_category", None)
    assert fields == {}
    payload = {
        "account_number": "BE46000000000001",
        "transaction_date": tx_date,
        "amount": amount,
        "currency": "EUR",
        "description": description,
        "counterparty_name": "Counterparty",
        "counterparty_account": "BE99000000000002",
        "transaction_type": transaction_type,
        "source_bank": source_bank,
    }
    if expense_category is not None:
        payload["expense_category"] = expense_category

    response = client.post("/transactions/restore", json=payload)
    assert response.status_code == HTTP_OK
    return response.json()


def _accept_session(
    transaction_id: int,
    *,
    transaction_type: str,
    category: str,
    recurrence: dict[str, object] | None = None,
    confirm_type_change: bool = False,
) -> dict[str, Any]:
    session = client.post(
        "/classification/sessions", json={"transaction_id": transaction_id}
    ).json()
    propose_response = client.post(f"/classification/sessions/{session['id']}/propose")
    assert propose_response.status_code == HTTP_OK

    accept_response = client.post(
        f"/classification/sessions/{session['id']}/accept",
        json={
            "transaction_type": transaction_type,
            "category": category,
            "classification_source": "assistant",
            "confirm_type_change": confirm_type_change,
            "recurrence": recurrence or {"is_recurrent": False},
        },
    )
    assert accept_response.status_code == HTTP_OK
    return accept_response.json()


def _accept_utilities_session(transaction_id: int) -> dict[str, Any]:
    return _accept_session(
        transaction_id,
        transaction_type="Expense",
        category="Utilities",
    )


def _make_minimal_belfius_export_csv(*, booking_date: str, description: str) -> bytes:
    return _make_belfius_export_csv_rows((booking_date, description))


def _make_belfius_export_csv_rows(*rows: tuple[str, str]) -> bytes:
    first_booking_date = rows[0][0]
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Boekingsdatum vanaf", first_booking_date])
    writer.writerow(["Boekingsdatum tot en met", rows[-1][0]])
    writer.writerow(["Bedrag vanaf", ""])
    writer.writerow(["Bedrag tot en met", ""])
    writer.writerow(["Rekeninguittrekselnummer vanaf", ""])
    writer.writerow(["Rekeninguittrekselnummer tot en met", ""])
    writer.writerow(["Mededeling", ""])
    writer.writerow(["Naam tegenpartij bevat", ""])
    writer.writerow(["Rekening tegenpartij", ""])
    writer.writerow(["Laatste saldo", "-140,40 EUR"])
    writer.writerow(["Datum/uur van het laatste saldo", "11/04/2026 13:14:53"])
    writer.writerow(["", ""])
    writer.writerow(
        [
            "Rekening",
            "Boekingsdatum",
            "Rekeninguittrekselnummer",
            "Transactienummer",
            "Rekening tegenpartij",
            "Naam tegenpartij bevat",
            "Straat en nummer",
            "Postcode en plaats",
            "Transactie",
            "Valutadatum",
            "Bedrag",
            "Devies",
            "BIC",
            "Landcode",
            "Mededelingen",
        ]
    )
    for index, (booking_date, description) in enumerate(rows, start=33):
        writer.writerow(
            [
                "BE46 0636 5194 6836",
                booking_date,
                "00004",
                str(index),
                "",
                "",
                "",
                "",
                description,
                booking_date,
                "-45,99",
                "EUR",
                "",
                "",
                description,
            ]
        )
    return output.getvalue().encode("utf-8")


def _make_minimal_beobank_compact_csv(*, booking_date: str, description: str) -> bytes:
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(
        [
            "Datum",
            "Waardedatum",
            "Debet",
            "Krediet",
            "Omschrijving",
            "Saldo",
        ]
    )
    writer.writerow(
        [
            booking_date,
            booking_date,
            "-45,99",
            "",
            description,
            "375,53",
        ]
    )
    return output.getvalue().encode("latin-1")


def _upload_csv_for_review(*, filename: str, payload: bytes) -> dict[str, Any]:
    response = client.post(
        "/imports/upload",
        files={"file": (filename, payload, "text/csv")},
    )
    assert response.status_code == HTTP_OK
    return response.json()


def _approve_import_session(session_id: int) -> dict[str, Any]:
    response = client.post(f"/imports/{session_id}/approve")
    assert response.status_code == HTTP_OK
    return response.json()


def _latest_transaction() -> Transaction | None:
    db = SessionLocal()
    try:
        return db.query(Transaction).order_by(Transaction.id.desc()).first()
    finally:
        db.close()


def test_similar_preview_only_returns_uncategorized_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify similar preview only returns uncategorized rows."""
    _reset_rate_limiter()
    _reset_database()
    _clear_vector_collections()

    seed = _restore_transaction(
        description="SEPA PROXIMUS telecom invoice", tx_date="2026-04-10"
    )
    expected_match = _restore_transaction(
        description="SEPA PROXIMUS telecom invoice april", tx_date="2026-04-11"
    )
    _restore_transaction(
        description="SEPA PROXIMUS telecom invoice may",
        tx_date="2026-04-12",
        expense_category="Utilities",
    )
    _restore_transaction(description="LOCAL bakery card purchase", tx_date="2026-04-13")
    transfer_candidate = _restore_transaction(
        description="SEPA PROXIMUS telecom invoice transfer",
        tx_date="2026-04-14",
        transaction_type="Transfer",
    )

    accepted = _accept_utilities_session(seed["id"])

    def fake_similarity_scores(
        source_text: str, candidate_texts: list[str]
    ) -> list[float]:
        return [
            SUGGESTION_CONFIDENCE
            if "proximus" in source_text and "proximus" in candidate_text
            else 0.12
            for candidate_text in candidate_texts
        ]

    monkeypatch.setattr(
        category_suggestion_service, "similarity_scores", fake_similarity_scores
    )

    preview = client.post(
        f"/classification/sessions/{accepted['session']['id']}/similar-preview"
    )

    assert preview.status_code == HTTP_OK
    payload = preview.json()
    assert [match["transaction_id"] for match in payload["matches"]] == [
        expected_match["id"]
    ]
    assert transfer_candidate["id"] not in [
        match["transaction_id"] for match in payload["matches"]
    ]


def test_apply_batch_skips_rows_that_are_already_categorized() -> None:
    """Verify apply batch skips rows that are already categorized."""
    _reset_rate_limiter()
    _reset_database()
    _clear_vector_collections()

    seed = _restore_transaction(
        description="SEPA PROXIMUS telecom invoice", tx_date="2026-04-10"
    )
    match_one = _restore_transaction(
        description="SEPA PROXIMUS telecom invoice april", tx_date="2026-04-11"
    )
    match_two = _restore_transaction(
        description="SEPA PROXIMUS telecom invoice may", tx_date="2026-04-12"
    )

    accepted = _accept_utilities_session(seed["id"])

    patch_response = client.patch(
        f"/transactions/{match_two['id']}/category",
        params={"category": "Utilities", "transaction_type": "Expense"},
    )
    assert patch_response.status_code == HTTP_OK

    response = client.post(
        f"/classification/sessions/{accepted['session']['id']}/apply-batch",
        json={"transaction_ids": [match_one["id"], match_two["id"]]},
    )

    assert response.status_code == HTTP_OK
    payload = response.json()
    assert payload["applied_transaction_ids"] == [match_one["id"]]
    assert payload["skipped_transaction_ids"] == [match_two["id"]]

    db = SessionLocal()
    try:
        updated_match_one = (
            db.query(Transaction).filter(Transaction.id == match_one["id"]).first()
        )
        updated_match_two = (
            db.query(Transaction).filter(Transaction.id == match_two["id"]).first()
        )
    finally:
        db.close()

    assert updated_match_one is not None
    assert updated_match_one.expense_category is not None
    assert updated_match_one.expense_category.value == "Utilities"
    assert updated_match_one.classification_source == "assistant_batch"
    assert updated_match_two is not None
    assert updated_match_two.classification_source == "manual"


def test_apply_batch_skips_uncategorized_rows_that_are_not_preview_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify apply batch skips uncategorized rows that are not preview matches."""
    _reset_rate_limiter()
    _reset_database()
    _clear_vector_collections()

    seed = _restore_transaction(
        description="SEPA PROXIMUS telecom invoice", tx_date="2026-04-10"
    )
    match_one = _restore_transaction(
        description="SEPA PROXIMUS telecom invoice april", tx_date="2026-04-11"
    )
    unrelated = _restore_transaction(
        description="LOCAL bakery card purchase", tx_date="2026-04-12"
    )

    accepted = _accept_utilities_session(seed["id"])

    def fake_similarity_scores(
        source_text: str, candidate_texts: list[str]
    ) -> list[float]:
        return [
            SUGGESTION_CONFIDENCE
            if "proximus" in source_text and "proximus" in candidate_text
            else 0.12
            for candidate_text in candidate_texts
        ]

    monkeypatch.setattr(
        category_suggestion_service, "similarity_scores", fake_similarity_scores
    )

    response = client.post(
        f"/classification/sessions/{accepted['session']['id']}/apply-batch",
        json={"transaction_ids": [match_one["id"], unrelated["id"]]},
    )

    assert response.status_code == HTTP_OK
    payload = response.json()
    assert payload["applied_transaction_ids"] == [match_one["id"]]
    assert payload["skipped_transaction_ids"] == [unrelated["id"]]


def test_recurrence_pattern_wins_before_upload_suggester(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify recurrence pattern wins before upload suggester."""
    _reset_rate_limiter()
    _reset_database()
    _clear_vector_collections()

    first_upload = _upload_csv_for_review(
        filename="BE46 0636 5194 6836 2026-04-11 13-17-27 1.csv",
        payload=_make_minimal_belfius_export_csv(
            booking_date="10/04/2026",
            description="PROXIMUS telecom invoice",
        ),
    )
    assert first_upload["status"] == "awaiting_review"
    _approve_import_session(first_upload["id"])
    seed_transaction = _latest_transaction()
    assert seed_transaction is not None
    session = client.post(
        "/classification/sessions", json={"transaction_id": seed_transaction.id}
    ).json()
    propose_response = client.post(f"/classification/sessions/{session['id']}/propose")
    assert propose_response.status_code == HTTP_OK

    accept_response = client.post(
        f"/classification/sessions/{session['id']}/accept",
        json={
            "transaction_type": "Expense",
            "category": "Utilities",
            "classification_source": "assistant",
            "confirm_type_change": False,
            "recurrence": {"is_recurrent": True, "frequency": "monthly"},
        },
    )
    assert accept_response.status_code == HTTP_OK
    pattern_id = accept_response.json()["recurrence_pattern_id"]

    def _unexpected_suggester(*_args: object, **_kwargs: object) -> Never:
        msg = "upload suggester should not run when a recurrence pattern matches"
        raise AssertionError(msg)

    monkeypatch.setattr(
        import_enrichment.category_suggestion_service,
        "suggest_category",
        _unexpected_suggester,
    )

    second_upload = _upload_csv_for_review(
        filename="BE46 0636 5194 6836 2026-05-11 13-17-27 1.csv",
        payload=_make_minimal_belfius_export_csv(
            booking_date="11/05/2026",
            description="PROXIMUS telecom invoice",
        ),
    )
    assert second_upload["status"] == "awaiting_review"
    _approve_import_session(second_upload["id"])
    imported_transaction = _latest_transaction()
    assert imported_transaction is not None
    assert imported_transaction.expense_category is not None
    assert imported_transaction.expense_category.value == "Utilities"
    assert imported_transaction.classification_source == "recurrence_pattern"
    assert imported_transaction.recurrence_pattern_id == pattern_id

    manual_override = client.patch(
        f"/transactions/{imported_transaction.id}/category",
        params={"category": "Entertainment", "transaction_type": "Expense"},
    )
    assert manual_override.status_code == HTTP_OK
    assert manual_override.json()["expense_category"] == "Entertainment"
    assert manual_override.json()["classification_source"] == "manual"

    db = SessionLocal()
    try:
        stored_pattern = (
            db.query(RecurrencePattern)
            .filter(RecurrencePattern.id == pattern_id)
            .first()
        )
    finally:
        db.close()

    assert stored_pattern is not None
    assert stored_pattern.active is True


def test_transfer_recurrence_overrides_seeded_type_for_reviewed_csv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify transfer recurrence overrides seeded type for reviewed CSV."""
    _reset_rate_limiter()
    _reset_database()
    _clear_vector_collections()

    seed = _restore_transaction(
        description="BANK TRANSFER to savings",
        tx_date="2026-04-10",
        transaction_type="Transfer",
    )
    accepted = _accept_session(
        seed["id"],
        transaction_type="Transfer",
        category="Internal Transfer",
        recurrence={"is_recurrent": True, "frequency": "monthly"},
    )
    pattern_id = accepted["recurrence_pattern_id"]

    def _unexpected_suggester(*_args: object, **_kwargs: object) -> Never:
        msg = (
            "upload suggester should not run when a transfer recurrence pattern matches"
        )
        raise AssertionError(msg)

    monkeypatch.setattr(
        import_enrichment.category_suggestion_service,
        "suggest_category",
        _unexpected_suggester,
    )

    review_session = _upload_csv_for_review(
        filename="BE46 0636 5194 6836 2026-05-11 13-17-27 1.csv",
        payload=_make_minimal_belfius_export_csv(
            booking_date="11/05/2026",
            description="BANK TRANSFER to savings",
        ),
    )
    assert review_session["status"] == "awaiting_review"

    approve_response = client.post(f"/imports/{review_session['id']}/approve")
    assert approve_response.status_code == HTTP_OK

    imported_transaction = _latest_transaction()
    assert imported_transaction is not None
    assert imported_transaction.transaction_type.value == "Transfer"
    assert imported_transaction.transfer_category is not None
    assert imported_transaction.transfer_category.value == "Internal Transfer"
    assert imported_transaction.expense_category is None
    assert imported_transaction.classification_source == "recurrence_pattern"
    assert imported_transaction.recurrence_pattern_id == pattern_id


def test_recurrence_pattern_can_apply_across_banks_when_exact_bank_match_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify recurrence pattern applies across banks without exact bank match."""
    _reset_rate_limiter()
    _reset_database()
    _clear_vector_collections()

    seed = _restore_transaction(
        description="PROXIMUS telecom invoice",
        tx_date="2026-04-10",
        source_bank="Belfius",
    )
    accepted = _accept_session(
        seed["id"],
        transaction_type="Expense",
        category="Utilities",
        recurrence={"is_recurrent": True, "frequency": "monthly"},
    )
    pattern_id = accepted["recurrence_pattern_id"]

    def _unexpected_suggester(*_args: object, **_kwargs: object) -> Never:
        msg = (
            "upload suggester should not run when a compatible recurrence pattern "
            "exists"
        )
        raise AssertionError(msg)

    monkeypatch.setattr(
        import_enrichment.category_suggestion_service,
        "suggest_category",
        _unexpected_suggester,
    )

    second_upload = _upload_csv_for_review(
        filename="50212984548.csv",
        payload=_make_minimal_beobank_compact_csv(
            booking_date="11/05/2026",
            description="PROXIMUS telecom invoice",
        ),
    )
    assert second_upload["status"] == "awaiting_review"
    _approve_import_session(second_upload["id"])

    imported_transaction = _latest_transaction()
    assert imported_transaction is not None
    assert imported_transaction.source_bank == "Beobank"
    assert imported_transaction.expense_category is not None
    assert imported_transaction.expense_category.value == "Utilities"
    assert imported_transaction.classification_source == "recurrence_pattern"
    assert imported_transaction.recurrence_pattern_id == pattern_id


def test_upload_csv_is_atomic_when_auto_classification_fails_mid_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify upload csv is atomic when auto classification fails mid file."""
    _reset_rate_limiter()
    _reset_database()
    _clear_vector_collections()

    calls = 0

    def flaky_suggester(
        *_args: object,
        **_kwargs: object,
    ) -> list[tuple[str, float]]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return [("Utilities", SUGGESTION_CONFIDENCE)]
        msg = "simulated suggester failure"
        raise RuntimeError(msg)

    monkeypatch.setattr(
        import_enrichment.category_suggestion_service,
        "suggest_category",
        flaky_suggester,
    )

    response = _upload_csv_for_review(
        filename="data.csv",
        payload=_make_belfius_export_csv_rows(
            ("01/05/2026", "PROXIMUS invoice"),
            ("02/05/2026", "Bakery purchase"),
        ),
    )
    assert response["status"] == "failed"
    assert response["error_stage"] == "extraction"
    assert "simulated suggester failure" in response["error_message"]

    db = SessionLocal()
    try:
        transaction_count = db.query(Transaction).count()
    finally:
        db.close()

    assert transaction_count == 0


def test_upload_csv_still_succeeds_when_post_commit_learning_update_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify upload csv still succeeds when post commit learning update fails."""
    _reset_rate_limiter()
    _reset_database()
    _clear_vector_collections()

    def suggest_utilities(
        *_args: object,
        **_kwargs: object,
    ) -> list[tuple[str, float]]:
        return [("Utilities", SUGGESTION_CONFIDENCE)]

    monkeypatch.setattr(
        import_enrichment.category_suggestion_service,
        "suggest_category",
        suggest_utilities,
    )

    def broken_add_transaction(*_args: object, **_kwargs: object) -> Never:
        msg = "simulated index update failure"
        raise RuntimeError(msg)

    monkeypatch.setattr(
        import_workflow.category_suggestion_service,
        "add_transaction",
        broken_add_transaction,
    )

    session = _upload_csv_for_review(
        filename="data.csv",
        payload=_make_minimal_belfius_export_csv(
            booking_date="01/05/2026",
            description="PROXIMUS invoice",
        ),
    )
    assert session["status"] == "awaiting_review"

    response = _approve_import_session(session["id"])
    assert response["status"] == "committed"

    db = SessionLocal()
    try:
        transaction_count = db.query(Transaction).count()
    finally:
        db.close()

    assert transaction_count == 1
