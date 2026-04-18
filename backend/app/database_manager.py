from sqlalchemy import inspect, text
import logging
from pathlib import Path

from .database import engine, Base
from .config import settings
from .imports.dedupe import ensure_import_session_file_hash_uniqueness
from .migrations.migrate_europe_iban_reclassification import migrate_europe_iban_reclassification
from .models.fx import FXDailyReferenceRate
from .models.classification import ClassificationSession, ClassificationTurn, RecurrencePattern
from .models.transaction import Transaction
from .models.statistics import FinancialStatistics, CategoryStatistics
from .models.financial_health import FinancialHealth, FinancialRecommendation
from .models.financial_projection import ProjectionScenario, ProjectionParameter, ProjectionResult
from .models.anomaly import TransactionAnomaly, AnomalyPattern, AnomalyRule
from .models.imports import (
    ImportBatchItem,
    ImportBatchRun,
    ImportIssue,
    ImportSession,
    ImportStatementDraft,
    ImportTransactionDraft,
)
from .services.statistics_service import StatisticsService
from .services.financial_health_service import FinancialHealthService
from .services.projection_service import ProjectionService
from sqlalchemy.orm import Session

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _import_artifact_root() -> Path:
    return settings.imports_dir


def _ensure_classification_transaction_columns() -> None:
    inspector = inspect(engine)
    if "transactions" not in inspector.get_table_names():
        return

    transaction_columns = {column["name"] for column in inspector.get_columns("transactions")}
    with engine.begin() as conn:
        if "transfer_category" not in transaction_columns:
            conn.execute(text("ALTER TABLE transactions ADD COLUMN transfer_category VARCHAR(50)"))
        if "classification_source" not in transaction_columns:
            conn.execute(text("ALTER TABLE transactions ADD COLUMN classification_source VARCHAR(50)"))
        if "recurrence_pattern_id" not in transaction_columns:
            conn.execute(text("ALTER TABLE transactions ADD COLUMN recurrence_pattern_id INTEGER"))
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

    transaction_columns = {column["name"] for column in inspector.get_columns("transactions")}
    with engine.begin() as conn:
        if "import_session_id" not in transaction_columns:
            conn.execute(text("ALTER TABLE transactions ADD COLUMN import_session_id INTEGER"))
        if "import_source_locator" not in transaction_columns:
            conn.execute(text("ALTER TABLE transactions ADD COLUMN import_source_locator VARCHAR(255)"))
        if "import_source_description" not in transaction_columns:
            conn.execute(text("ALTER TABLE transactions ADD COLUMN import_source_description VARCHAR(500)"))
        if "canonical_description_en" not in transaction_columns:
            conn.execute(text("ALTER TABLE transactions ADD COLUMN canonical_description_en VARCHAR(500)"))
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_transactions_import_session_id ON transactions (import_session_id)")
        )


def _ensure_import_transaction_draft_proposal_columns() -> None:
    inspector = inspect(engine)
    if "import_transaction_drafts" not in inspector.get_table_names():
        return

    transaction_columns = {column["name"] for column in inspector.get_columns("import_transaction_drafts")}
    with engine.begin() as conn:
        if "proposed_transaction_type" not in transaction_columns:
            conn.execute(
                text("ALTER TABLE import_transaction_drafts ADD COLUMN proposed_transaction_type VARCHAR(50)")
            )
        if "proposed_expense_category" not in transaction_columns:
            conn.execute(
                text("ALTER TABLE import_transaction_drafts ADD COLUMN proposed_expense_category VARCHAR(100)")
            )
        if "proposed_income_category" not in transaction_columns:
            conn.execute(
                text("ALTER TABLE import_transaction_drafts ADD COLUMN proposed_income_category VARCHAR(100)")
            )
        if "proposed_transfer_category" not in transaction_columns:
            conn.execute(
                text("ALTER TABLE import_transaction_drafts ADD COLUMN proposed_transfer_category VARCHAR(100)")
            )
        if "classification_source" not in transaction_columns:
            conn.execute(text("ALTER TABLE import_transaction_drafts ADD COLUMN classification_source VARCHAR(50)"))
        if "recurrence_pattern_id" not in transaction_columns:
            conn.execute(text("ALTER TABLE import_transaction_drafts ADD COLUMN recurrence_pattern_id INTEGER"))


