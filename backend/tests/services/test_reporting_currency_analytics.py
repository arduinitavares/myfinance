from datetime import date, datetime
from decimal import Decimal

from app.models.fx import FXDailyReferenceRate
from app.models.transaction import (
    ExpenseCategory,
    IncomeCategory,
    Transaction,
    TransactionType,
    TransferCategory,
)
from app.services.reporting_currency_analytics import ReportingCurrencyAnalyticsService


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


def test_build_financial_timeseries_excludes_unconvertible_rows_from_totals_but_reports_them(db_session):
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
    assert payload["items"][0]["period_income"] == 6000.0
    assert payload["items"][0]["period_expenses"] == 0.0


def test_build_transfer_summary_excludes_unconvertible_rows_from_totals_but_reports_them(db_session):
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
    assert items["Credit Card Settlement"]["total_outgoing"] == 120.0
    assert items["Internal Transfer"]["total_outgoing"] == 0.0
