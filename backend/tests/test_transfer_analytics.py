"""Module for backend tests test_transfer_analytics."""

import csv
import io
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Never, cast

import numpy as np
import pytest
from app.database import SessionLocal
from app.main import app
from app.models.fx import FXDailyReferenceRate
from app.models.statistics import (
    CategoryStatistics,
    FinancialStatistics,
    StatisticsPeriod,
)
from app.models.transaction import (
    ExpenseCategory,
    IncomeCategory,
    Transaction,
    TransactionType,
    TransferCategory,
)
from app.routers.suggestions import category_suggestion_service
from app.schemas.transaction import TransactionRestore
from app.services import classification_commit_service as classification_commit_module
from app.services.classification_commit_service import (
    CategoryChangeRequest,
    commit_category_change,
    normalized_category_for,
)
from app.services.classification_session_service import ClassificationSessionService
from app.services.statistics_service import StatisticsService
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

HTTP_OK: int = 200
HTTP_BAD_REQUEST: int = 400
TRANSFER_AMOUNT: float = -240.0
TRANSFER_DISPLAY_AMOUNT_USD: float = -300.0
DISPLAY_FX_RATE: float = 1.25
EUR_INCOME: float = 5000.0
EUR_EXPENSES: float = 189.0
EUR_NET_SAVINGS: float = 4811.0
EUR_AVERAGE_EXPENSE: float = 94.5
USD_INCOME: float = 6250.0
USD_EXPENSES: float = 236.25
USD_NET_SAVINGS: float = 6013.75
USD_AVERAGE_EXPENSE: float = 118.12
RAW_MIXED_EXPENSES: float = 180.0
RAW_MIXED_NET_SAVINGS: float = 4820.0
RAW_MIXED_AVERAGE_EXPENSE: float = 90.0
EXPECTED_TRANSFER_COUNT: int = 2
SINGLE_TRANSACTION_COUNT: int = 1
ZERO_AMOUNT: float = 0.0
CARD_SETTLEMENT_TOTAL_EUR: float = 240.0
CARD_SETTLEMENT_TOTAL_USD: float = 300.0
INTERNAL_TRANSFER_OUTGOING_EUR: float = 164.0
LOAN_REPAYMENT_INCOMING_EUR: float = 55.0
INTERNAL_TRANSFER_OUTGOING_USD: float = 205.0
LOAN_REPAYMENT_INCOMING_USD: float = 68.75
FX_TIMESTAMP: datetime = datetime(2026, 4, 17, 8, 30, 0, tzinfo=UTC)


def _reset_database(client: TestClient) -> None:
    response = client.post("/debug/reset-database")
    assert response.status_code == HTTP_OK


def _restore_transaction(client: TestClient, *, description: str) -> dict[str, Any]:
    payload = {
        "account_number": "BE55000000000001",
        "transaction_date": "2025-01-15",
        "amount": TRANSFER_AMOUNT,
        "currency": "EUR",
        "description": description,
        "counterparty_name": "Counterparty",
        "counterparty_account": "BE99000000000002",
        "transaction_type": TransactionType.TRANSFER.value,
        "transfer_category": TransferCategory.INTERNAL_TRANSFER.value,
        "source_bank": "ing",
    }

    response = client.post("/transactions/restore", json=payload)
    assert response.status_code == HTTP_OK
    return response.json()


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


def _clear_transactions_and_statistics() -> None:
    db_session = SessionLocal()
    try:
        db_session.query(CategoryStatistics).delete()
        db_session.query(FinancialStatistics).delete()
        db_session.query(Transaction).delete()
        db_session.commit()
    finally:
        db_session.close()


def test_manual_transfer_update_clears_other_category_columns() -> None:
    """Verify manual transfer update clears other category columns."""
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

    assert response.status_code == HTTP_OK
    payload = response.json()
    assert payload["transaction_type"] == TransactionType.TRANSFER.value
    assert payload["transfer_category"] == TransferCategory.CREDIT_CARD_SETTLEMENT.value
    assert payload["expense_category"] is None
    assert payload["income_category"] is None


