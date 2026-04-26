"""Module for backend tests test_transaction_listing."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast

from app.main import app
from app.models.fx import FXDailyReferenceRate
from app.models.transaction import (
    ExpenseCategory,
    Transaction,
    TransactionType,
    TransferCategory,
)
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

client: Any = TestClient(app)
HTTP_OK: int = 200
EXPECTED_CLASSIFIED_TOTAL: int = 2
EUR_AMOUNT: float = -18.19
USD_DISPLAY_AMOUNT: float = -21.83
USD_DISPLAY_RATE: float = 1.2
MISSING_RATE_AMOUNT: float = -42.0
FX_TIMESTAMP: datetime = datetime(2026, 4, 17, 8, 30, 0, tzinfo=UTC)


def _store_rate(
    db_session: Session,
    *,
    rate_date: date,
    quoted_currency: str,
    units_per_base: str,
) -> None:
    db_session.add(
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
    db_session.commit()


def _make_transaction(
    db_session: Session,
    **fields: object,
) -> Transaction:
    description = cast("str", fields.pop("description"))
    amount = cast("float", fields.pop("amount"))
    transaction_type = cast("TransactionType", fields.pop("transaction_type"))
    expense_category = cast(
        "ExpenseCategory | None",
        fields.pop("expense_category", None),
    )
    transfer_category = cast(
        "TransferCategory | None",
        fields.pop("transfer_category", None),
    )
    assert fields == {}
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


def test_get_transactions_filters_by_classification_status(
    db_session: Session,
) -> None:
    """Verify get transactions filters by classification status."""
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

    classified = client.get(
        "/transactions/", params={"classification_status": "classified"}
    )
    assert classified.status_code == HTTP_OK
    classified_payload = classified.json()
    assert classified_payload["total"] == EXPECTED_CLASSIFIED_TOTAL
    assert {item["description"] for item in classified_payload["items"]} == {
        "Categorized expense",
        "Categorized transfer",
    }

    unclassified = client.get(
        "/transactions/", params={"classification_status": "unclassified"}
    )
    assert unclassified.status_code == HTTP_OK
    unclassified_payload = unclassified.json()
    assert unclassified_payload["total"] == 1
    assert [item["description"] for item in unclassified_payload["items"]] == [
        "Needs review"
    ]


def test_get_transactions_includes_display_fields_for_selected_reporting_currency(
    db_session: Session,
) -> None:
    """Verify transactions include selected reporting-currency display fields."""
    _store_rate(
        db_session,
        rate_date=date(2026, 2, 26),
        quoted_currency="USD",
        units_per_base="1.2000",
    )
    _make_transaction(
        db_session,
        description="Imported grocery run",
        amount=EUR_AMOUNT,
        transaction_type=TransactionType.EXPENSE,
        expense_category=ExpenseCategory.GROCERIES,
    )
    db_session.commit()

    response = client.get(
        "/transactions/",
        headers={"X-Reporting-Currency": "USD"},
    )

    assert response.status_code == HTTP_OK
    payload = response.json()
    assert payload["total"] == 1
    item = payload["items"][0]
    assert item["amount"] == EUR_AMOUNT
    assert item["currency"] == "EUR"
    assert item["display_amount"] == USD_DISPLAY_AMOUNT
    assert item["display_currency"] == "USD"
    assert item["display_fx_rate"] == USD_DISPLAY_RATE
    assert item["display_rate_date"] == "2026-02-26"
    assert item["display_is_available"] is True
    assert item["display_unavailable_reason"] is None


def test_get_transactions_keeps_unavailable_display_shape_when_rate_missing(
    db_session: Session,
) -> None:
    """Verify get transactions keeps unavailable display shape when rate missing."""
    _make_transaction(
        db_session,
        description="USD card purchase",
        amount=MISSING_RATE_AMOUNT,
        transaction_type=TransactionType.EXPENSE,
        expense_category=ExpenseCategory.SHOPPING,
    ).currency = "USD"
    db_session.commit()

    response = client.get(
        "/transactions/",
        headers={"X-Reporting-Currency": "BRL"},
    )

    assert response.status_code == HTTP_OK
    payload = response.json()
    item = payload["items"][0]
    assert item["amount"] == MISSING_RATE_AMOUNT
    assert item["currency"] == "USD"
    assert item["display_amount"] is None
    assert item["display_currency"] == "BRL"
    assert item["display_fx_rate"] is None
    assert item["display_rate_date"] is None
    assert item["display_is_available"] is False
    assert item["display_unavailable_reason"] == "missing_rate"
