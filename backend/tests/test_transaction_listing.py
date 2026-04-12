from datetime import date

from fastapi.testclient import TestClient

from app.main import app
from app.models.transaction import ExpenseCategory, Transaction, TransactionType, TransferCategory


client = TestClient(app)


def _make_transaction(
    db_session,
    *,
    description: str,
    amount: float,
    transaction_type: TransactionType,
    expense_category=None,
    transfer_category=None,
):
    transaction = Transaction(
        account_number="BE12000000000001",
        transaction_date=date(2026, 2, 26),
        amount=amount,
        currency="EUR",
        description=description,
        counterparty_name="Counterparty",
        counterparty_account="BE12000000000002",
        transaction_type=transaction_type,
        expense_category=expense_category,
        transfer_category=transfer_category,
        source_bank="Beobank",
    )
    db_session.add(transaction)
    db_session.flush()
    return transaction


def test_get_transactions_filters_by_classification_status(db_session):
    _make_transaction(
        db_session,
        description="Categorized expense",
        amount=-45.99,
        transaction_type=TransactionType.EXPENSE,
        expense_category=ExpenseCategory.UTILITIES,
    )
    _make_transaction(
        db_session,
        description="Needs review",
        amount=-10.00,
        transaction_type=TransactionType.EXPENSE,
    )
    _make_transaction(
        db_session,
        description="Categorized transfer",
        amount=-545.00,
        transaction_type=TransactionType.TRANSFER,
        transfer_category=TransferCategory.INTERNAL_TRANSFER,
    )
    db_session.commit()

    classified = client.get("/transactions/", params={"classification_status": "classified"})
    assert classified.status_code == 200
    classified_payload = classified.json()
    assert classified_payload["total"] == 2
    assert {item["description"] for item in classified_payload["items"]} == {
        "Categorized expense",
        "Categorized transfer",
    }

    unclassified = client.get("/transactions/", params={"classification_status": "unclassified"})
    assert unclassified.status_code == 200
    unclassified_payload = unclassified.json()
    assert unclassified_payload["total"] == 1
    assert [item["description"] for item in unclassified_payload["items"]] == ["Needs review"]