def test_manual_transfer_update_returns_display_fields_for_reporting_currency() -> None:
    """Verify manual transfer update returns display fields for reporting currency."""
    client = TestClient(app)
    _reset_database(client)
    db_session = SessionLocal()
    try:
        _store_rate(
            db_session,
            rate_date=date(2025, 1, 15),
            quoted_currency="USD",
            units_per_base="1.2500",
        )
    finally:
        db_session.close()

    transaction = _restore_transaction(client, description="Belfius card settlement")

    response = client.patch(
        f"/transactions/{transaction['id']}/category",
        params={
            "transaction_type": TransactionType.TRANSFER.value,
            "category": TransferCategory.CREDIT_CARD_SETTLEMENT.value,
        },
        headers={"X-Reporting-Currency": "USD"},
    )

    assert response.status_code == HTTP_OK
    payload = response.json()
    assert payload["amount"] == TRANSFER_AMOUNT
    assert payload["currency"] == "EUR"
    assert payload["display_amount"] == TRANSFER_DISPLAY_AMOUNT_USD
    assert payload["display_currency"] == "USD"
    assert payload["display_fx_rate"] == DISPLAY_FX_RATE
    assert payload["display_rate_date"] == "2025-01-15"


def test_restore_returns_display_fields_for_reporting_currency() -> None:
    """Verify restore returns display fields for reporting currency."""
    client = TestClient(app)
    _reset_database(client)
    db_session = SessionLocal()
    try:
        _store_rate(
            db_session,
            rate_date=date(2025, 1, 15),
            quoted_currency="USD",
            units_per_base="1.2500",
        )
    finally:
        db_session.close()

    payload = {
        "account_number": "BE55000000000001",
        "transaction_date": "2025-01-15",
        "amount": -240.00,
        "currency": "EUR",
        "description": "Transfer to card",
        "counterparty_name": "Counterparty",
        "counterparty_account": "BE99000000000002",
        "transaction_type": TransactionType.TRANSFER.value,
        "transfer_category": TransferCategory.INTERNAL_TRANSFER.value,
        "source_bank": "ing",
    }

    response = client.post(
        "/transactions/restore",
        json=payload,
        headers={"X-Reporting-Currency": "USD"},
    )

    assert response.status_code == HTTP_OK
    body = response.json()
    assert body["amount"] == TRANSFER_AMOUNT
    assert body["currency"] == "EUR"
    assert body["display_amount"] == TRANSFER_DISPLAY_AMOUNT_USD
    assert body["display_currency"] == "USD"
    assert body["display_fx_rate"] == DISPLAY_FX_RATE
    assert body["display_rate_date"] == "2025-01-15"


def test_statistics_overview_excludes_transfer_transactions() -> None:
    """Verify statistics overview excludes transfer transactions."""
    client = TestClient(app)
    _reset_database(client)
    db_session = SessionLocal()

    try:
        _store_rate(
            db_session,
            rate_date=date(2025, 1, 15),
            quoted_currency="USD",
            units_per_base="1.2500",
        )
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
        usd_expense = _create_transaction(
            db_session,
            description="USD utilities",
            amount=-80.0,
            transaction_type=TransactionType.EXPENSE,
            expense_category=ExpenseCategory.UTILITIES,
        )
        usd_expense.currency = "USD"
        _create_transaction(
            db_session,
            description="Card settlement",
            amount=-240.0,
            transaction_type=TransactionType.TRANSFER,
            transfer_category=TransferCategory.CREDIT_CARD_SETTLEMENT,
        )
        db_session.commit()

        StatisticsService.initialize_statistics(db_session)
        StatisticsService.initialize_category_statistics(db_session)

        eur_response = client.get("/statistics/overview")
        assert eur_response.status_code == HTTP_OK

        eur_payload = eur_response.json()
        eur_current_month = eur_payload["current_month"]
        eur_all_time = eur_payload["all_time"]

        assert eur_current_month["reporting_currency"] == "EUR"
        assert eur_current_month["period_income"] == EUR_INCOME
        assert eur_current_month["period_expenses"] == EUR_EXPENSES
        assert eur_current_month["income_count"] == SINGLE_TRANSACTION_COUNT
        assert eur_current_month["expense_count"] == EXPECTED_TRANSFER_COUNT
        assert eur_current_month["total_income"] == EUR_INCOME
        assert eur_current_month["total_expenses"] == EUR_EXPENSES
        assert eur_current_month["total_net_savings"] == EUR_NET_SAVINGS
        assert eur_current_month["average_expense"] == EUR_AVERAGE_EXPENSE
        assert eur_all_time["reporting_currency"] == "EUR"
        assert eur_all_time["total_income"] == EUR_INCOME
        assert eur_all_time["total_expenses"] == EUR_EXPENSES

        usd_response = client.get(
            "/statistics/overview",
            headers={"X-Reporting-Currency": "USD"},
        )
        assert usd_response.status_code == HTTP_OK

        usd_payload = usd_response.json()
        usd_current_month = usd_payload["current_month"]
        usd_all_time = usd_payload["all_time"]

        assert usd_current_month["reporting_currency"] == "USD"
        assert usd_current_month["period_income"] == USD_INCOME
        assert usd_current_month["period_expenses"] == USD_EXPENSES
        assert usd_current_month["total_income"] == USD_INCOME
        assert usd_current_month["total_expenses"] == USD_EXPENSES
        assert usd_current_month["total_net_savings"] == USD_NET_SAVINGS
        assert usd_current_month["average_income"] == USD_INCOME
        assert usd_current_month["average_expense"] == USD_AVERAGE_EXPENSE
        assert usd_all_time["reporting_currency"] == "USD"
        assert usd_all_time["total_income"] == USD_INCOME
        assert usd_all_time["total_expenses"] == USD_EXPENSES
    finally:
        db_session.close()


