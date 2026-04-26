"""Module for backend tests services test_reporting_currency_analytics."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import cast

import pytest
from app.models.fx import FXDailyReferenceRate
from app.models.statistics import StatisticsPeriod
from app.models.transaction import (
    ExpenseCategory,
    ExpenseType,
    IncomeCategory,
    Transaction,
    TransactionType,
    TransferCategory,
)
from app.services.reporting_currency_analytics import ReportingCurrencyAnalyticsService
from sqlalchemy.orm import Session

FX_TIMESTAMP: datetime = datetime(2026, 4, 17, 8, 30, 0, tzinfo=UTC)
EXPECTED_CONVERTED_COUNT: int = 2
EXPECTED_TRANSACTION_COUNT: int = 2
EXPECTED_TOTAL_TRANSACTION_COUNT: int = 3
EXPECTED_PERIOD_INCOME_USD: float = 6000.0
EXPECTED_TOTAL_INCOME_USD: float = 7100.0
EXPECTED_TRANSFER_OUTGOING_USD: float = 120.0
EXPECTED_TOTAL_AMOUNT_USD: float = 170.0
EXPECTED_AVERAGE_AMOUNT_USD: float = 85.0
EXPECTED_CUMULATIVE_AMOUNT_USD: float = 175.0
EXPECTED_FEBRUARY_AMOUNT_USD: float = 110.0
EXPECTED_MARCH_AMOUNT_USD: float = 60.0


def _create_transaction(
    db_session: Session,
    **fields: object,
) -> Transaction:
    description = cast("str", fields.pop("description"))
    amount = cast("float", fields.pop("amount"))
    transaction_type = cast("TransactionType", fields.pop("transaction_type"))
    transaction_date = cast("date", fields.pop("transaction_date", date(2026, 3, 31)))
    expense_category = cast(
        "ExpenseCategory | None",
        fields.pop("expense_category", None),
    )
    income_category = cast("IncomeCategory | None", fields.pop("income_category", None))
    transfer_category = cast(
        "TransferCategory | None",
        fields.pop("transfer_category", None),
    )
    assert fields == {}
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


def test_financial_timeseries_excludes_unconvertible_rows(
    db_session: Session,
) -> None:
    """Verify financial timeseries reports unconvertible rows."""
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
        description="Unsupported token fee",
        amount=-15.0,
        transaction_type=TransactionType.EXPENSE,
        expense_category=ExpenseCategory.FINANCIAL_FEES,
    )
    unsupported.currency = "NEXO"
    db_session.commit()

    payload = ReportingCurrencyAnalyticsService(db_session).build_financial_timeseries(
        start=date(2026, 3, 1),
        end=date(2026, 3, 31),
        reporting_currency="USD",
    )

    assert payload["reporting_currency"] == "USD"
    assert payload["conversion_summary"]["converted_transaction_count"] == 1
    assert payload["conversion_summary"]["unavailable_transaction_count"] == 1
    assert payload["conversion_summary"]["unavailable_currencies"] == ["NEXO"]
    assert payload["items"][0]["period_income"] == EXPECTED_PERIOD_INCOME_USD
    assert payload["items"][0]["period_expenses"] == 0.0


def test_financial_timeseries_conversion_summary_covers_all_metrics(
    db_session: Session,
) -> None:
    """Verify timeseries conversion summary covers returned metrics."""
    _store_rate(
        db_session,
        rate_date=date(2026, 2, 28),
        quoted_currency="USD",
        units_per_base="1.1000",
    )
    _store_rate(
        db_session,
        rate_date=date(2026, 3, 31),
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
    _create_transaction(
        db_session,
        description="March salary",
        amount=5000.0,
        transaction_type=TransactionType.INCOME,
        transaction_date=date(2026, 3, 31),
        income_category=IncomeCategory.SALARY,
    )
    historical_unsupported = _create_transaction(
        db_session,
        description="Historical unsupported fee",
        amount=-15.0,
        transaction_type=TransactionType.EXPENSE,
        transaction_date=date(2026, 2, 28),
        expense_category=ExpenseCategory.FINANCIAL_FEES,
    )
    historical_unsupported.currency = "NEXO"
    db_session.commit()

    payload = ReportingCurrencyAnalyticsService(db_session).build_financial_timeseries(
        start=date(2026, 3, 1),
        end=date(2026, 3, 31),
        reporting_currency="USD",
    )

    assert (
        payload["conversion_summary"]["converted_transaction_count"]
        == EXPECTED_CONVERTED_COUNT
    )
    assert payload["conversion_summary"]["unavailable_transaction_count"] == 1
    assert payload["conversion_summary"]["unavailable_currencies"] == ["NEXO"]
    assert payload["items"][0]["period_income"] == EXPECTED_PERIOD_INCOME_USD
    assert payload["items"][0]["total_income"] == EXPECTED_TOTAL_INCOME_USD
    assert payload["items"][0]["yearly_income"] == EXPECTED_TOTAL_INCOME_USD


def test_transfer_summary_excludes_unconvertible_rows(
    db_session: Session,
) -> None:
    """Verify transfer summary reports unconvertible rows."""
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

    payload = ReportingCurrencyAnalyticsService(db_session).build_transfer_summary(
        start=date(2026, 3, 1),
        end=date(2026, 3, 31),
        reporting_currency="USD",
    )

    assert payload["reporting_currency"] == "USD"
    assert payload["conversion_summary"]["converted_transaction_count"] == 1
    assert payload["conversion_summary"]["unavailable_transaction_count"] == 1
    assert payload["conversion_summary"]["unavailable_currencies"] == ["NEXO"]
    items = {item["subtype"]: item for item in payload["items"]}
    assert (
        items["Credit Card Settlement"]["total_outgoing"]
        == EXPECTED_TRANSFER_OUTGOING_USD
    )
    assert items["Internal Transfer"]["total_outgoing"] == 0.0


def test_resolve_reporting_window_raises_stable_invalid_date_message(
    db_session: Session,
) -> None:
    """Verify resolve reporting window raises stable invalid date message."""
    with pytest.raises(ValueError, match=r"Invalid date format\. Use YYYY-MM-DD"):
        ReportingCurrencyAnalyticsService.resolve_reporting_window(
            db_session,
            start_date="2026-99-01",
        )


def test_category_breakdown_uses_converted_raw_transactions(
    db_session: Session,
) -> None:
    """Verify category breakdown uses converted raw transactions."""
    _store_rate(
        db_session,
        rate_date=date(2026, 3, 31),
        quoted_currency="USD",
        units_per_base="1.2000",
    )
    groceries = _create_transaction(
        db_session,
        description="Groceries",
        amount=-100.0,
        transaction_type=TransactionType.EXPENSE,
        expense_category=ExpenseCategory.GROCERIES,
    )
    groceries.currency = "EUR"
    db_session.commit()

    payload = ReportingCurrencyAnalyticsService(db_session).build_category_breakdown(
        period=StatisticsPeriod.MONTHLY,
        target_date=date(2026, 3, 31),
        reporting_currency="USD",
    )

    groceries_item = next(
        item for item in payload["items"] if item["category"] == "Groceries"
    )
    assert groceries_item["period_amount"] == EXPECTED_TRANSFER_OUTGOING_USD
    assert payload["reporting_currency"] == "USD"
    assert payload["conversion_summary"] == {
        "converted_transaction_count": 1,
        "unavailable_transaction_count": 0,
        "unavailable_currencies": [],
    }


def test_expense_type_breakdown_reports_unavailable_rows(
    db_session: Session,
) -> None:
    """Verify expense type breakdown reports unavailable rows."""
    _store_rate(
        db_session,
        rate_date=date(2026, 2, 28),
        quoted_currency="USD",
        units_per_base="1.1000",
    )
    _store_rate(
        db_session,
        rate_date=date(2026, 3, 31),
        quoted_currency="USD",
        units_per_base="1.2000",
    )
    _create_transaction(
        db_session,
        description="March groceries",
        amount=-100.0,
        transaction_type=TransactionType.EXPENSE,
        transaction_date=date(2026, 3, 31),
        expense_category=ExpenseCategory.GROCERIES,
    )
    _create_transaction(
        db_session,
        description="February groceries",
        amount=-50.0,
        transaction_type=TransactionType.EXPENSE,
        transaction_date=date(2026, 2, 28),
        expense_category=ExpenseCategory.GROCERIES,
    )
    unsupported = _create_transaction(
        db_session,
        description="Unsupported restaurant charge",
        amount=-25.0,
        transaction_type=TransactionType.EXPENSE,
        transaction_date=date(2026, 3, 31),
        expense_category=ExpenseCategory.EATING_OUT,
    )
    unsupported.currency = "NEXO"
    db_session.commit()

    payload = ReportingCurrencyAnalyticsService(
        db_session
    ).build_expense_type_breakdown(
        period=StatisticsPeriod.MONTHLY,
        target_date=date(2026, 3, 31),
        reporting_currency="USD",
    )

    essential = next(
        item
        for item in payload["items"]
        if item["expense_type"] == ExpenseType.FIXED_ESSENTIAL.value
    )
    discretionary = next(
        item
        for item in payload["items"]
        if item["expense_type"] == ExpenseType.GUILT_FREE_DISCRETIONARY.value
    )
    assert payload["reporting_currency"] == "USD"
    assert payload["conversion_summary"] == {
        "converted_transaction_count": EXPECTED_CONVERTED_COUNT,
        "unavailable_transaction_count": 1,
        "unavailable_currencies": ["NEXO"],
    }
    assert essential["period_amount"] == EXPECTED_TRANSFER_OUTGOING_USD
    assert essential["total_amount_cumulative"] == EXPECTED_CUMULATIVE_AMOUNT_USD
    assert discretionary["period_amount"] == 0.0
    assert discretionary["period_transaction_count"] == 1


def test_category_averages_reports_conversion_gaps(
    db_session: Session,
) -> None:
    """Verify category averages reports conversion gaps."""
    _store_rate(
        db_session,
        rate_date=date(2026, 2, 28),
        quoted_currency="USD",
        units_per_base="1.1000",
    )
    _store_rate(
        db_session,
        rate_date=date(2026, 3, 31),
        quoted_currency="USD",
        units_per_base="1.2000",
    )
    _create_transaction(
        db_session,
        description="February groceries",
        amount=-100.0,
        transaction_type=TransactionType.EXPENSE,
        transaction_date=date(2026, 2, 28),
        expense_category=ExpenseCategory.GROCERIES,
    )
    _create_transaction(
        db_session,
        description="March groceries",
        amount=-50.0,
        transaction_type=TransactionType.EXPENSE,
        transaction_date=date(2026, 3, 31),
        expense_category=ExpenseCategory.GROCERIES,
    )
    unsupported = _create_transaction(
        db_session,
        description="Unsupported groceries fee",
        amount=-25.0,
        transaction_type=TransactionType.EXPENSE,
        transaction_date=date(2026, 3, 31),
        expense_category=ExpenseCategory.GROCERIES,
    )
    unsupported.currency = "NEXO"
    db_session.commit()

    payload = ReportingCurrencyAnalyticsService(db_session).build_category_averages(
        start=date(2026, 2, 1),
        end=date(2026, 3, 31),
        reporting_currency="USD",
        transaction_type=TransactionType.EXPENSE,
    )

    groceries = next(
        item for item in payload["categories"] if item["category_name"] == "Groceries"
    )
    assert payload["reporting_currency"] == "USD"
    assert payload["months_count"] == EXPECTED_CONVERTED_COUNT
    assert payload["conversion_summary"] == {
        "converted_transaction_count": EXPECTED_CONVERTED_COUNT,
        "unavailable_transaction_count": 1,
        "unavailable_currencies": ["NEXO"],
    }
    assert groceries["total_amount"] == EXPECTED_TOTAL_AMOUNT_USD
    assert groceries["average_amount"] == EXPECTED_AVERAGE_AMOUNT_USD
    assert groceries["transaction_count"] == EXPECTED_TOTAL_TRANSACTION_COUNT
    assert groceries["average_transaction_amount"] == EXPECTED_AVERAGE_AMOUNT_USD


def test_category_timeseries_uses_converted_raw_transactions(
    db_session: Session,
) -> None:
    """Verify category timeseries uses converted raw transactions."""
    _store_rate(
        db_session,
        rate_date=date(2026, 2, 28),
        quoted_currency="USD",
        units_per_base="1.1000",
    )
    _store_rate(
        db_session,
        rate_date=date(2026, 3, 31),
        quoted_currency="USD",
        units_per_base="1.2000",
    )
    _create_transaction(
        db_session,
        description="February groceries",
        amount=-100.0,
        transaction_type=TransactionType.EXPENSE,
        transaction_date=date(2026, 2, 28),
        expense_category=ExpenseCategory.GROCERIES,
    )
    _create_transaction(
        db_session,
        description="March groceries",
        amount=-50.0,
        transaction_type=TransactionType.EXPENSE,
        transaction_date=date(2026, 3, 31),
        expense_category=ExpenseCategory.GROCERIES,
    )
    unsupported = _create_transaction(
        db_session,
        description="Unsupported groceries fee",
        amount=-25.0,
        transaction_type=TransactionType.EXPENSE,
        transaction_date=date(2026, 3, 31),
        expense_category=ExpenseCategory.GROCERIES,
    )
    unsupported.currency = "NEXO"
    db_session.commit()

    payload = ReportingCurrencyAnalyticsService(db_session).build_category_timeseries(
        start=date(2026, 3, 1),
        end=date(2026, 3, 31),
        reporting_currency="USD",
        transaction_type=TransactionType.EXPENSE,
        category_name="Groceries",
    )

    assert payload["reporting_currency"] == "USD"
    assert payload["conversion_summary"] == {
        "converted_transaction_count": EXPECTED_CONVERTED_COUNT,
        "unavailable_transaction_count": 1,
        "unavailable_currencies": ["NEXO"],
    }
    assert payload["items"] == [
        {
            "category": "Groceries",
            "period": "monthly",
            "date": "2026-03-31",
            "category_name": "Groceries",
            "transaction_type": "Expense",
            "expense_type": "Fixed Essential",
            "period_amount": EXPECTED_MARCH_AMOUNT_USD,
            "period_transaction_count": EXPECTED_TRANSACTION_COUNT,
            "period_percentage": 100.0,
            "total_amount": EXPECTED_MARCH_AMOUNT_USD,
            "transaction_count": EXPECTED_TRANSACTION_COUNT,
            "total_amount_cumulative": EXPECTED_TOTAL_AMOUNT_USD,
            "total_transaction_count": EXPECTED_TOTAL_TRANSACTION_COUNT,
            "average_transaction_amount": EXPECTED_MARCH_AMOUNT_USD,
            "yearly_amount": EXPECTED_TOTAL_AMOUNT_USD,
            "yearly_transaction_count": EXPECTED_TOTAL_TRANSACTION_COUNT,
        }
    ]


def test_build_expense_type_timeseries_uses_converted_raw_transactions(
    db_session: Session,
) -> None:
    """Verify build expense type timeseries uses converted raw transactions."""
    _store_rate(
        db_session,
        rate_date=date(2026, 2, 28),
        quoted_currency="USD",
        units_per_base="1.1000",
    )
    _store_rate(
        db_session,
        rate_date=date(2026, 3, 31),
        quoted_currency="USD",
        units_per_base="1.2000",
    )
    _create_transaction(
        db_session,
        description="Groceries",
        amount=-100.0,
        transaction_type=TransactionType.EXPENSE,
        transaction_date=date(2026, 2, 28),
        expense_category=ExpenseCategory.GROCERIES,
    )
    _create_transaction(
        db_session,
        description="Restaurant",
        amount=-50.0,
        transaction_type=TransactionType.EXPENSE,
        transaction_date=date(2026, 3, 31),
        expense_category=ExpenseCategory.EATING_OUT,
    )
    unsupported = _create_transaction(
        db_session,
        description="Unsupported shopping",
        amount=-25.0,
        transaction_type=TransactionType.EXPENSE,
        transaction_date=date(2026, 3, 31),
        expense_category=ExpenseCategory.SHOPPING,
    )
    unsupported.currency = "NEXO"
    db_session.commit()

    payload = ReportingCurrencyAnalyticsService(
        db_session
    ).build_expense_type_timeseries(
        start=date(2026, 2, 1),
        end=date(2026, 3, 31),
        reporting_currency="USD",
    )

    items = {(item["date"], item["expense_type"]): item for item in payload["items"]}
    assert payload["reporting_currency"] == "USD"
    assert payload["conversion_summary"] == {
        "converted_transaction_count": EXPECTED_CONVERTED_COUNT,
        "unavailable_transaction_count": 1,
        "unavailable_currencies": ["NEXO"],
    }
    assert (
        items[("2026-02-28", ExpenseType.FIXED_ESSENTIAL.value)]["period_amount"]
        == EXPECTED_FEBRUARY_AMOUNT_USD
    )
    assert (
        items[("2026-03-31", ExpenseType.GUILT_FREE_DISCRETIONARY.value)][
            "period_amount"
        ]
        == EXPECTED_MARCH_AMOUNT_USD
    )
    assert (
        items[("2026-03-31", ExpenseType.GUILT_FREE_DISCRETIONARY.value)][
            "period_transaction_count"
        ]
        == EXPECTED_TRANSACTION_COUNT
    )
