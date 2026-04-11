from sqlalchemy import inspect

from app.database import engine
from app.database_manager import init_database, reset_database


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