def ensure_runtime_schema_compatibility() -> None:
    _ensure_classification_transaction_columns()
    _ensure_import_traceability_transaction_columns()
    _ensure_import_transaction_draft_proposal_columns()

def init_database():
    """Initialize the database and create all tables"""
    logger.info("Initializing database...")
    
    # Check if database exists and has all tables
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()
    logger.info(f"Existing tables: {existing_tables}")

    ensure_runtime_schema_compatibility()

    tables_to_check = [
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
    ]
    missing_tables = [table for table in tables_to_check if table not in existing_tables]

    migration_summary = None

    if missing_tables:
        logger.info(f"Creating missing tables: {missing_tables}")
        try:
            # Create all tables
            Base.metadata.create_all(bind=engine)
            logger.info("Database tables created successfully!")
            
            # Verify tables were created
            inspector = inspect(engine)
            tables = inspector.get_table_names()
            logger.info(f"Tables after creation: {tables}")
            
            # Log columns for each table
            for table in tables:
                columns = [c['name'] for c in inspector.get_columns(table)]
                logger.info(f"Columns in {table} table: {columns}")

            # Initialize derived tables if transactions table already existed and the
            # Europe cleanup pass does not already recompute them.
            need_stats_init = False
            need_category_stats_init = False
            need_financial_health_init = False
            need_projection_init = False
            
            if "transactions" in existing_tables:
                if "financial_statistics" in missing_tables:
                    need_stats_init = True
                if "category_statistics" in missing_tables:
                    need_category_stats_init = True
                if "financial_health" in missing_tables:
                    need_financial_health_init = True
                if "projection_scenarios" in missing_tables:
                    need_projection_init = True
            
            ensure_import_session_file_hash_uniqueness(engine, _import_artifact_root())

            with Session(engine) as db:
                migration_summary = migrate_europe_iban_reclassification(db)
                logger.info("Europe IBAN cleanup migration summary: %s", migration_summary)

                aggregates_already_refreshed = migration_summary.get("recomputed_aggregates", 0) > 0
                if need_stats_init or need_category_stats_init or need_financial_health_init or need_projection_init:
                    logger.info("Initializing derived data for existing transactions...")
                    if need_stats_init and not aggregates_already_refreshed:
                        logger.info("Initializing financial statistics...")
                        StatisticsService.initialize_statistics(db)
                    if need_category_stats_init and not aggregates_already_refreshed:
                        logger.info("Initializing category statistics...")
                        StatisticsService.initialize_category_statistics(db)
                    if need_financial_health_init and not aggregates_already_refreshed:
                        logger.info("Initializing financial health scores...")
                        FinancialHealthService.initialize_financial_health(db)
                    if need_projection_init:
                        logger.info("Creating default projection scenarios...")
                        ProjectionService.create_default_scenarios(db)
                    logger.info("Derived data initialization completed successfully!")
        except Exception as e:
            logger.error(f"Error creating database tables: {str(e)}")
            raise
    else:
        logger.info("All required database tables already exist")
        ensure_import_session_file_hash_uniqueness(engine, _import_artifact_root())
        with Session(engine) as db:
            migration_summary = migrate_europe_iban_reclassification(db)
            logger.info("Europe IBAN cleanup migration summary: %s", migration_summary)


def _recreate_tables(*, tables=None) -> None:
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        try:
            Base.metadata.drop_all(bind=connection, tables=tables)
            Base.metadata.create_all(bind=connection, tables=tables)
            connection.commit()
        finally:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()

def reset_database(reset_type: str = "all"):
    """Drop all tables and recreate them"""
    logger.info("Resetting database...")
    try:
        if reset_type == "all":
            _recreate_tables()
        elif reset_type == "transactions":
            _recreate_tables(tables=[Transaction.__table__])
        elif reset_type == "statistics":
            _recreate_tables(tables=[FinancialStatistics.__table__, CategoryStatistics.__table__])
        elif reset_type == "financial_health":
            _recreate_tables(tables=[FinancialHealth.__table__, FinancialRecommendation.__table__])
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
                tables=[TransactionAnomaly.__table__, AnomalyPattern.__table__, AnomalyRule.__table__]
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
    except Exception as e:
        logger.error(f"Error resetting database: {str(e)}")
        raise
