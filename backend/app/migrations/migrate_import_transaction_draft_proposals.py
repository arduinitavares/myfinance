import logging

from sqlalchemy import inspect, text

from app.database import engine as default_engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def migrate_import_transaction_draft_proposals(bind_engine=default_engine) -> None:
    logger.info("Starting import transaction draft proposal migration...")

    inspector = inspect(bind_engine)
    if "import_transaction_drafts" not in inspector.get_table_names():
        logger.info("import_transaction_drafts table does not exist; skipping migration")
        return

    existing_columns = {
        column["name"] for column in inspector.get_columns("import_transaction_drafts")
    }
    column_statements = {
        "proposed_transaction_type": "ALTER TABLE import_transaction_drafts ADD COLUMN proposed_transaction_type VARCHAR(50)",
        "proposed_expense_category": "ALTER TABLE import_transaction_drafts ADD COLUMN proposed_expense_category VARCHAR(100)",
        "proposed_income_category": "ALTER TABLE import_transaction_drafts ADD COLUMN proposed_income_category VARCHAR(100)",
        "proposed_transfer_category": "ALTER TABLE import_transaction_drafts ADD COLUMN proposed_transfer_category VARCHAR(100)",
        "proposal_source": "ALTER TABLE import_transaction_drafts ADD COLUMN proposal_source VARCHAR(50)",
    }

    with bind_engine.begin() as conn:
        for column_name, statement in column_statements.items():
            if column_name not in existing_columns:
                conn.execute(text(statement))
                logger.info("Added missing import transaction draft column: %s", column_name)

    logger.info("Import transaction draft proposal migration completed successfully.")


if __name__ == "__main__":
    migrate_import_transaction_draft_proposals()