def test_statistics_overview_keeps_prior_year_month_for_transfers() -> None:
    """Verify statistics overview keeps prior year month for transfers."""
    client = TestClient(app)
    _reset_database(client)
    db_session = SessionLocal()

    try:
        _create_transaction(
            db_session,
            description="Salary",
            amount=5000.0,
            transaction_type=TransactionType.INCOME,
            income_category=IncomeCategory.SALARY,
        )
        prior_year_transfer = _create_transaction(
            db_session,
            description="Previous year transfer",
            amount=-240.0,
            transaction_type=TransactionType.TRANSFER,
            transfer_category=TransferCategory.INTERNAL_TRANSFER,
        )
        prior_year_transfer.transaction_date = date(2024, 12, 20)
        db_session.commit()

        StatisticsService.initialize_statistics(db_session)
        StatisticsService.initialize_category_statistics(db_session)

        response = client.get("/statistics/overview")
        assert response.status_code == HTTP_OK

        payload = response.json()
        previous_year_last_month = payload["previous_year_last_month"]

        assert previous_year_last_month is not None
        assert previous_year_last_month["reporting_currency"] == "EUR"
        assert previous_year_last_month["date"] == "2024-12-31"
        assert previous_year_last_month["period_income"] == ZERO_AMOUNT
        assert previous_year_last_month["period_expenses"] == ZERO_AMOUNT
        assert previous_year_last_month["total_net_savings"] == ZERO_AMOUNT
    finally:
        db_session.close()


def test_calculate_statistics_keeps_raw_mixed_currency_totals() -> None:
    """Verify calculate statistics keeps raw mixed currency totals."""
    client = TestClient(app)
    _reset_database(client)
    db_session = SessionLocal()

    try:
        _store_rate(
            db_session,
            rate_date=date(2025, 1, 15),
            quoted_currency="USD",
            units_per_base="1.2500",
        )

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
            amount=-100.0,
            transaction_type=TransactionType.EXPENSE,
            expense_category=ExpenseCategory.GROCERIES,
        )
        usd_expense = _create_transaction(
            db_session,
            description="USD subscription",
            amount=-80.0,
            transaction_type=TransactionType.EXPENSE,
            expense_category=ExpenseCategory.UTILITIES,
        )
        usd_expense.currency = "USD"
        db_session.commit()

        stats = StatisticsService.calculate_statistics(
            db_session,
            StatisticsPeriod.MONTHLY,
            date(2025, 1, 31),
        )

        assert stats["period_income"] == EUR_INCOME
        assert stats["period_expenses"] == RAW_MIXED_EXPENSES
        assert stats["total_expenses"] == RAW_MIXED_EXPENSES
        assert stats["period_net_savings"] == RAW_MIXED_NET_SAVINGS
        assert stats["average_expense"] == RAW_MIXED_AVERAGE_EXPENSE
    finally:
        db_session.close()


