from datetime import date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app
from app.models.fx import FXDailyReferenceRate
from app.models.transaction import (
    ExpenseCategory,
    IncomeCategory,
    Transaction,
    TransactionType,
    TransferCategory,
)


client = TestClient(app)


def _create_transaction(
    db_session,
    *,
    description: str,
    amount: float,
    transaction_type: TransactionType,
    transaction_date: date = date(2026, 3, 31),
    expense_category=None,
    income_category=None,
    transfer_category=None,
):
    transaction = Transaction(
        account_number="BE55000000000001",
        transaction_date=transaction_date,
        amount=amount,
        currency="EUR",
        description=description,
        counterparty_name="Counterparty",
        counterparty_account="BE99000000000002",
        transaction_type=transaction_type,
        expense_category=expense_category,
        income_category=income_category,
        transfer_category=transfer_category,
        source_bank="ing",
    )
    db_session.add(transaction)
    db_session.flush()
    return transaction


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


def test_statistics_timeseries_endpoint_returns_wrapper_payload(db_session):
    _store_rate(
        db_session,
        rate_date=date(2026, 3, 31),
        quoted_currency="USD",
        units_per_base="1.2000",
    )
    _create_transaction(
        db_session,
        description="Salary",
        amount=5000.0,
        transaction_type=TransactionType.INCOME,
        income_category=IncomeCategory.SALARY,
    )
    db_session.commit()

    response = client.get("/statistics/timeseries", headers={"X-Reporting-Currency": "USD"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["reporting_currency"] == "USD"
    assert "conversion_summary" in payload
    assert "items" in payload


def test_statistics_timeseries_partial_month_same_month_range_returns_empty_wrapper(db_session):
    _store_rate(
        db_session,
        rate_date=date(2026, 3, 10),
        quoted_currency="USD",
        units_per_base="1.2000",
    )
    _create_transaction(
        db_session,
        description="Mid-month salary",
        amount=5000.0,
        transaction_type=TransactionType.INCOME,
        transaction_date=date(2026, 3, 10),
        income_category=IncomeCategory.SALARY,
    )
    db_session.commit()

    response = client.get(
        "/statistics/timeseries",
        params={"start_date": "2026-03-01", "end_date": "2026-03-15"},
        headers={"X-Reporting-Currency": "USD"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "reporting_currency": "USD",
        "conversion_summary": {
            "converted_transaction_count": 0,
            "unavailable_transaction_count": 0,
            "unavailable_currencies": [],
        },
        "items": [],
    }


def test_statistics_timeseries_partial_month_cross_month_range_only_counts_completed_month_buckets(db_session):
    _store_rate(
        db_session,
        rate_date=date(2026, 2, 28),
        quoted_currency="USD",
        units_per_base="1.1000",
    )
    _store_rate(
        db_session,
        rate_date=date(2026, 3, 10),
        quoted_currency="USD",
        units_per_base="1.2000",
    )
    _create_transaction(
        db_session,
        description="February salary",
        amount=1000.0,
        transaction_type=TransactionType.INCOME,
        transaction_date=date(2026, 2, 28),
        income_category=IncomeCategory.SALARY,
    )
    march_transaction = _create_transaction(
        db_session,
        description="March unsupported fee",
        amount=-15.0,
        transaction_type=TransactionType.EXPENSE,
        transaction_date=date(2026, 3, 10),
        expense_category=ExpenseCategory.FINANCIAL_FEES,
    )
    march_transaction.currency = "NEXO"
    db_session.commit()

    response = client.get(
        "/statistics/timeseries",
        params={"start_date": "2026-02-15", "end_date": "2026-03-15"},
        headers={"X-Reporting-Currency": "USD"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["conversion_summary"] == {
        "converted_transaction_count": 1,
        "unavailable_transaction_count": 0,
        "unavailable_currencies": [],
    }
    assert len(payload["items"]) == 1
    assert payload["items"][0]["date"] == "2026-02-28"
    assert payload["items"][0]["period_income"] == 1100.0
    assert payload["items"][0]["total_income"] == 1100.0
    assert payload["items"][0]["yearly_income"] == 1100.0


def test_statistics_overview_endpoint_includes_conversion_summary_on_each_item(db_session):
    _store_rate(
        db_session,
        rate_date=date(2026, 3, 31),
        quoted_currency="USD",
        units_per_base="1.2000",
    )
    _create_transaction(
        db_session,
        description="Salary",
        amount=5000.0,
        transaction_type=TransactionType.INCOME,
        income_category=IncomeCategory.SALARY,
    )
    unsupported = _create_transaction(
        db_session,
        description="Unsupported fee",
        amount=-15.0,
        transaction_type=TransactionType.EXPENSE,
        expense_category=ExpenseCategory.FINANCIAL_FEES,
    )
    unsupported.currency = "NEXO"
    db_session.commit()

    response = client.get("/statistics/overview", headers={"X-Reporting-Currency": "USD"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["current_month"]["reporting_currency"] == "USD"
    assert payload["current_month"]["conversion_summary"]["converted_transaction_count"] == 1
    assert payload["current_month"]["conversion_summary"]["unavailable_transaction_count"] == 1
    assert payload["all_time"]["conversion_summary"]["unavailable_currencies"] == ["NEXO"]


def test_statistics_transfer_summary_endpoint_returns_conversion_summary(db_session):
    _store_rate(
        db_session,
        rate_date=date(2026, 3, 31),
        quoted_currency="USD",
        units_per_base="1.2000",
    )
    _create_transaction(
        db_session,
        description="Credit card settlement",
        amount=-100.0,
        transaction_type=TransactionType.TRANSFER,
        transfer_category=TransferCategory.CREDIT_CARD_SETTLEMENT,
    )
    unsupported = _create_transaction(
        db_session,
        description="Unsupported transfer",
        amount=-25.0,
        transaction_type=TransactionType.TRANSFER,
        transfer_category=TransferCategory.INTERNAL_TRANSFER,
    )
    unsupported.currency = "NEXO"
    db_session.commit()

    response = client.get(
        "/statistics/transfers/summary",
        params={"start_date": "2026-03-01", "end_date": "2026-03-31"},
        headers={"X-Reporting-Currency": "USD"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["reporting_currency"] == "USD"
    assert payload["conversion_summary"]["converted_transaction_count"] == 1
    assert payload["conversion_summary"]["unavailable_transaction_count"] == 1
    assert payload["conversion_summary"]["unavailable_currencies"] == ["NEXO"]
