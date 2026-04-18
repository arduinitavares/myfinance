from datetime import date, datetime
from decimal import Decimal

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


def test_build_financial_timeseries_conversion_summary_covers_all_transactions_feeding_returned_metrics(db_session):
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

    assert payload["conversion_summary"]["converted_transaction_count"] == 2
    assert payload["conversion_summary"]["unavailable_transaction_count"] == 1
    assert payload["conversion_summary"]["unavailable_currencies"] == ["NEXO"]
    assert payload["items"][0]["period_income"] == 6000.0
    assert payload["items"][0]["total_income"] == 7100.0
    assert payload["items"][0]["yearly_income"] == 7100.0


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


def test_resolve_reporting_window_raises_stable_invalid_date_message(db_session):
    try:
        ReportingCurrencyAnalyticsService.resolve_reporting_window(
            db_session,
            start_date="2026-99-01",
        )
        assert False, "expected resolve_reporting_window to raise ValueError"
    except ValueError as exc:
        assert str(exc) == "Invalid date format. Use YYYY-MM-DD"


def test_category_breakdown_uses_converted_raw_transactions_instead_of_persisted_eur_rows(db_session):
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

    groceries_item = next(item for item in payload["items"] if item["category"] == "Groceries")
    assert groceries_item["period_amount"] == 120.0
    assert payload["reporting_currency"] == "USD"
    assert payload["conversion_summary"] == {
        "converted_transaction_count": 1,
        "unavailable_transaction_count": 0,
        "unavailable_currencies": [],
    }


def test_build_expense_type_breakdown_uses_converted_raw_transactions_and_reports_unavailable_rows(db_session):
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

    payload = ReportingCurrencyAnalyticsService(db_session).build_expense_type_breakdown(
        period=StatisticsPeriod.MONTHLY,
        target_date=date(2026, 3, 31),
        reporting_currency="USD",
    )

    essential = next(item for item in payload["items"] if item["expense_type"] == ExpenseType.FIXED_ESSENTIAL.value)
    discretionary = next(
        item for item in payload["items"] if item["expense_type"] == ExpenseType.GUILT_FREE_DISCRETIONARY.value
    )
    assert payload["reporting_currency"] == "USD"
    assert payload["conversion_summary"] == {
        "converted_transaction_count": 2,
        "unavailable_transaction_count": 1,
        "unavailable_currencies": ["NEXO"],
    }
    assert essential["period_amount"] == 120.0
    assert essential["total_amount_cumulative"] == 175.0
    assert discretionary["period_amount"] == 0.0
    assert discretionary["period_transaction_count"] == 1


def test_build_category_averages_uses_converted_raw_transactions_and_reports_conversion_gaps(db_session):
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

    groceries = next(item for item in payload["categories"] if item["category_name"] == "Groceries")
    assert payload["reporting_currency"] == "USD"
    assert payload["months_count"] == 2
    assert payload["conversion_summary"] == {
        "converted_transaction_count": 2,
        "unavailable_transaction_count": 1,
        "unavailable_currencies": ["NEXO"],
    }
    assert groceries["total_amount"] == 170.0
    assert groceries["average_amount"] == 85.0
    assert groceries["transaction_count"] == 3
    assert groceries["average_transaction_amount"] == 85.0


def test_build_category_timeseries_uses_converted_raw_transactions_for_period_and_cumulative_metrics(db_session):
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
        "converted_transaction_count": 2,
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
            "period_amount": 60.0,
            "period_transaction_count": 2,
            "period_percentage": 100.0,
            "total_amount": 60.0,
            "transaction_count": 2,
            "total_amount_cumulative": 170.0,
            "total_transaction_count": 3,
            "average_transaction_amount": 60.0,
            "yearly_amount": 170.0,
            "yearly_transaction_count": 3,
        }
    ]


def test_build_expense_type_timeseries_uses_converted_raw_transactions(db_session):
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

    payload = ReportingCurrencyAnalyticsService(db_session).build_expense_type_timeseries(
        start=date(2026, 2, 1),
        end=date(2026, 3, 31),
        reporting_currency="USD",
    )

    items = {
        (item["date"], item["expense_type"]): item
        for item in payload["items"]
    }
    assert payload["reporting_currency"] == "USD"
    assert payload["conversion_summary"] == {
        "converted_transaction_count": 2,
        "unavailable_transaction_count": 1,
        "unavailable_currencies": ["NEXO"],
    }
    assert items[("2026-02-28", ExpenseType.FIXED_ESSENTIAL.value)]["period_amount"] == 110.0
    assert items[("2026-03-31", ExpenseType.GUILT_FREE_DISCRETIONARY.value)]["period_amount"] == 60.0
    assert items[("2026-03-31", ExpenseType.GUILT_FREE_DISCRETIONARY.value)]["period_transaction_count"] == 2
