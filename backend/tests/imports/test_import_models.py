from datetime import datetime

from sqlalchemy import inspect

from app.database import engine
from app.database_manager import init_database, reset_database
from app.models.imports import ImportSession


def test_import_tables_exist_after_init_database():
    reset_database()
    init_database()
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
    reset_database()
    init_database()

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
