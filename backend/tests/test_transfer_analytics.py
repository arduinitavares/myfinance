import pytest
import numpy as np
from fastapi.testclient import TestClient
from datetime import date, datetime
from decimal import Decimal
import csv
import io

from app.main import app
from app.database import SessionLocal
from app.models.fx import FXDailyReferenceRate
from app.models.transaction import (
    ExpenseCategory,
    IncomeCategory,
    Transaction,
    TransactionType,
    TransferCategory,
)
from app.models.statistics import CategoryStatistics, FinancialStatistics
from app.schemas.transaction import TransactionRestore
from app.services import classification_commit_service as classification_commit_module
from app.services.classification_commit_service import commit_category_change, normalized_category_for
from app.services.classification_session_service import ClassificationSessionService
from app.routers.suggestions import category_suggestion_service


def _reset_database(client):
    response = client.post("/debug/reset-database")
    assert response.status_code == 200


def _restore_transaction(client, *, description: str):
    payload = {
        "account_number": "BE55000000000001",
        "transaction_date": "2025-01-15",
        "amount": -240.00,
        "currency": "EUR",
        "description": description,
        "counterparty_name": "Counterparty",
        "counterparty_account": "BE99000000000002",
        "transaction_type": TransactionType.TRANSFER.value,
        "transfer_category": TransferCategory.INTERNAL_TRANSFER.value,
        "source_bank": "ing",
    }

    response = client.post("/transactions/restore", json=payload)
    assert response.status_code == 200
    return response.json()


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


def _clear_transactions_and_statistics():
    db_session = SessionLocal()
    try:
        db_session.query(CategoryStatistics).delete()
        db_session.query(FinancialStatistics).delete()
        db_session.query(Transaction).delete()
        db_session.commit()
    finally:
        db_session.close()


def test_manual_transfer_update_uses_transfer_category_and_clears_other_category_columns():
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

    assert response.status_code == 200
    payload = response.json()
    assert payload["transaction_type"] == TransactionType.TRANSFER.value
    assert payload["transfer_category"] == TransferCategory.CREDIT_CARD_SETTLEMENT.value
    assert payload["expense_category"] is None
    assert payload["income_category"] is None


def test_manual_transfer_update_returns_display_fields_for_reporting_currency():
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

    assert response.status_code == 200
    payload = response.json()
    assert payload["amount"] == -240.0
    assert payload["currency"] == "EUR"
    assert payload["display_amount"] == -300.0
    assert payload["display_currency"] == "USD"
    assert payload["display_fx_rate"] == 1.25
    assert payload["display_rate_date"] == "2025-01-15"


def test_restore_returns_display_fields_for_reporting_currency():
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

    assert response.status_code == 200
    body = response.json()
    assert body["amount"] == -240.0
    assert body["currency"] == "EUR"
    assert body["display_amount"] == -300.0
    assert body["display_currency"] == "USD"
    assert body["display_fx_rate"] == 1.25
    assert body["display_rate_date"] == "2025-01-15"


