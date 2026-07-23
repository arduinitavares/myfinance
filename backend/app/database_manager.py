"""Module for backend app database_manager."""

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from sqlalchemy import Table, inspect, text
from sqlalchemy.orm import Session

from .config import settings
from .database import Base, engine
from .imports.dedupe import ensure_import_session_file_hash_uniqueness
from .migrations.migrate_europe_iban_reclassification import (
    migrate_europe_iban_reclassification,
)
from .models.anomaly import AnomalyPattern, AnomalyRule, TransactionAnomaly
from .models.classification import (
    ClassificationSession,
    ClassificationTurn,
    RecurrencePattern,
)
from .models.financial_health import FinancialHealth, FinancialRecommendation
from .models.financial_projection import (
    ProjectionParameter,
    ProjectionResult,
    ProjectionScenario,
)
from .models.imports import (
    ImportBatchItem,
    ImportBatchRun,
    ImportIssue,
    ImportSession,
    ImportStatementDraft,
    ImportTransactionDraft,
)
from .models.statistics import CategoryStatistics, FinancialStatistics
from .models.transaction import Transaction
from .services.financial_health_service import FinancialHealthService
from .services.projection_service import ProjectionService
from .services.statistics_service import StatisticsService

logging.basicConfig(level=logging.INFO)
logger: logging.Logger = logging.getLogger(__name__)

REQUIRED_TABLE_NAMES: tuple[str, ...] = (
    "transactions",
    "classification_sessions",
    "classification_turns",
    "recurrence_patterns",
    "financial_statistics",
    "category_statistics",
    "financial_health",
    "financial_recommendations",
    "fx_daily_reference_rates",
    "projection_scenarios",
    "projection_parameters",
    "projection_results",
    "transaction_anomalies",
    "anomaly_patterns",
    "anomaly_rules",
    "import_sessions",
    "import_batch_runs",
    "import_batch_items",
    "import_statement_drafts",
    "import_transaction_drafts",
    "import_issues",
)


def _import_artifact_root() -> Path:
    return settings.imports_dir


def _ensure_classification_transaction_columns() -> None:
    inspector = inspect(engine)
    if "transactions" not in inspector.get_table_names():
        return

    transaction_columns = {
        column["name"] for column in inspector.get_columns("transactions")
    }
    with engine.begin() as conn:
        if "transfer_category" not in transaction_columns:
            conn.execute(
                text(
                    "ALTER TABLE transactions ADD COLUMN transfer_category VARCHAR(50)"
                )
            )
        if "classification_source" not in transaction_columns:
            conn.execute(
                text(
                    "ALTER TABLE transactions ADD COLUMN "
                    "classification_source VARCHAR(50)"
                )
            )
        if "recurrence_pattern_id" not in transaction_columns:
            conn.execute(
                text(
                    "ALTER TABLE transactions ADD COLUMN recurrence_pattern_id INTEGER"
                )
            )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_transactions_recurrence_pattern_id "
                "ON transactions (recurrence_pattern_id)"
            )
        )


def _ensure_import_traceability_transaction_columns() -> None:
    inspector = inspect(engine)
    if "transactions" not in inspector.get_table_names():
        return

    transaction_columns = {
        column["name"] for column in inspector.get_columns("transactions")
    }
    with engine.begin() as conn:
        if "import_session_id" not in transaction_columns:
            conn.execute(
                text("ALTER TABLE transactions ADD COLUMN import_session_id INTEGER")
            )
        if "import_source_locator" not in transaction_columns:
            conn.execute(
                text(
                    "ALTER TABLE transactions ADD COLUMN "
                    "import_source_locator VARCHAR(255)"
                )
            )
        if "import_source_description" not in transaction_columns:
            conn.execute(
                text(
                    "ALTER TABLE transactions ADD COLUMN "
                    "import_source_description VARCHAR(500)"
                )
            )
        if "canonical_description_en" not in transaction_columns:
            conn.execute(
                text(
                    "ALTER TABLE transactions ADD COLUMN "
                    "canonical_description_en VARCHAR(500)"
                )
            )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_transactions_import_session_id "
                "ON transactions (import_session_id)"
            )
        )