def test_category_statistics_ignore_transfer_rows() -> None:
    """Verify category statistics ignore transfer rows."""
    client = TestClient(app)
    _reset_database(client)
    db_session = SessionLocal()

    try:
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
        _create_transaction(
            db_session,
            description="Transfer to savings",
            amount=-240.0,
            transaction_type=TransactionType.TRANSFER,
            transfer_category=TransferCategory.INTERNAL_TRANSFER,
        )
        db_session.commit()

        StatisticsService.initialize_statistics(db_session)
        StatisticsService.initialize_category_statistics(db_session)

        response = client.get(
            "/statistics/by-category",
            params={"period": "monthly", "date": "2025-01-15"},
        )
        assert response.status_code == HTTP_OK

        payload = response.json()
        categories = {item["category"] for item in payload["items"]}

        assert "Internal Transfer" not in categories
        assert categories == {"Salary", "Groceries"}
    finally:
        db_session.close()


def test_transfer_summary_groups_by_category_and_sign() -> None:
    """Verify transfer summary groups by category and sign."""
    client = TestClient(app)
    _reset_database(client)
    db_session = SessionLocal()

    try:
        _store_rate(
            db_session,
            rate_date=date(2025, 1, 15),
            quoted_currency="USD",
            units_per_base="1.2500",
        )
        _create_transaction(
            db_session,
            description="Card settlement",
            amount=-240.0,
            transaction_type=TransactionType.TRANSFER,
            transfer_category=TransferCategory.CREDIT_CARD_SETTLEMENT,
        )
        _create_transaction(
            db_session,
            description="Card refund",
            amount=240.0,
            transaction_type=TransactionType.TRANSFER,
            transfer_category=TransferCategory.CREDIT_CARD_SETTLEMENT,
        )
        _create_transaction(
            db_session,
            description="Savings transfer",
            amount=-100.0,
            transaction_type=TransactionType.TRANSFER,
            transfer_category=None,
        )
        _create_transaction(
            db_session,
            description="Loan repayment received",
            amount=55.0,
            transaction_type=TransactionType.TRANSFER,
            transfer_category=TransferCategory.LOAN_REPAYMENT_RECEIVED,
        )
        _create_transaction(
            db_session,
            description=(
                "USD transfer should now be converted through the reporting "
                "currency service"
            ),
            amount=-80.0,
            transaction_type=TransactionType.TRANSFER,
            transfer_category=TransferCategory.INTERNAL_TRANSFER,
        ).currency = "USD"
        db_session.commit()

        response = client.get(
            "/statistics/transfers/summary",
            params={"start_date": "2025-01-01", "end_date": "2025-01-31"},
        )
        assert response.status_code == HTTP_OK

        payload = response.json()
        assert payload["start_date"] == "2025-01-01"
        assert payload["end_date"] == "2025-01-31"
        assert payload["reporting_currency"] == "EUR"

        by_category = {item["subtype"]: item for item in payload["items"]}

        assert (
            by_category["Credit Card Settlement"]["transaction_count"]
            == EXPECTED_TRANSFER_COUNT
        )
        assert (
            by_category["Credit Card Settlement"]["total_outgoing"]
            == CARD_SETTLEMENT_TOTAL_EUR
        )
        assert (
            by_category["Credit Card Settlement"]["total_incoming"]
            == CARD_SETTLEMENT_TOTAL_EUR
        )
        assert (
            by_category["Internal Transfer"]["transaction_count"]
            == EXPECTED_TRANSFER_COUNT
        )
        assert (
            by_category["Internal Transfer"]["total_outgoing"]
            == INTERNAL_TRANSFER_OUTGOING_EUR
        )
        assert by_category["Internal Transfer"]["total_incoming"] == ZERO_AMOUNT
        assert (
            by_category["Loan Repayment Received"]["transaction_count"]
            == SINGLE_TRANSACTION_COUNT
        )
        assert (
            by_category["Loan Repayment Received"]["total_outgoing"] == ZERO_AMOUNT
        )
        assert (
            by_category["Loan Repayment Received"]["total_incoming"]
            == LOAN_REPAYMENT_INCOMING_EUR
        )

        usd_response = client.get(
            "/statistics/transfers/summary",
            params={"start_date": "2025-01-01", "end_date": "2025-01-31"},
            headers={"X-Reporting-Currency": "USD"},
        )
        assert usd_response.status_code == HTTP_OK

        usd_payload = usd_response.json()
        assert usd_payload["reporting_currency"] == "USD"

        usd_by_category = {item["subtype"]: item for item in usd_payload["items"]}
        assert (
            usd_by_category["Credit Card Settlement"]["total_outgoing"]
            == CARD_SETTLEMENT_TOTAL_USD
        )
        assert (
            usd_by_category["Credit Card Settlement"]["total_incoming"]
            == CARD_SETTLEMENT_TOTAL_USD
        )
        assert (
            usd_by_category["Internal Transfer"]["transaction_count"]
            == EXPECTED_TRANSFER_COUNT
        )
        assert (
            usd_by_category["Internal Transfer"]["total_outgoing"]
            == INTERNAL_TRANSFER_OUTGOING_USD
        )
        assert usd_by_category["Internal Transfer"]["total_incoming"] == ZERO_AMOUNT
        assert (
            usd_by_category["Loan Repayment Received"]["total_incoming"]
            == LOAN_REPAYMENT_INCOMING_USD
        )
    finally:
        db_session.close()