def test_statistics_overview_excludes_transfer_transactions():
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

        from app.services.statistics_service import StatisticsService

        StatisticsService.initialize_statistics(db_session)
        StatisticsService.initialize_category_statistics(db_session)

        eur_response = client.get("/statistics/overview")
        assert eur_response.status_code == 200

        eur_payload = eur_response.json()
        eur_current_month = eur_payload["current_month"]
        eur_all_time = eur_payload["all_time"]

        assert eur_current_month["reporting_currency"] == "EUR"
        assert eur_current_month["period_income"] == 5000.0
        assert eur_current_month["period_expenses"] == 189.0
        assert eur_current_month["income_count"] == 1
        assert eur_current_month["expense_count"] == 2
        assert eur_current_month["total_income"] == 5000.0
        assert eur_current_month["total_expenses"] == 189.0
        assert eur_current_month["total_net_savings"] == 4811.0
        assert eur_current_month["average_expense"] == 94.5
        assert eur_all_time["reporting_currency"] == "EUR"
        assert eur_all_time["total_income"] == 5000.0
        assert eur_all_time["total_expenses"] == 189.0

        usd_response = client.get(
            "/statistics/overview",
            headers={"X-Reporting-Currency": "USD"},
        )
        assert usd_response.status_code == 200

        usd_payload = usd_response.json()
        usd_current_month = usd_payload["current_month"]
        usd_all_time = usd_payload["all_time"]

        assert usd_current_month["reporting_currency"] == "USD"
        assert usd_current_month["period_income"] == 6250.0
        assert usd_current_month["period_expenses"] == 236.25
        assert usd_current_month["total_income"] == 6250.0
        assert usd_current_month["total_expenses"] == 236.25
        assert usd_current_month["total_net_savings"] == 6013.75
        assert usd_current_month["average_income"] == 6250.0
        assert usd_current_month["average_expense"] == 118.12
        assert usd_all_time["reporting_currency"] == "USD"
        assert usd_all_time["total_income"] == 6250.0
        assert usd_all_time["total_expenses"] == 236.25
    finally:
        db_session.close()


def test_statistics_overview_keeps_previous_year_month_when_only_transfers_exist():
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

        from app.services.statistics_service import StatisticsService

        StatisticsService.initialize_statistics(db_session)
        StatisticsService.initialize_category_statistics(db_session)

        response = client.get("/statistics/overview")
        assert response.status_code == 200

        payload = response.json()
        previous_year_last_month = payload["previous_year_last_month"]

        assert previous_year_last_month is not None
        assert previous_year_last_month["reporting_currency"] == "EUR"
        assert previous_year_last_month["date"] == "2024-12-31"
        assert previous_year_last_month["period_income"] == 0.0
        assert previous_year_last_month["period_expenses"] == 0.0
        assert previous_year_last_month["total_net_savings"] == 0.0
    finally:
        db_session.close()


def test_calculate_statistics_keeps_raw_persisted_totals_for_mixed_currency_rows():
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

        from app.services.statistics_service import StatisticsService
        from app.models.statistics import StatisticsPeriod

        stats = StatisticsService.calculate_statistics(
            db_session,
            StatisticsPeriod.MONTHLY,
            date(2025, 1, 31),
        )

        assert stats["period_income"] == 5000.0
        assert stats["period_expenses"] == 180.0
        assert stats["total_expenses"] == 180.0
        assert stats["period_net_savings"] == 4820.0
        assert stats["average_expense"] == 90.0
    finally:
        db_session.close()


def test_category_statistics_ignore_transfer_rows():
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

        from app.services.statistics_service import StatisticsService

        StatisticsService.initialize_statistics(db_session)
        StatisticsService.initialize_category_statistics(db_session)

        response = client.get("/statistics/by-category", params={"period": "monthly", "date": "2025-01-15"})
        assert response.status_code == 200

        payload = response.json()
        categories = {item["category"] for item in payload["items"]}

        assert "Internal Transfer" not in categories
        assert categories == {"Salary", "Groceries"}
    finally:
        db_session.close()


