"""Module for backend tests test_manual_edit_updates_index."""

from typing import Any

from app.main import app
from app.routers.suggestions import category_suggestion_service
from fastapi.testclient import TestClient

client: Any = TestClient(app)
HTTP_OK: int = 200


def _reset_database() -> None:
    # Use the debug endpoint to reset the DB between tests
    resp = client.post("/debug/reset-database")
    assert resp.status_code == HTTP_OK


def _clear_vector_collections() -> None:
    # Ensure vector DB is empty and deterministic for the test
    category_suggestion_service.reset_collection(
        collection_name="expense_embeddings"
    )
    category_suggestion_service.reset_collection(
        collection_name="income_embeddings"
    )


def test_manual_category_edit_updates_suggestion_index() -> None:
    """Verify manual category edit updates suggestion index."""
    _reset_database()
    _clear_vector_collections()

    resp = client.post(
        "/transactions/restore",
        json={
            "account_number": "BE1234567890",
            "transaction_date": "2025-01-01",
            "amount": -12.34,
            "currency": "EUR",
            "description": "Test Coffee Shop",
            "counterparty_name": "Counterparty",
            "counterparty_account": "BE0987654321",
            "transaction_type": "Expense",
            "source_bank": "ING",
        },
    )
    assert resp.status_code == HTTP_OK
    tx_id = resp.json()["id"]

    # 2) Manually update category to GROCERIES (expense)
    patch_url = f"/transactions/{tx_id}/category"
    resp = client.patch(
        patch_url, params={"category": "Groceries", "transaction_type": "Expense"}
    )
    assert resp.status_code == HTTP_OK
    updated = resp.json()
    assert updated["expense_category"] == "Groceries"

    # 3) Verify the vector index contains this transaction under expense_embeddings
    retrieved = category_suggestion_service.client.retrieve(
        collection_name="expense_embeddings", ids=[tx_id]
    )
    # Should retrieve exactly one point with our payload category
    assert retrieved
    assert len(retrieved) == 1
    point = retrieved[0]
    assert point.payload.get("category") == "Groceries"
