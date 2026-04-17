from datetime import date
from decimal import Decimal
from datetime import datetime

from fastapi.testclient import TestClient

from app.main import app
from app.models.fx import FXDailyReferenceRate
from app.models.transaction import ExpenseCategory, Transaction, TransactionType, TransferCategory


client = TestClient(app)


def _store_rate(
    db_session,
    *,
    rate_date: date,
    quoted_currency: str,
    units_per_base: str,
):
    db_session.add(
        FXDailyReferenceRate(
            rate_date=rate_date,
            base_currency="EUR",
            quoted_currency=quoted_currency,
            units_per_base=Decimal(units_per_base),
            source_name="ECB_EXR",
            fetched_at=datetime(2026, 4, 17, 8, 30, 0),
            updated_at=datetime(2026, 4, 17, 8, 30, 0),
        )
    )
    db_session.commit()


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


def test_get_transactions_includes_display_fields_for_selected_reporting_currency(db_session):
    _store_rate(
        db_session,
        rate_date=date(2026, 2, 26),
        quoted_currency="USD",
        units_per_base="1.2000",
    )
    _make_transaction(
        db_session,
        description="Imported grocery run",
        amount=-18.19,
        transaction_type=TransactionType.EXPENSE,
        expense_category=ExpenseCategory.GROCERIES,
    )
    db_session.commit()

    response = client.get(
        "/transactions/",
        headers={"X-Reporting-Currency": "USD"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    item = payload["items"][0]
    assert item["amount"] == -18.19
    assert item["currency"] == "EUR"
    assert item["display_amount"] == -21.83
    assert item["display_currency"] == "USD"
    assert item["display_fx_rate"] == 1.2
    assert item["display_rate_date"] == "2026-02-26"


def test_get_transactions_keeps_unavailable_display_shape_when_rate_missing(db_session):
    _make_transaction(
        db_session,
        description="USD card purchase",
        amount=-42.0,
        transaction_type=TransactionType.EXPENSE,
        expense_category=ExpenseCategory.SHOPPING,
    ).currency = "USD"
    db_session.commit()

    response = client.get(
        "/transactions/",
        headers={"X-Reporting-Currency": "BRL"},
    )

    assert response.status_code == 200
    payload = response.json()
    item = payload["items"][0]
    assert item["amount"] == -42.0
    assert item["currency"] == "USD"
    assert item["display_amount"] is None
    assert item["display_currency"] == "BRL"
    assert item["display_fx_rate"] is None
    assert item["display_rate_date"] is None