def test_transfer_summary_empty_state_honors_requested_dates() -> None:
    """Verify transfer summary empty state honors requested dates."""
    client = TestClient(app)
    _clear_transactions_and_statistics()

    response = client.get(
        "/statistics/transfers/summary",
        params={"start_date": "2025-01-01", "end_date": "2025-01-31"},
    )

    assert response.status_code == HTTP_OK
    assert response.json() == {
        "start_date": "2025-01-01",
        "end_date": "2025-01-31",
        "reporting_currency": "EUR",
        "conversion_summary": {
            "converted_transaction_count": 0,
            "unavailable_transaction_count": 0,
            "unavailable_currencies": [],
        },
        "items": [],
    }


def test_internal_transfer_exists_only_in_transfer_category_enum() -> None:
    """Verify internal transfer exists only in transfer category enum."""
    assert "INTERNAL_TRANSFER" not in ExpenseCategory.__members__
    assert "INTERNAL_TRANSFER" not in IncomeCategory.__members__
    assert TransferCategory.INTERNAL_TRANSFER.value == "Internal Transfer"


def test_transfer_summary_rejects_invalid_dates_when_no_transactions_exist() -> None:
    """Verify transfer summary rejects invalid dates when no transactions exist."""
    client = TestClient(app)
    _clear_transactions_and_statistics()

    response = client.get(
        "/statistics/transfers/summary",
        params={"start_date": "not-a-date"},
    )

    assert response.status_code == HTTP_BAD_REQUEST


def test_normalized_category_for_validates_transfer_categories() -> None:
    """Verify normalized category for validates transfer categories."""
    assert (
        normalized_category_for(
            transaction_type=TransactionType.TRANSFER,
            category=TransferCategory.CREDIT_CARD_SETTLEMENT.value,
        )
        == TransferCategory.CREDIT_CARD_SETTLEMENT.value
    )

    with pytest.raises(ValueError, match="not a valid TransferCategory"):
        normalized_category_for(
            transaction_type=TransactionType.TRANSFER,
            category=ExpenseCategory.UTILITIES.value,
        )


def test_commit_transfer_clears_other_category_fields(
    db_session: Session,
) -> None:
    """Verify commit transfer clears other category fields."""
    transaction = Transaction(
        account_number="BE55000000000001",
        transaction_date=date(2025, 1, 15),
        amount=-240.0,
        currency="EUR",
        description="Card settlement",
        counterparty_name="Counterparty",
        counterparty_account="BE99000000000002",
        transaction_type=TransactionType.EXPENSE,
        expense_category=ExpenseCategory.UTILITIES,
        income_category=IncomeCategory.SALARY,
        source_bank="ing",
    )
    db_session.add(transaction)
    db_session.flush()

    updated = commit_category_change(
        db=db_session,
        transaction=transaction,
        change=CategoryChangeRequest(
            transaction_type=TransactionType.TRANSFER,
            category=TransferCategory.CREDIT_CARD_SETTLEMENT.value,
            classification_source="manual",
            recurrence_pattern_id=None,
        ),
        commit=False,
    )

    assert updated.transaction_type == TransactionType.TRANSFER
    assert updated.transfer_category == TransferCategory.CREDIT_CARD_SETTLEMENT
    assert updated.expense_category is None
    assert updated.income_category is None


