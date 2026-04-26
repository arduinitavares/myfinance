"""Module for backend tests imports test_import_models."""

from pathlib import Path

import app.config as config_module
import pytest
from app import database_manager
from app.database import Base, engine
from app.imports.contracts import ExtractedTransaction, ImportStrategyKey
from app.models.imports import ImportSession
from app.schemas.transaction import Transaction, TransactionCreate
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

RECURRENCE_PATTERN_ID: int = 42


def test_settings_exposes_batch_import_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify settings exposes batch import dir."""
    batch_dir = tmp_path / "bank_files"
    monkeypatch.setenv("MYFINANCE_BATCH_IMPORT_DIR", str(batch_dir))

    loaded = config_module.load_settings()

    assert loaded.batch_import_dir == batch_dir.resolve()


def test_import_tables_exist_after_init_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify import tables exist after init database."""
    db_path = tmp_path / "bootstrap.sqlite"
    temp_engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )

    monkeypatch.setattr(database_manager, "engine", temp_engine)
    database_manager.init_database()

    with temp_engine.begin() as conn:
        conn.execute(text("DROP TABLE import_batch_items"))
        conn.execute(text("DROP TABLE import_batch_runs"))

    database_manager.init_database()

    tables = set(inspect(temp_engine).get_table_names())
    assert {
        "import_sessions",
        "import_statement_drafts",
        "import_transaction_drafts",
        "import_issues",
        "import_batch_runs",
        "import_batch_items",
    } <= tables

    batch_item_columns = {
        column["name"]
        for column in inspect(temp_engine).get_columns("import_batch_items")
    }
    assert {
        "batch_run_id",
        "filename",
        "status",
        "session_id",
        "existing_session_id",
    } <= batch_item_columns

    batch_run_columns = {
        column["name"]
        for column in inspect(temp_engine).get_columns("import_batch_runs")
    }
    assert {
        "folder_path",
        "status",
        "total_files",
        "processed_count",
        "skipped_existing_count",
        "unsupported_count",
        "failed_count",
        "created_at",
        "completed_at",
    } <= batch_run_columns


def test_import_session_timestamp_columns_are_populated_on_insert(
    db_session: Session,
) -> None:
    """Verify import session timestamp columns are populated on insert."""
    session = ImportSession(
        file_name="statement.pdf",
        file_hash="abc123",
        mime_type="application/pdf",
        status="uploaded",
    )
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)

    assert session.created_at is not None
    assert session.updated_at is not None
    assert session.created_at <= session.updated_at


def test_import_schema_includes_statement_and_transaction_metadata_columns() -> None:
    """Verify import schema includes statement and transaction metadata columns."""
    database_manager.reset_database()
    database_manager.init_database()

    import_columns = {
        column["name"]: column
        for column in inspect(engine).get_columns("import_sessions")
    }
    statement_columns = {
        column["name"]: column
        for column in inspect(engine).get_columns("import_statement_drafts")
    }
    transaction_columns = {
        column["name"]: column
        for column in inspect(engine).get_columns("import_transaction_drafts")
    }

    assert {"created_at", "updated_at"} <= import_columns.keys()
    assert {
        "statement_period_start",
        "statement_period_end",
        "summary_text",
        "opening_balance",
        "closing_balance",
        "available_balance",
        "total_debit",
        "total_credit",
        "transaction_count",
    } <= statement_columns.keys()
    assert {
        "transaction_date",
        "debit_credit",
        "confidence",
        "field_confidence",
        "raw_fields",
        "proposed_transaction_type",
        "proposed_expense_category",
        "proposed_income_category",
        "proposed_transfer_category",
        "classification_source",
        "recurrence_pattern_id",
    } <= transaction_columns.keys()


def test_import_strategy_key_includes_nexo_csv() -> None:
    """Verify import strategy key includes nexo csv."""
    assert ImportStrategyKey.NEXO_CSV.value == "nexo_csv"


def test_extracted_transaction_exposes_review_time_proposals() -> None:
    """Verify extracted transaction exposes review time proposals."""
    transaction = ExtractedTransaction(
        transaction_date="2026-04-11",
        source_description="Nexo card purchase",
        signed_amount=-10.0,
        currency="EUR",
        debit_credit="debit",
        source_locator="csv:row:2",
        proposed_transaction_type="Expense",
        proposed_expense_category="Groceries",
        proposed_income_category=None,
        proposed_transfer_category=None,
        classification_source="deterministic",
        recurrence_pattern_id=RECURRENCE_PATTERN_ID,
    )

    dumped = transaction.model_dump()
    assert dumped["proposed_transaction_type"] == "Expense"
    assert dumped["proposed_expense_category"] == "Groceries"
    assert dumped["classification_source"] == "deterministic"
    assert dumped["recurrence_pattern_id"] == RECURRENCE_PATTERN_ID


