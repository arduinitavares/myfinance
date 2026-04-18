import csv
import io
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from qdrant_client.http import models

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


client = TestClient(app)


@pytest.fixture(autouse=True)
def _enable_runtime_stub_provider(monkeypatch):
    monkeypatch.setattr(
        classification_session_service,
        "settings",
        replace(app_settings, provider_config_path=app_settings.provider_example_path),
    )


def _reset_rate_limiter():
    try:
        imports_router._upload_attempts.clear()  # type: ignore[attr-defined]
    except Exception:
        pass


def _reset_database():
    response = client.post("/debug/reset-database")
    assert response.status_code == 200


def _clear_vector_collections():
    category_suggestion_service.client.recreate_collection(
        collection_name="expense_embeddings",
        vectors_config=models.VectorParams(size=384, distance=models.Distance.COSINE),
    )
    category_suggestion_service.client.recreate_collection(
        collection_name="income_embeddings",
        vectors_config=models.VectorParams(size=384, distance=models.Distance.COSINE),
    )


def _restore_transaction(
    *,
    description: str,
    tx_date: str,
    amount: float = -45.99,
    transaction_type: str = "Expense",
    source_bank: str = "Belfius",
    expense_category: str | None = None,
):
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
    assert response.status_code == 200
    return response.json()


def _accept_session(
    transaction_id: int,
    *,
    transaction_type: str,
    category: str,
    recurrence: dict | None = None,
    confirm_type_change: bool = False,
):
    session = client.post("/classification/sessions", json={"transaction_id": transaction_id}).json()
    propose_response = client.post(f"/classification/sessions/{session['id']}/propose")
    assert propose_response.status_code == 200

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
    assert accept_response.status_code == 200
    return accept_response.json()


def _accept_utilities_session(transaction_id: int):
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


def _upload_csv_for_review(*, filename: str, payload: bytes) -> dict:
    response = client.post(
        "/imports/upload",
        files={"file": (filename, payload, "text/csv")},
    )
    assert response.status_code == 200
    return response.json()


def _approve_import_session(session_id: int) -> dict:
    response = client.post(f"/imports/{session_id}/approve")
    assert response.status_code == 200
    return response.json()


def _latest_transaction() -> Transaction | None:
    db = SessionLocal()
    try:
        return db.query(Transaction).order_by(Transaction.id.desc()).first()
    finally:
        db.close()


def test_similar_preview_only_returns_uncategorized_rows(monkeypatch):
    _reset_rate_limiter()
    _reset_database()
    _clear_vector_collections()

    seed = _restore_transaction(description="SEPA PROXIMUS telecom invoice", tx_date="2026-04-10")
    expected_match = _restore_transaction(description="SEPA PROXIMUS telecom invoice april", tx_date="2026-04-11")
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

    def fake_similarity(source_text: str, candidate_text: str) -> float:
        if "proximus" in source_text and "proximus" in candidate_text:
            return 0.91
        return 0.12

    monkeypatch.setattr(category_suggestion_service, "similarity_score", fake_similarity)

    preview = client.post(
        f"/classification/sessions/{accepted['session']['id']}/similar-preview"
    )

    assert preview.status_code == 200
    payload = preview.json()
    assert [match["transaction_id"] for match in payload["matches"]] == [expected_match["id"]]
    assert transfer_candidate["id"] not in [match["transaction_id"] for match in payload["matches"]]