def test_commit_reclassifying_indexed_expense_to_transfer_removes_stale_embeddings(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify transfer reclassification removes stale embeddings."""
    transaction = Transaction(
        account_number="BE55000000000001",
        transaction_date=date(2025, 1, 15),
        amount=-240.0,
        currency="EUR",
        description="Card settlement",
        counterparty_name="Counterparty",
        counterparty_account="BE99000000000002",
        transaction_type=TransactionType.EXPENSE,
        expense_category=ExpenseCategory.UTILITIES,
        source_bank="ing",
    )
    db_session.add(transaction)
    db_session.commit()
    db_session.refresh(transaction)

    delete_calls: list[tuple[str, list[int]]] = []

    def noop_update_statistics(*_args: object, **_kwargs: object) -> None:
        return None

    def record_delete(
        collection_name: str,
        points_selector: list[int] | tuple[int, ...],
        **_kwargs: object,
    ) -> None:
        delete_calls.append((collection_name, list(points_selector)))

    def fail_readd_embedding(**_kwargs: object) -> Never:
        raise AssertionError

    def fail_encode_for_reclassification(_text: object) -> Never:
        raise AssertionError

    monkeypatch.setattr(
        classification_commit_module.StatisticsService,
        "update_statistics",
        noop_update_statistics,
    )
    monkeypatch.setattr(
        category_suggestion_service.client,
        "delete",
        record_delete,
    )
    monkeypatch.setattr(
        category_suggestion_service.client,
        "upsert",
        fail_readd_embedding,
    )
    monkeypatch.setattr(
        category_suggestion_service.model,
        "encode",
        fail_encode_for_reclassification,
    )

    updated = commit_category_change(
        db=db_session,
        transaction=transaction,
        change=CategoryChangeRequest(
            transaction_type=TransactionType.TRANSFER,
            category=TransferCategory.CREDIT_CARD_SETTLEMENT.value,
            classification_source="manual",
            recurrence_pattern_id=None,
        ),
        commit=True,
    )

    assert updated.transaction_type == TransactionType.TRANSFER
    assert updated.transfer_category == TransferCategory.CREDIT_CARD_SETTLEMENT
    assert updated.expense_category is None
    assert updated.income_category is None
    assert delete_calls == [
        ("expense_embeddings", [transaction.id]),
        ("income_embeddings", [transaction.id]),
    ]


def test_allowed_options_for_transfer_include_full_transfer_category_family() -> None:
    """Verify allowed options for transfer include full transfer category family."""
    expected = [category.value for category in TransferCategory]

    assert ClassificationSessionService._allowed_options_by_type(
        TransactionType.TRANSFER
    ) == {TransactionType.TRANSFER.value: expected}
    assert (
        ClassificationSessionService._allowed_options_by_type(TransactionType.EXPENSE)[
            TransactionType.TRANSFER.value
        ]
        == expected
    )
    assert (
        ClassificationSessionService._allowed_options_by_type(TransactionType.INCOME)[
            TransactionType.TRANSFER.value
        ]
        == expected
    )


def test_category_suggestion_service_skips_transfer_transactions_for_training_and_add(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify category suggestions skip transfer training and add."""
    expense = Transaction(
        account_number="BE55000000000001",
        transaction_date=date(2025, 1, 15),
        amount=-49.99,
        currency="EUR",
        description="PROXIMUS telecom invoice",
        counterparty_name="Counterparty",
        counterparty_account="BE99000000000002",
        transaction_type=TransactionType.EXPENSE,
        expense_category=ExpenseCategory.UTILITIES,
        source_bank="ing",
    )
    transfer = Transaction(
        account_number="BE55000000000003",
        transaction_date=date(2025, 1, 16),
        amount=-240.0,
        currency="EUR",
        description="Card settlement",
        counterparty_name="Counterparty",
        counterparty_account="BE99000000000004",
        transaction_type=TransactionType.TRANSFER,
        transfer_category=TransferCategory.INTERNAL_TRANSFER,
        source_bank="ing",
    )
    db_session.add_all([expense, transfer])
    db_session.commit()

    upsert_calls: list[dict[str, Any]] = []

    def transaction_text(transaction: Transaction) -> str:
        return str(transaction.description)

    def encode_vector(_text: str, **_kwargs: object) -> np.ndarray:
        return np.array([0.1, 0.2, 0.3], dtype=float)

    def record_upsert(**kwargs: object) -> None:
        upsert_calls.append(kwargs)

    monkeypatch.setattr(
        category_suggestion_service,
        "_create_transaction_text",
        transaction_text,
    )
    monkeypatch.setattr(
        category_suggestion_service.model,
        "encode",
        encode_vector,
    )
    monkeypatch.setattr(
        category_suggestion_service.client,
        "upsert",
        record_upsert,
    )

    category_suggestion_service.train_on_existing_transactions(db_session)

    assert len(upsert_calls) == SINGLE_TRANSACTION_COUNT
    assert upsert_calls[0]["collection_name"] == "expense_embeddings"
    assert upsert_calls[0]["points"][0].payload == {
        "category": ExpenseCategory.UTILITIES.value
    }

    upsert_calls.clear()
    category_suggestion_service.add_transaction(transfer)

    assert upsert_calls == []


def test_suggest_category_returns_empty_for_transfer_without_touching_embeddings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify transfer suggestion skips embeddings."""
    def fail_encode_for_transfer(_text: object) -> Never:
        raise AssertionError

    def fail_get_collection_for_transfer(_name: str) -> Never:
        raise AssertionError

    monkeypatch.setattr(
        category_suggestion_service.model,
        "encode",
        fail_encode_for_transfer,
    )
    monkeypatch.setattr(
        category_suggestion_service.client,
        "get_collection",
        fail_get_collection_for_transfer,
    )

    suggestions = category_suggestion_service.suggest_category(
        description="Transfer to savings account",
        amount=-200.0,
        transaction_type=TransactionType.TRANSFER,
    )

    assert suggestions == []


def test_upload_csv_skips_transfer_suggestions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify upload csv skips transfer category suggestions."""
    client = TestClient(app)
    _reset_database(client)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Transaction",
            "Type",
            "Input Currency",
            "Input Amount",
            "Output Currency",
            "Output Amount",
            "USD Equivalent",
            "Fee",
            "Fee Currency",
            "Details",
            "Date / Time (UTC)",
            "normalizedDisplayDetails",
        ]
    )
    writer.writerow(
        [
            "NXT_CASHOUT_1",
            "Transfer Out",
            "USDC",
            "-120.00000000",
            "USDC",
            "120.00000000",
            "$120.00",
            "-",
            "-",
            "approved / Bank transfer to BE55000000000001",
            "2026-03-26 18:19:22",
            "approved / Bank transfer to BE55000000000001",
        ]
    )

    def fail_transfer_suggestion(*_args: object, **_kwargs: object) -> Never:
        raise AssertionError

    monkeypatch.setattr(
        "app.imports.enrichment.category_suggestion_service.suggest_category",
        fail_transfer_suggestion,
    )

    response = client.post(
        "/imports/upload",
        files={
            "file": ("transfers.csv", output.getvalue().encode("utf-8"), "text/csv")
        },
    )

    assert response.status_code == HTTP_OK
    session_payload = response.json()
    assert session_payload["status"] == "awaiting_review"

    approve_response = client.post(f"/imports/{session_payload['id']}/approve")
    assert approve_response.status_code == HTTP_OK

    db = SessionLocal()
    try:
        stored_transfer = db.query(Transaction).order_by(Transaction.id.desc()).first()
    finally:
        db.close()

    assert stored_transfer is not None
    assert stored_transfer.transaction_type == TransactionType.TRANSFER
    assert stored_transfer.transfer_category == TransferCategory.INTERNAL_TRANSFER


def test_transfer_schema_keeps_uncategorized_transfer_rows_uncategorized() -> None:
    """Verify transfer schema keeps uncategorized transfer rows uncategorized."""

    class TransferRow:
        account_number = "BE55000000000001"
        transaction_date = date(2025, 1, 15)
        amount = -240.00
        currency = "EUR"
        description = "Belfius card settlement"
        counterparty_name = "Counterparty"
        counterparty_account = "BE99000000000002"
        transaction_type = TransactionType.TRANSFER
        expense_category = None
        income_category = None
        transfer_category = None
        classification_source = None
        recurrence_pattern_id = None
        source_bank = "ing"

    transaction = TransactionRestore.model_validate(TransferRow(), from_attributes=True)

    assert transaction.transaction_type == TransactionType.TRANSFER
    assert transaction.transfer_category is None
    assert transaction.expense_category is None
    assert transaction.income_category is None

    payload = transaction.model_dump(mode="json")
    assert payload["transaction_type"] == TransactionType.TRANSFER.value
    assert payload["transfer_category"] is None
    assert payload["expense_category"] is None
    assert payload["income_category"] is None
