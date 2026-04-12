import pytest
import numpy as np
from fastapi.testclient import TestClient
from datetime import date

from app.main import app
from app.models.transaction import (
    ExpenseCategory,
    IncomeCategory,
    Transaction,
    TransactionType,
    TransferCategory,
)
from app.routers import transactions as tx_router
from app.schemas.transaction import TransactionCreate
from app.schemas.transaction import TransactionRestore
from app.services import classification_commit_service as classification_commit_module
from app.services.classification_commit_service import commit_category_change, normalized_category_for
from app.services.classification_session_service import ClassificationSessionService
from app.routers.suggestions import category_suggestion_service


def _reset_database(client):
    response = client.post("/debug/reset-database")
    assert response.status_code == 200


def _reset_rate_limiter():
    try:
        tx_router._upload_attempts.clear()  # type: ignore[attr-defined]
    except Exception:
        pass


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
        "expense_category": ExpenseCategory.INTERNAL_TRANSFER.value,
        "source_bank": "ing",
    }

    response = client.post("/transactions/restore", json=payload)
    assert response.status_code == 200
    return response.json()


def test_manual_transfer_update_uses_transfer_category_and_clears_legacy_categories():
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


def test_commit_transfer_writes_first_class_transfer_category_and_clears_legacy_fields(db_session):
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
        expense_category=ExpenseCategory.INTERNAL_TRANSFER,
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
    _reset_rate_limiter()
    _reset_database(client)

    monkeypatch.setattr(
        tx_router.CSVParser,
        "parse_csv",
        lambda file_path, source_filename=None: [
            TransactionCreate(
                account_number="BE55000000000001",
                transaction_date=date(2025, 1, 15),
                amount=-240.0,
                currency="EUR",
                description="Transfer to savings account",
                counterparty_name="Counterparty",
                counterparty_account="BE99000000000002",
                transaction_type=TransactionType.TRANSFER,
                source_bank="ing",
            )
        ],
    )
    monkeypatch.setattr(
        tx_router.category_suggestion_service,
        "suggest_category",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("upload should skip category suggestions for transfer rows")
        ),
    )
    monkeypatch.setattr(tx_router.StatisticsService, "update_statistics", lambda *args, **kwargs: None)
    monkeypatch.setattr(tx_router.AnomalyDetectionService, "detect_anomalies", lambda *args, **kwargs: None)

    response = client.post(
        "/transactions/upload/",
        files={"file": ("transfers.csv", b"ignored-by-mock\n", "text/csv")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["transaction_type"] == TransactionType.TRANSFER.value
    assert payload[0]["transfer_category"] is None


def test_transfer_schema_normalizes_legacy_transfer_rows_from_orm():
    class LegacyTransferRow:
        account_number = "BE55000000000001"
        transaction_date = date(2025, 1, 15)
        amount = -240.00
        currency = "EUR"
        description = "Belfius card settlement"
        counterparty_name = "Counterparty"
        counterparty_account = "BE99000000000002"
        transaction_type = TransactionType.TRANSFER
        expense_category = ExpenseCategory.INTERNAL_TRANSFER
        income_category = IncomeCategory.INTERNAL_TRANSFER
        transfer_category = None
        classification_source = None
        recurrence_pattern_id = None
        source_bank = "ing"

    transaction = TransactionRestore.model_validate(LegacyTransferRow(), from_attributes=True)

    assert transaction.transaction_type == TransactionType.TRANSFER
    assert transaction.transfer_category == TransferCategory.INTERNAL_TRANSFER
    assert transaction.expense_category is None
    assert transaction.income_category is None

    payload = transaction.model_dump(mode="json")
    assert payload["transaction_type"] == TransactionType.TRANSFER.value
    assert payload["transfer_category"] == TransferCategory.INTERNAL_TRANSFER.value
    assert payload["expense_category"] is None
    assert payload["income_category"] is None
