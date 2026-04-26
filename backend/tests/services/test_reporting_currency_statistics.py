"""Module for backend tests services test_reporting_currency_statistics."""

from datetime import date
from typing import cast

from app.models.statistics import StatisticsPeriod
from app.models.transaction import (
    ExpenseCategory,
    IncomeCategory,
    Transaction,
    TransactionType,
    TransferCategory,
)
from app.services.statistics_service import StatisticsService
from sqlalchemy.orm import Session


def _create_transaction(
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
    income_category = cast("IncomeCategory | None", fields.pop("income_category", None))
    transfer_category = cast(
        "TransferCategory | None",
        fields.pop("transfer_category", None),
    )
    assert fields == {}
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


def test_reporting_currency_statistics_preserve_counts_without_fx(
    db_session: Session,
) -> None:
    """Verify reporting currency stats preserve counts without FX."""
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


def test_transfer_summary_preserves_counts_without_fx(
    db_session: Session,
) -> None:
    """Verify calculate transfer summary preserves counts when fx is missing."""
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