def _ensure_import_transaction_draft_proposal_columns() -> None:
    inspector = inspect(engine)
    if "import_transaction_drafts" not in inspector.get_table_names():
        return

    transaction_columns = {
        column["name"] for column in inspector.get_columns("import_transaction_drafts")
    }
    with engine.begin() as conn:
        if "proposed_transaction_type" not in transaction_columns:
            conn.execute(
                text(
                    "ALTER TABLE import_transaction_drafts ADD COLUMN "
                    "proposed_transaction_type VARCHAR(50)"
                )
            )
        if "proposed_expense_category" not in transaction_columns:
            conn.execute(
                text(
                    "ALTER TABLE import_transaction_drafts ADD COLUMN "
                    "proposed_expense_category VARCHAR(100)"
                )
            )
        if "proposed_income_category" not in transaction_columns:
            conn.execute(
                text(
                    "ALTER TABLE import_transaction_drafts ADD COLUMN "
                    "proposed_income_category VARCHAR(100)"
                )
            )
        if "proposed_transfer_category" not in transaction_columns:
            conn.execute(
                text(
                    "ALTER TABLE import_transaction_drafts ADD COLUMN "
                    "proposed_transfer_category VARCHAR(100)"
                )
            )
        if "classification_source" not in transaction_columns:
            conn.execute(
                text(
                    "ALTER TABLE import_transaction_drafts ADD COLUMN "
                    "classification_source VARCHAR(50)"
                )
            )
        if "recurrence_pattern_id" not in transaction_columns:
            conn.execute(
                text(
                    "ALTER TABLE import_transaction_drafts ADD COLUMN "
                    "recurrence_pattern_id INTEGER"
                )
            )


def ensure_runtime_schema_compatibility() -> None:
    """Handle ensure runtime schema compatibility."""
    _ensure_classification_transaction_columns()
    _ensure_import_traceability_transaction_columns()
    _ensure_import_transaction_draft_proposal_columns()


def _log_current_schema() -> None:
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    logger.info("Tables after creation: %s", tables)

    for table in tables:
        columns = [column["name"] for column in inspector.get_columns(table)]
        logger.info("Columns in %s table: %s", table, columns)


def _created_derived_table_needs(
    existing_tables: set[str],
    missing_tables: set[str],
) -> dict[str, bool]:
    if "transactions" not in existing_tables:
        return {}

    return {
        "financial_statistics": "financial_statistics" in missing_tables,
        "category_statistics": "category_statistics" in missing_tables,
        "financial_health": "financial_health" in missing_tables,
        "projection_scenarios": "projection_scenarios" in missing_tables,
    }


def _initialize_derived_data(
    db: Session,
    table_needs: dict[str, bool],
    migration_summary: dict[str, int],
) -> None:
    if not any(table_needs.values()):
        return

    logger.info("Initializing derived data for existing transactions...")
    aggregates_already_refreshed = migration_summary.get("recomputed_aggregates", 0) > 0

    if table_needs["financial_statistics"] and not aggregates_already_refreshed:
        logger.info("Initializing financial statistics...")
        StatisticsService.initialize_statistics(db)
    if table_needs["category_statistics"] and not aggregates_already_refreshed:
        logger.info("Initializing category statistics...")
        StatisticsService.initialize_category_statistics(db)
    if table_needs["financial_health"] and not aggregates_already_refreshed:
        logger.info("Initializing financial health scores...")
        FinancialHealthService.initialize_financial_health(db)
    if table_needs["projection_scenarios"]:
        logger.info("Creating default projection scenarios...")
        ProjectionService.create_default_scenarios(db)

    logger.info("Derived data initialization completed successfully!")


