from sqlalchemy import create_engine, inspect, text

from app.database import engine
from app.database import Base
import app.database_manager as database_manager
import app.config as config_module
from app.models.imports import ImportBatchItem, ImportBatchRun, ImportSession
from app.models.transaction import ExpenseCategory, TransactionType
from app.schemas.imports import (
    ImportTransactionDraftResponse,
    build_import_transaction_draft_response_payload,
)
from app.services.currency_conversion import DisplayMoney
from app.schemas.transaction import Transaction, TransactionCreate


def test_settings_exposes_batch_import_dir(monkeypatch, tmp_path):
    batch_dir = tmp_path / "bank_files"
    monkeypatch.setenv("MYFINANCE_BATCH_IMPORT_DIR", str(batch_dir))

    loaded = config_module.load_settings()

    assert loaded.batch_import_dir == batch_dir.resolve()


def test_import_tables_exist_after_init_database(tmp_path, monkeypatch):
    db_path = tmp_path / "bootstrap.sqlite"
    temp_engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})

    monkeypatch.setattr(database_manager, "engine", temp_engine)
    database_manager.init_database()

    with temp_engine.begin() as conn:
        ImportBatchItem.__table__.drop(bind=conn)
        ImportBatchRun.__table__.drop(bind=conn)

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

    batch_item_columns = {column["name"] for column in inspect(temp_engine).get_columns("import_batch_items")}
    assert {
        "batch_run_id",
        "filename",
        "status",
        "session_id",
        "existing_session_id",
    } <= batch_item_columns

    batch_run_columns = {column["name"] for column in inspect(temp_engine).get_columns("import_batch_runs")}
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
        "proposed_transaction_type",
        "proposed_expense_category",
        "proposed_income_category",
        "proposed_transfer_category",
        "proposal_source",
    } <= transaction_columns.keys()


def test_import_transaction_draft_response_exposes_proposal_fields():
    transaction_draft = type(
        "Draft",
        (),
        {
            "id": 17,
            "transaction_date": None,
            "source_description": "Bancontact payment",
            "canonical_description_en": None,
            "signed_amount": -12.5,
            "currency": "EUR",
            "debit_credit": "debit",
            "source_locator": "csv:row:3",
            "proposed_transaction_type": TransactionType.EXPENSE,
            "proposed_expense_category": ExpenseCategory.GROCERIES,
            "proposed_income_category": None,
            "proposed_transfer_category": None,
            "proposal_source": "deterministic_extracted",
            "confidence": 0.83,
            "edit_source": "deterministic_extracted",
        },
    )()

    payload = build_import_transaction_draft_response_payload(
        transaction_draft,
        DisplayMoney.unavailable(display_currency="EUR", reason="missing_transaction_date"),
    )

    assert "inferred_category" not in payload
    assert "category_source" not in payload
    assert payload["proposed_transaction_type"] == "Expense"
    assert payload["proposed_expense_category"] == "Groceries"
    assert payload["proposal_source"] == "deterministic_extracted"

    response = ImportTransactionDraftResponse.model_validate(payload)
    assert response.proposed_expense_category == "Groceries"
    assert response.proposal_source == "deterministic_extracted"


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


def test_init_database_backfills_missing_import_transaction_draft_proposal_columns(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy_import_drafts.sqlite"
    temp_engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})

    Base.metadata.create_all(bind=temp_engine)
    with temp_engine.begin() as conn:
        conn.execute(text("DROP TABLE import_transaction_drafts"))
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
                    edit_source VARCHAR(50) NOT NULL DEFAULT 'ai_extracted'
                )
                """
            )
        )

    monkeypatch.setattr(database_manager, "engine", temp_engine)
    database_manager.init_database()

    transaction_columns = {column["name"] for column in inspect(temp_engine).get_columns("import_transaction_drafts")}
    assert {
        "proposed_transaction_type",
        "proposed_expense_category",
        "proposed_income_category",
        "proposed_transfer_category",
        "proposal_source",
    } <= transaction_columns


def test_transaction_read_schema_exposes_traceability_fields_only():
    assert "import_session_id" in Transaction.model_fields
    assert "import_source_locator" in Transaction.model_fields
    assert "import_source_description" in Transaction.model_fields
    assert "canonical_description_en" in Transaction.model_fields

    assert "import_session_id" not in TransactionCreate.model_fields
    assert "import_source_locator" not in TransactionCreate.model_fields
    assert "import_source_description" not in TransactionCreate.model_fields
    assert "canonical_description_en" not in TransactionCreate.model_fields
