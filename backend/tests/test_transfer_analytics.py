import pytest
from fastapi.testclient import TestClient
from datetime import date

from app.models.transaction import ExpenseCategory, IncomeCategory, TransactionType, TransferCategory
from app.schemas.transaction import TransactionRestore


def _reset_database(client):
    response = client.post("/debug/reset-database")
    assert response.status_code == 200


def _restore_transaction(client, *, description: str):
    payload = {
        "account_number": "BE55000000000001",
        "transaction_date": "2025-01-15",
        "amount": -240.00,
        "currency": "EUR",
        "description": description,
        "counterparty_name": "Counterparty",
        "counterparty_account": "BE99000000000002",
        "transaction_type": TransactionType.TRANSFER.value,
        "expense_category": ExpenseCategory.INTERNAL_TRANSFER.value,
        "source_bank": "ing",
    }

    response = client.post("/transactions/restore", json=payload)
    assert response.status_code == 200
    return response.json()


@pytest.mark.xfail(
    strict=True,
    reason="Task 2 finishes the transfer commit/update path; this API check still depends on out-of-scope startup plumbing.",
)
def test_manual_transfer_update_uses_transfer_category_and_clears_legacy_categories():
    from app.main import app

    client = TestClient(app)
    _reset_database(client)
    transaction = _restore_transaction(client, description="Belfius card settlement")

    response = client.patch(
        f"/transactions/{transaction['id']}/category",
        params={
            "transaction_type": TransactionType.TRANSFER.value,
            "category": TransferCategory.CREDIT_CARD_SETTLEMENT.value,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["transaction_type"] == TransactionType.TRANSFER.value
    assert payload["transfer_category"] == TransferCategory.CREDIT_CARD_SETTLEMENT.value
    assert payload["expense_category"] is None
    assert payload["income_category"] is None


def test_transfer_schema_normalizes_legacy_transfer_rows_from_orm():
    class LegacyTransferRow:
        account_number = "BE55000000000001"
        transaction_date = date(2025, 1, 15)
        amount = -240.00
        currency = "EUR"
        description = "Belfius card settlement"
        counterparty_name = "Counterparty"
        counterparty_account = "BE99000000000002"
        transaction_type = TransactionType.TRANSFER
        expense_category = ExpenseCategory.INTERNAL_TRANSFER
        income_category = IncomeCategory.INTERNAL_TRANSFER
        transfer_category = None
        classification_source = None
        recurrence_pattern_id = None
        source_bank = "ing"

    transaction = TransactionRestore.model_validate(LegacyTransferRow(), from_attributes=True)

    assert transaction.transaction_type == TransactionType.TRANSFER
    assert transaction.transfer_category == TransferCategory.INTERNAL_TRANSFER
    assert transaction.expense_category is None
    assert transaction.income_category is None

    payload = transaction.model_dump(mode="json")
    assert payload["transaction_type"] == TransactionType.TRANSFER.value
    assert payload["transfer_category"] == TransferCategory.INTERNAL_TRANSFER.value
    assert payload["expense_category"] is None
    assert payload["income_category"] is None
