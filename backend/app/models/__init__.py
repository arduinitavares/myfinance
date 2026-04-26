"""Module for backend app models __init__."""

from ..database import Base
from .anomaly import (
    AnomalyPattern,
    AnomalyRule,
    AnomalySeverity,
    AnomalyStatus,
    AnomalyType,
    TransactionAnomaly,
)
from .classification import (
    ClassificationSession,
    ClassificationSessionStatus,
    ClassificationTurn,
    RecurrencePattern,
)
from .financial_health import FinancialHealth, FinancialRecommendation
from .financial_projection import (
    ProjectionParameter,
    ProjectionResult,
    ProjectionScenario,
)
from .fx import FXDailyReferenceRate
from .imports import (
    ImportBatchItem,
    ImportBatchRun,
    ImportIssue,
    ImportSession,
    ImportStatementDraft,
    ImportTransactionDraft,
)
from .statistics import CategoryStatistics, FinancialStatistics, StatisticsPeriod
from .transaction import (
    ExpenseCategory,
    IncomeCategory,
    Transaction,
    TransactionType,
    TransferCategory,
)

# Export all models
__all__ = [
    "AnomalyPattern",
    "AnomalyRule",
    "AnomalySeverity",
    "AnomalyStatus",
    "AnomalyType",
    "Base",
    "CategoryStatistics",
    "ClassificationSession",
    "ClassificationSessionStatus",
    "ClassificationTurn",
    "ExpenseCategory",
    "FXDailyReferenceRate",
    "FinancialHealth",
    "FinancialRecommendation",
    "FinancialStatistics",
    "ImportBatchItem",
    "ImportBatchRun",
    "ImportIssue",
    "ImportSession",
    "ImportStatementDraft",
    "ImportTransactionDraft",
    "IncomeCategory",
    "ProjectionParameter",
    "ProjectionResult",
    "ProjectionScenario",
    "RecurrencePattern",
    "StatisticsPeriod",
    "Transaction",
    "TransactionAnomaly",
    "TransactionType",
    "TransferCategory",
]
