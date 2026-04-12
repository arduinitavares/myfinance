from sqlalchemy import inspect, text
import logging
from .database import engine, Base
from .models.classification import ClassificationSession, ClassificationTurn, RecurrencePattern
from .models.transaction import Transaction
from .models.statistics import FinancialStatistics, CategoryStatistics
from .models.financial_health import FinancialHealth, FinancialRecommendation
from .models.financial_projection import ProjectionScenario, ProjectionParameter, ProjectionResult
from .models.anomaly import TransactionAnomaly, AnomalyPattern, AnomalyRule
from .models.imports import ImportIssue, ImportSession, ImportStatementDraft, ImportTransactionDraft
from .services.statistics_service import StatisticsService
from .services.financial_health_service import FinancialHealthService
from .services.projection_service import ProjectionService
from sqlalchemy.orm import Session

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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

def init_database():
    """Initialize the database and create all tables"""
    logger.info("Initializing database...")
    
    # Check if database exists and has all tables
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()
    logger.info(f"Existing tables: {existing_tables}")

    _ensure_classification_transaction_columns()
    _ensure_import_traceability_transaction_columns()

    tables_to_check = [
        "transactions",
        "classification_sessions",
        "classification_turns",
        "recurrence_patterns",
        "financial_statistics",
        "category_statistics",
        "financial_health",
        "financial_recommendations",
        "projection_scenarios",
        "projection_parameters",
        "projection_results",
        "transaction_anomalies",
        "anomaly_patterns",
        "anomaly_rules",
        "import_sessions",
        "import_statement_drafts",
        "import_transaction_drafts",
        "import_issues",
    ]
    missing_tables = [table for table in tables_to_check if table not in existing_tables]

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

            # Initialize statistics if transactions table already existed
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
            
            if need_stats_init or need_category_stats_init or need_financial_health_init or need_projection_init:
                logger.info("Initializing statistics and financial health for existing transactions...")
                with Session(engine) as db:
                    if need_stats_init:
                        logger.info("Initializing financial statistics...")
                        StatisticsService.initialize_statistics(db)
                    if need_category_stats_init:
                        logger.info("Initializing category statistics...")
                        StatisticsService.initialize_category_statistics(db)
                    if need_financial_health_init:
                        logger.info("Initializing financial health scores...")
                        FinancialHealthService.initialize_financial_health(db)
                    if need_projection_init:
                        logger.info("Creating default projection scenarios...")
                        ProjectionService.create_default_scenarios(db)
                logger.info("Statistics and financial health initialized successfully!")
            
        except Exception as e:
            logger.error(f"Error creating database tables: {str(e)}")
            raise
    else:
        logger.info("All required database tables already exist")


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