def test_transfer_summary_groups_by_category_and_sign():
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
            description="USD transfer should now be converted through the reporting currency service",
            amount=-80.0,
            transaction_type=TransactionType.TRANSFER,
            transfer_category=TransferCategory.INTERNAL_TRANSFER,
        ).currency = "USD"
        db_session.commit()

        response = client.get(
            "/statistics/transfers/summary",
            params={"start_date": "2025-01-01", "end_date": "2025-01-31"},
        )
        assert response.status_code == 200

        payload = response.json()
        assert payload["start_date"] == "2025-01-01"
        assert payload["end_date"] == "2025-01-31"
        assert payload["reporting_currency"] == "EUR"

        by_category = {item["subtype"]: item for item in payload["items"]}

        assert by_category["Credit Card Settlement"]["transaction_count"] == 2
        assert by_category["Credit Card Settlement"]["total_outgoing"] == 240.0
        assert by_category["Credit Card Settlement"]["total_incoming"] == 240.0
        assert by_category["Internal Transfer"]["transaction_count"] == 2
        assert by_category["Internal Transfer"]["total_outgoing"] == 164.0
        assert by_category["Internal Transfer"]["total_incoming"] == 0.0
        assert by_category["Loan Repayment Received"]["transaction_count"] == 1
        assert by_category["Loan Repayment Received"]["total_outgoing"] == 0.0
        assert by_category["Loan Repayment Received"]["total_incoming"] == 55.0

        usd_response = client.get(
            "/statistics/transfers/summary",
            params={"start_date": "2025-01-01", "end_date": "2025-01-31"},
            headers={"X-Reporting-Currency": "USD"},
        )
        assert usd_response.status_code == 200

        usd_payload = usd_response.json()
        assert usd_payload["reporting_currency"] == "USD"

        usd_by_category = {item["subtype"]: item for item in usd_payload["items"]}
        assert usd_by_category["Credit Card Settlement"]["total_outgoing"] == 300.0
        assert usd_by_category["Credit Card Settlement"]["total_incoming"] == 300.0
        assert usd_by_category["Internal Transfer"]["transaction_count"] == 2
        assert usd_by_category["Internal Transfer"]["total_outgoing"] == 205.0
        assert usd_by_category["Internal Transfer"]["total_incoming"] == 0.0
        assert usd_by_category["Loan Repayment Received"]["total_incoming"] == 68.75
    finally:
        db_session.close()


def test_transfer_summary_empty_state_honors_requested_dates():
    client = TestClient(app)
    _clear_transactions_and_statistics()

    response = client.get(
        "/statistics/transfers/summary",
        params={"start_date": "2025-01-01", "end_date": "2025-01-31"},
    )

    assert response.status_code == 200
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


def test_internal_transfer_exists_only_in_transfer_category_enum():
    assert "INTERNAL_TRANSFER" not in ExpenseCategory.__members__
    assert "INTERNAL_TRANSFER" not in IncomeCategory.__members__
    assert TransferCategory.INTERNAL_TRANSFER.value == "Internal Transfer"


def test_transfer_summary_rejects_invalid_dates_when_no_transactions_exist():
    client = TestClient(app)
    _clear_transactions_and_statistics()

    response = client.get(
        "/statistics/transfers/summary",
        params={"start_date": "not-a-date"},
    )

    assert response.status_code == 400


def test_normalized_category_for_validates_transfer_categories():
    assert (
        normalized_category_for(
            transaction_type=TransactionType.TRANSFER,
            category=TransferCategory.CREDIT_CARD_SETTLEMENT.value,
            amount=-240.0,
        )
        == TransferCategory.CREDIT_CARD_SETTLEMENT.value
    )

    with pytest.raises(ValueError):
        normalized_category_for(
            transaction_type=TransactionType.TRANSFER,
            category=ExpenseCategory.UTILITIES.value,
            amount=-240.0,
        )


def test_commit_transfer_writes_first_class_transfer_category_and_clears_other_category_fields(db_session):
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
        transaction_type=TransactionType.TRANSFER,
        category=TransferCategory.CREDIT_CARD_SETTLEMENT.value,
        classification_source="manual",
        recurrence_pattern_id=None,
        commit=False,
    )

    assert updated.transaction_type == TransactionType.TRANSFER
    assert updated.transfer_category == TransferCategory.CREDIT_CARD_SETTLEMENT
    assert updated.expense_category is None
    assert updated.income_category is None