def test_transactions_include_import_traceability_columns() -> None:
    """Verify transactions include import traceability columns."""
    database_manager.reset_database()
    database_manager.init_database()

    transaction_columns = {
        column["name"]: column for column in inspect(engine).get_columns("transactions")
    }

    assert {
        "import_session_id",
        "import_source_locator",
        "import_source_description",
        "canonical_description_en",
    } <= transaction_columns.keys()


def test_init_database_backfills_missing_transaction_traceability_columns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify init database backfills missing transaction traceability columns."""
    db_path = tmp_path / "legacy_imports.sqlite"
    temp_engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )

    Base.metadata.create_all(
        bind=temp_engine,
        tables=[
            table
            for table in Base.metadata.sorted_tables
            if table.name != "transactions"
        ],
    )
    with temp_engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE transactions (
                    id INTEGER PRIMARY KEY,
                    account_number VARCHAR(50),
                    transaction_date DATE,
                    amount FLOAT,
                    currency VARCHAR(3),
                    description VARCHAR(500),
                    counterparty_name VARCHAR(200),
                    counterparty_account VARCHAR(50),
                    transaction_type VARCHAR(50),
                    expense_category VARCHAR(100),
                    income_category VARCHAR(100),
                    transfer_category VARCHAR(100),
                    classification_source VARCHAR(50),
                    recurrence_pattern_id INTEGER,
                    source_bank VARCHAR(10)
                )
                """
            )
        )

    monkeypatch.setattr(database_manager, "engine", temp_engine)
    database_manager.init_database()

    transaction_columns = {
        column["name"] for column in inspect(temp_engine).get_columns("transactions")
    }
    assert {
        "import_session_id",
        "import_source_locator",
        "import_source_description",
        "canonical_description_en",
    } <= transaction_columns

    transaction_indexes = inspect(temp_engine).get_indexes("transactions")
    assert any(
        index["name"] == "ix_transactions_import_session_id"
        for index in transaction_indexes
    )


def test_init_database_backfills_missing_import_draft_proposal_columns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify init database backfills missing proposal columns."""
    db_path = tmp_path / "legacy_import_drafts.sqlite"
    temp_engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )

    Base.metadata.create_all(
        bind=temp_engine,
        tables=[
            table
            for table in Base.metadata.sorted_tables
            if table.name != "import_transaction_drafts"
        ],
    )
    with temp_engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE import_transaction_drafts (
                    id INTEGER PRIMARY KEY,
                    import_statement_draft_id INTEGER NOT NULL,
                    transaction_date DATE,
                    source_description TEXT NOT NULL,
                    canonical_description_en TEXT,
                    signed_amount FLOAT NOT NULL,
                    currency VARCHAR(10) NOT NULL,
                    debit_credit VARCHAR(10),
                    source_locator VARCHAR(255) NOT NULL,
                    inferred_category VARCHAR(100),
                    category_source VARCHAR(50),
                    confidence FLOAT,
                    field_confidence TEXT,
                    raw_fields TEXT,
                    edit_source VARCHAR(50) NOT NULL
                )
                """
            )
        )

    monkeypatch.setattr(database_manager, "engine", temp_engine)
    database_manager.init_database()

    transaction_columns = {
        column["name"]
        for column in inspect(temp_engine).get_columns("import_transaction_drafts")
    }
    assert {
        "proposed_transaction_type",
        "proposed_expense_category",
        "proposed_income_category",
        "proposed_transfer_category",
        "classification_source",
        "recurrence_pattern_id",
    } <= transaction_columns


def test_transaction_read_schema_exposes_traceability_fields_only() -> None:
    """Verify transaction read schema exposes traceability fields only."""
    assert "import_session_id" in Transaction.model_fields
    assert "import_source_locator" in Transaction.model_fields
    assert "import_source_description" in Transaction.model_fields
    assert "canonical_description_en" in Transaction.model_fields

    assert "import_session_id" not in TransactionCreate.model_fields
    assert "import_source_locator" not in TransactionCreate.model_fields
    assert "import_source_description" not in TransactionCreate.model_fields
    assert "canonical_description_en" not in TransactionCreate.model_fields
