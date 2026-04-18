from datetime import date

from app.models.statistics import StatisticsPeriod
from app.models.transaction import (
    ExpenseCategory,
    IncomeCategory,
    Transaction,
    TransactionType,
    TransferCategory,
)
from app.services.statistics_service import StatisticsService


def _create_transaction(
    db_session,
    *,
    description: str,
    amount: float,
    transaction_type: TransactionType,
    expense_category=None,
    income_category=None,
    transfer_category=None,
):
    transaction = Transaction(
        account_number="BE55000000000001",
        transaction_date=date(2025, 1, 15),
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


def test_calculate_statistics_for_reporting_currency_preserves_counts_when_fx_is_missing(db_session):
    _create_transaction(
        db_session,
        description="Salary",
        amount=5000.0,
        transaction_type=TransactionType.INCOME,
        income_category=IncomeCategory.SALARY,
    )
    _create_transaction(
        db_session,
        description="Groceries",
        amount=-125.0,
        transaction_type=TransactionType.EXPENSE,
        expense_category=ExpenseCategory.GROCERIES,
    )
    db_session.commit()

    result = StatisticsService.calculate_statistics_for_reporting_currency(
        db_session,
        StatisticsPeriod.MONTHLY,
        date(2025, 1, 31),
        reporting_currency="USD",
    )

    assert result["period_income"] == 0.0
    assert result["period_expenses"] == 0.0
    assert result["income_count"] == 1
    assert result["expense_count"] == 1


def test_calculate_transfer_summary_preserves_counts_when_fx_is_missing(db_session):
    _create_transaction(
        db_session,
        description="Missing FX transfer",
        amount=-80.0,
        transaction_type=TransactionType.TRANSFER,
        transfer_category=TransferCategory.INTERNAL_TRANSFER,
    )
    db_session.commit()

    items = StatisticsService.calculate_transfer_summary(
        db_session,
        date(2025, 1, 1),
        date(2025, 1, 31),
        reporting_currency="USD",
    )
    by_category = {item["subtype"]: item for item in items}

    assert by_category["Internal Transfer"]["transaction_count"] == 1
    assert by_category["Internal Transfer"]["total_outgoing"] == 0.0
    assert by_category["Internal Transfer"]["total_incoming"] == 0.0