def test_commit_reclassifying_indexed_expense_to_transfer_removes_stale_embeddings(db_session, monkeypatch):
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

    delete_calls = []
    monkeypatch.setattr(
        classification_commit_module.StatisticsService,
        "update_statistics",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        category_suggestion_service.client,
        "delete",
        lambda collection_name, points_selector, **kwargs: delete_calls.append(
            (collection_name, list(points_selector))
        ),
    )
    monkeypatch.setattr(
        category_suggestion_service.client,
        "upsert",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("transfer reclassification should not re-add an embedding")
        ),
    )
    monkeypatch.setattr(
        category_suggestion_service.model,
        "encode",
        lambda text: (_ for _ in ()).throw(
            AssertionError("transfer reclassification should not encode a new embedding")
        ),
    )

    updated = commit_category_change(
        db=db_session,
        transaction=transaction,
        transaction_type=TransactionType.TRANSFER,
        category=TransferCategory.CREDIT_CARD_SETTLEMENT.value,
        classification_source="manual",
        recurrence_pattern_id=None,
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


def test_allowed_options_for_transfer_include_full_transfer_category_family():
    expected = [category.value for category in TransferCategory]

    assert ClassificationSessionService._allowed_options_by_type(TransactionType.TRANSFER) == {
        TransactionType.TRANSFER.value: expected
    }
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
    db_session, monkeypatch
):
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

    upsert_calls = []
    monkeypatch.setattr(
        category_suggestion_service,
        "_create_transaction_text",
        lambda transaction: transaction.description,
    )
    monkeypatch.setattr(
        category_suggestion_service.model,
        "encode",
        lambda text: np.array([0.1, 0.2, 0.3], dtype=float),
    )
    monkeypatch.setattr(
        category_suggestion_service.client,
        "upsert",
        lambda **kwargs: upsert_calls.append(kwargs),
    )

    category_suggestion_service.train_on_existing_transactions(db_session)

    assert len(upsert_calls) == 1
    assert upsert_calls[0]["collection_name"] == "expense_embeddings"
    assert upsert_calls[0]["points"][0].payload == {"category": ExpenseCategory.UTILITIES.value}

    upsert_calls.clear()
    category_suggestion_service.add_transaction(transfer)

    assert upsert_calls == []


def test_suggest_category_returns_empty_for_transfer_without_touching_embeddings(monkeypatch):
    monkeypatch.setattr(
        category_suggestion_service.model,
        "encode",
        lambda text: (_ for _ in ()).throw(AssertionError("transfer suggestions should short-circuit")),
    )
    monkeypatch.setattr(
        category_suggestion_service.client,
        "get_collection",
        lambda name: (_ for _ in ()).throw(AssertionError("transfer suggestions should not hit collections")),
    )

    suggestions = category_suggestion_service.suggest_category(
        description="Transfer to savings account",
        amount=-200.0,
        transaction_type=TransactionType.TRANSFER,
    )

    assert suggestions == []


def test_upload_csv_skips_transfer_category_suggestions(monkeypatch):
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

    monkeypatch.setattr(
        "app.imports.enrichment.category_suggestion_service.suggest_category",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("upload should skip category suggestions for transfer rows")
        ),
    )

    response = client.post(
        "/imports/upload",
        files={"file": ("transfers.csv", output.getvalue().encode("utf-8"), "text/csv")},
    )

    assert response.status_code == 200
    session_payload = response.json()
    assert session_payload["status"] == "awaiting_review"

    approve_response = client.post(f"/imports/{session_payload['id']}/approve")
    assert approve_response.status_code == 200

    db = SessionLocal()
    try:
        stored_transfer = db.query(Transaction).order_by(Transaction.id.desc()).first()
    finally:
        db.close()

    assert stored_transfer is not None
    assert stored_transfer.transaction_type == TransactionType.TRANSFER
    assert stored_transfer.transfer_category == TransferCategory.INTERNAL_TRANSFER


def test_transfer_schema_keeps_uncategorized_transfer_rows_uncategorized():
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
