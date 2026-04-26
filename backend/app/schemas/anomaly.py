"""Module for backend app schemas anomaly."""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from ..models.anomaly import AnomalySeverity, AnomalyStatus, AnomalyType


class AnomalyBase(BaseModel):
    """Represent anomaly base."""

    transaction_id: int
    anomaly_type: AnomalyType
    severity: AnomalySeverity
    anomaly_score: float
    confidence: float
    detection_method: str
    reason: str
    details: str | None = None
    expected_value: float | None = None
    actual_value: float | None = None
    deviation_magnitude: float | None = None


class AnomalyCreate(AnomalyBase):
    """Represent anomaly create."""



class AnomalyUpdate(BaseModel):
    """Represent anomaly update."""

    status: AnomalyStatus | None = None
    review_notes: str | None = None


class Anomaly(AnomalyBase):
    """Represent anomaly."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    status: AnomalyStatus
    detection_timestamp: datetime
    reviewed_at: datetime | None = None
    reviewed_by: str | None = None
    review_notes: str | None = None


class AnomalyWithTransaction(Anomaly):
    """Represent anomaly with transaction."""

    transaction: dict[str, Any] | None = None


class AnomalyPatternBase(BaseModel):
    """Represent anomaly pattern base."""

    pattern_type: str
    pattern_key: str
    mean_value: float | None = None
    std_deviation: float | None = None
    median_value: float | None = None
    percentile_95: float | None = None
    percentile_99: float | None = None
    typical_days: str | None = None
    typical_hours: str | None = None
    avg_frequency_days: float | None = None
    min_frequency_days: float | None = None
    max_frequency_days: float | None = None
    sample_size: int


class AnomalyPatternCreate(AnomalyPatternBase):
    """Represent anomaly pattern create."""



class AnomalyPattern(AnomalyPatternBase):
    """Represent anomaly pattern."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    last_updated: datetime
    created_at: datetime


class AnomalyRuleBase(BaseModel):
    """Represent anomaly rule base."""

    name: str
    description: str | None = None
    rule_type: AnomalyType
    category_filter: str | None = None
    merchant_filter: str | None = None
    amount_threshold: float | None = None
    frequency_threshold: int | None = None
    time_period_days: int = 30
    is_active: bool = True
    severity_override: AnomalySeverity | None = None


class AnomalyRuleCreate(AnomalyRuleBase):
    """Represent anomaly rule create."""



class AnomalyRuleUpdate(BaseModel):
    """Represent anomaly rule update."""

    name: str | None = None
    description: str | None = None
    is_active: bool | None = None
    amount_threshold: float | None = None
    frequency_threshold: int | None = None
    severity_override: AnomalySeverity | None = None


class AnomalyRule(AnomalyRuleBase):
    """Represent anomaly rule."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class AnomalyDetectionRequest(BaseModel):
    """Represent anomaly detection request."""

    transaction_ids: list[int] | None = None
    start_date: date | None = None
    end_date: date | None = None
    force_redetection: bool = False


class AnomalyDetectionResult(BaseModel):
    """Represent anomaly detection result."""

    total_transactions_analyzed: int
    anomalies_detected: int
    anomalies_by_type: dict[str, int]
    anomalies_by_severity: dict[str, int]
    processing_time_seconds: float


class AnomalyStatistics(BaseModel):
    """Represent anomaly statistics."""

    total_anomalies: int
    unreviewed_anomalies: int
    confirmed_anomalies: int
    false_positives: int
    anomalies_by_type: dict[str, int]
    anomalies_by_severity: dict[str, int]
    detection_accuracy: float  # Percentage of confirmed vs total reviewed


class AnomalyPage(BaseModel):
    """Represent anomaly page."""

    model_config = ConfigDict(from_attributes=True)

    items: list[AnomalyWithTransaction]
    total: int
    page: int
    page_size: int
    total_pages: int