def test_apply_batch_skips_rows_that_are_already_categorized():
    _reset_rate_limiter()
    _reset_database()
    _clear_vector_collections()

    seed = _restore_transaction(description="SEPA PROXIMUS telecom invoice", tx_date="2026-04-10")
    match_one = _restore_transaction(description="SEPA PROXIMUS telecom invoice april", tx_date="2026-04-11")
    match_two = _restore_transaction(description="SEPA PROXIMUS telecom invoice may", tx_date="2026-04-12")

    accepted = _accept_utilities_session(seed["id"])

    patch_response = client.patch(
        f"/transactions/{match_two['id']}/category",
        params={"category": "Utilities", "transaction_type": "Expense"},
    )
    assert patch_response.status_code == 200

    response = client.post(
        f"/classification/sessions/{accepted['session']['id']}/apply-batch",
        json={"transaction_ids": [match_one["id"], match_two["id"]]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["applied_transaction_ids"] == [match_one["id"]]
    assert payload["skipped_transaction_ids"] == [match_two["id"]]

    db = SessionLocal()
    try:
        updated_match_one = db.query(Transaction).filter(Transaction.id == match_one["id"]).first()
        updated_match_two = db.query(Transaction).filter(Transaction.id == match_two["id"]).first()
    finally:
        db.close()

    assert updated_match_one is not None
    assert updated_match_one.expense_category.value == "Utilities"
    assert updated_match_one.classification_source == "assistant_batch"
    assert updated_match_two is not None
    assert updated_match_two.classification_source == "manual"


def test_apply_batch_skips_uncategorized_rows_that_are_not_preview_matches(monkeypatch):
    _reset_rate_limiter()
    _reset_database()
    _clear_vector_collections()

    seed = _restore_transaction(description="SEPA PROXIMUS telecom invoice", tx_date="2026-04-10")
    match_one = _restore_transaction(description="SEPA PROXIMUS telecom invoice april", tx_date="2026-04-11")
    unrelated = _restore_transaction(description="LOCAL bakery card purchase", tx_date="2026-04-12")

    accepted = _accept_utilities_session(seed["id"])

    def fake_similarity(source_text: str, candidate_text: str) -> float:
        if "proximus" in source_text and "proximus" in candidate_text:
            return 0.91
        return 0.12

    monkeypatch.setattr(category_suggestion_service, "similarity_score", fake_similarity)

    response = client.post(
        f"/classification/sessions/{accepted['session']['id']}/apply-batch",
        json={"transaction_ids": [match_one["id"], unrelated["id"]]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["applied_transaction_ids"] == [match_one["id"]]
    assert payload["skipped_transaction_ids"] == [unrelated["id"]]


def test_recurrence_pattern_wins_before_upload_suggester_and_manual_override_keeps_pattern_active(monkeypatch):
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
    session = client.post("/classification/sessions", json={"transaction_id": seed_transaction.id}).json()
    propose_response = client.post(f"/classification/sessions/{session['id']}/propose")
    assert propose_response.status_code == 200

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
    assert accept_response.status_code == 200
    pattern_id = accept_response.json()["recurrence_pattern_id"]

    def _unexpected_suggester(*args, **kwargs):
        raise AssertionError("upload suggester should not run when a recurrence pattern matches")

    monkeypatch.setattr(import_enrichment.category_suggestion_service, "suggest_category", _unexpected_suggester)

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
    assert imported_transaction.expense_category.value == "Utilities"
    assert imported_transaction.classification_source == "recurrence_pattern"
    assert imported_transaction.recurrence_pattern_id == pattern_id

    manual_override = client.patch(
        f"/transactions/{imported_transaction.id}/category",
        params={"category": "Entertainment", "transaction_type": "Expense"},
    )
    assert manual_override.status_code == 200
    assert manual_override.json()["expense_category"] == "Entertainment"
    assert manual_override.json()["classification_source"] == "manual"

    db = SessionLocal()
    try:
        stored_pattern = db.query(RecurrencePattern).filter(RecurrencePattern.id == pattern_id).first()
    finally:
        db.close()

    assert stored_pattern is not None
    assert stored_pattern.active is True


def test_transfer_recurrence_pattern_overrides_seeded_sign_based_type_for_reviewed_csv_upload(monkeypatch):
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

    def _unexpected_suggester(*args, **kwargs):
        raise AssertionError("upload suggester should not run when a transfer recurrence pattern matches")

    monkeypatch.setattr(import_enrichment.category_suggestion_service, "suggest_category", _unexpected_suggester)

    review_session = _upload_csv_for_review(
        filename="BE46 0636 5194 6836 2026-05-11 13-17-27 1.csv",
        payload=_make_minimal_belfius_export_csv(
            booking_date="11/05/2026",
            description="BANK TRANSFER to savings",
        ),
    )
    assert review_session["status"] == "awaiting_review"

    approve_response = client.post(f"/imports/{review_session['id']}/approve")
    assert approve_response.status_code == 200

    imported_transaction = _latest_transaction()
    assert imported_transaction is not None
    assert imported_transaction.transaction_type.value == "Transfer"
    assert imported_transaction.transfer_category.value == "Internal Transfer"
    assert imported_transaction.expense_category is None
    assert imported_transaction.classification_source == "recurrence_pattern"
    assert imported_transaction.recurrence_pattern_id == pattern_id


def test_recurrence_pattern_can_apply_across_banks_when_exact_bank_match_is_missing(monkeypatch):
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

    def _unexpected_suggester(*args, **kwargs):
        raise AssertionError("upload suggester should not run when a compatible recurrence pattern exists")

    monkeypatch.setattr(import_enrichment.category_suggestion_service, "suggest_category", _unexpected_suggester)

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
    assert imported_transaction.expense_category.value == "Utilities"
    assert imported_transaction.classification_source == "recurrence_pattern"
    assert imported_transaction.recurrence_pattern_id == pattern_id


def test_upload_csv_is_atomic_when_auto_classification_fails_mid_file(monkeypatch):
    _reset_rate_limiter()
    _reset_database()
    _clear_vector_collections()

    calls = 0

    def flaky_suggester(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return [("Utilities", 0.91)]
        raise RuntimeError("simulated suggester failure")

    monkeypatch.setattr(import_enrichment.category_suggestion_service, "suggest_category", flaky_suggester)

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


def test_upload_csv_still_succeeds_when_post_commit_learning_update_fails(monkeypatch):
    _reset_rate_limiter()
    _reset_database()
    _clear_vector_collections()

    monkeypatch.setattr(
        import_enrichment.category_suggestion_service,
        "suggest_category",
        lambda *args, **kwargs: [("Utilities", 0.91)],
    )

    def broken_add_transaction(*args, **kwargs):
        raise RuntimeError("simulated index update failure")

    monkeypatch.setattr(import_workflow.category_suggestion_service, "add_transaction", broken_add_transaction)

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
