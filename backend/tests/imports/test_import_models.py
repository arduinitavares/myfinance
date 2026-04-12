from datetime import datetime

from sqlalchemy import create_engine, inspect, text

from app.database import engine
from app.database import Base
import app.database_manager as database_manager
from app.models.imports import ImportSession
from app.schemas.transaction import Transaction, TransactionCreate


def test_import_tables_exist_after_init_database():
    database_manager.reset_database()
    database_manager.init_database()
    tables = set(inspect(engine).get_table_names())
    assert {
        "import_sessions",
        "import_statement_drafts",
        "import_transaction_drafts",
        "import_issues",
    } <= tables


def test_import_session_timestamp_columns_are_populated_on_insert(db_session):
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


def test_import_schema_includes_statement_and_transaction_metadata_columns():
    database_manager.reset_database()
    database_manager.init_database()

    import_columns = {column["name"]: column for column in inspect(engine).get_columns("import_sessions")}
    statement_columns = {column["name"]: column for column in inspect(engine).get_columns("import_statement_drafts")}
    transaction_columns = {column["name"]: column for column in inspect(engine).get_columns("import_transaction_drafts")}

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
    } <= transaction_columns.keys()


def test_transactions_include_import_traceability_columns():
    database_manager.reset_database()
    database_manager.init_database()

    transaction_columns = {column["name"]: column for column in inspect(engine).get_columns("transactions")}

    assert {
        "import_session_id",
        "import_source_locator",
        "import_source_description",
        "canonical_description_en",
    } <= transaction_columns.keys()


def test_init_database_backfills_missing_transaction_traceability_columns(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy_imports.sqlite"
    temp_engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})

    Base.metadata.create_all(
        bind=temp_engine,
        tables=[table for table in Base.metadata.sorted_tables if table.name != "transactions"],
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

    transaction_columns = {column["name"] for column in inspect(temp_engine).get_columns("transactions")}
    assert {
        "import_session_id",
        "import_source_locator",
        "import_source_description",
        "canonical_description_en",
    } <= transaction_columns

    transaction_indexes = inspect(temp_engine).get_indexes("transactions")
    assert any(index["name"] == "ix_transactions_import_session_id" for index in transaction_indexes)


def test_transaction_read_schema_exposes_traceability_fields_only():
    assert "import_session_id" in Transaction.model_fields
    assert "import_source_locator" in Transaction.model_fields
    assert "import_source_description" in Transaction.model_fields
    assert "canonical_description_en" in Transaction.model_fields

    assert "import_session_id" not in TransactionCreate.model_fields
    assert "import_source_locator" not in TransactionCreate.model_fields
    assert "import_source_description" not in TransactionCreate.model_fields
    assert "canonical_description_en" not in TransactionCreate.model_fields