def _run_startup_migrations() -> dict[str, int]:
    ensure_import_session_file_hash_uniqueness(engine, _import_artifact_root())
    with Session(engine) as db:
        migration_summary = migrate_europe_iban_reclassification(db)
        logger.info("Europe IBAN cleanup migration summary: %s", migration_summary)
        return migration_summary


def _create_missing_tables(
    existing_tables: set[str],
    missing_tables: list[str],
) -> None:
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created successfully!")
    _log_current_schema()

    migration_summary = _run_startup_migrations()
    table_needs = _created_derived_table_needs(existing_tables, set(missing_tables))
    with Session(engine) as db:
        _initialize_derived_data(db, table_needs, migration_summary)


def init_database() -> None:
    """Initialize the database and create all tables."""
    logger.info("Initializing database...")

    # Check if database exists and has all tables
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    logger.info("Existing tables: %s", sorted(existing_tables))

    ensure_runtime_schema_compatibility()

    missing_tables = [
        table for table in REQUIRED_TABLE_NAMES if table not in existing_tables
    ]

    if missing_tables:
        logger.info("Creating missing tables: %s", missing_tables)
        try:
            _create_missing_tables(existing_tables, missing_tables)
        except Exception:
            logger.exception("Error creating database tables")
            raise
    else:
        logger.info("All required database tables already exist")
        _run_startup_migrations()


def assert_required_schema() -> None:
    """Fail startup when a recorded database is missing required tables."""
    existing_tables = set(inspect(engine).get_table_names())
    missing_tables = sorted(set(REQUIRED_TABLE_NAMES) - existing_tables)
    if missing_tables:
        missing = ", ".join(missing_tables)
        raise RuntimeError(f"Database schema is missing required tables: {missing}")


def _recreate_tables(*, tables: Sequence[object] | None = None) -> None:
    metadata_tables = cast("Sequence[Table] | None", tables)
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        try:
            Base.metadata.drop_all(bind=connection, tables=metadata_tables)
            Base.metadata.create_all(bind=connection, tables=metadata_tables)
            connection.commit()
        finally:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()


def reset_database(reset_type: str = "all") -> None:
    """Drop all tables and recreate them."""
    logger.info("Resetting database...")
    try:
        if reset_type == "all":
            _recreate_tables()
        elif reset_type == "transactions":
            _recreate_tables(tables=[Transaction.__table__])
        elif reset_type == "statistics":
            _recreate_tables(
                tables=[FinancialStatistics.__table__, CategoryStatistics.__table__]
            )
        elif reset_type == "financial_health":
            _recreate_tables(
                tables=[FinancialHealth.__table__, FinancialRecommendation.__table__]
            )
        elif reset_type == "projections":
            _recreate_tables(
                tables=[
                    ProjectionScenario.__table__,
                    ProjectionParameter.__table__,
                    ProjectionResult.__table__,
                ]
            )
        elif reset_type == "anomalies":
            _recreate_tables(
                tables=[
                    TransactionAnomaly.__table__,
                    AnomalyPattern.__table__,
                    AnomalyRule.__table__,
                ]
            )
        elif reset_type == "imports":
            _recreate_tables(
                tables=[
                    ImportBatchItem.__table__,
                    ImportBatchRun.__table__,
                    ImportIssue.__table__,
                    ImportTransactionDraft.__table__,
                    ImportStatementDraft.__table__,
                    ImportSession.__table__,
                ]
            )
        elif reset_type == "classification":
            with Session(engine) as db:
                db.query(Transaction).update(
                    {
                        Transaction.classification_source: None,
                        Transaction.recurrence_pattern_id: None,
                    },
                    synchronize_session=False,
                )
                db.commit()
            _recreate_tables(
                tables=[
                    ClassificationTurn.__table__,
                    ClassificationSession.__table__,
                    RecurrencePattern.__table__,
                ],
            )
        engine.dispose()
        logger.info("Database reset successfully!")
    except Exception:
        logger.exception("Error resetting database")
        raise
