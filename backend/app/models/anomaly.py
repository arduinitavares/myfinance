"""Module for backend app models anomaly."""

import enum
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base

if TYPE_CHECKING:
    from .transaction import Transaction


def utc_now() -> datetime:
    """Return the current UTC datetime."""
    return datetime.now(UTC)


class AnomalyType(enum.Enum):
    """Represent anomaly type."""

    STATISTICAL_OUTLIER = "Statistical Outlier"
    TEMPORAL_ANOMALY = "Temporal Anomaly"
    AMOUNT_ANOMALY = "Amount Anomaly"
    FREQUENCY_ANOMALY = "Frequency Anomaly"
    BEHAVIORAL_ANOMALY = "Behavioral Anomaly"
    MERCHANT_ANOMALY = "Merchant Anomaly"


class AnomalySeverity(enum.Enum):
    """Represent anomaly severity."""

    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"


class AnomalyStatus(enum.Enum):
    """Represent anomaly status."""

    DETECTED = "Detected"
    REVIEWED = "Reviewed"
    CONFIRMED = "Confirmed"
    FALSE_POSITIVE = "False Positive"
    IGNORED = "Ignored"


class TransactionAnomaly(Base):
    """Represent transaction anomaly."""

    __tablename__ = "transaction_anomalies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    transaction_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("transactions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    anomaly_type: Mapped[AnomalyType] = mapped_column(Enum(AnomalyType), nullable=False)
    severity: Mapped[AnomalySeverity] = mapped_column(
        Enum(AnomalySeverity), nullable=False
    )
    status: Mapped[AnomalyStatus] = mapped_column(
        Enum(AnomalyStatus), default=AnomalyStatus.DETECTED, nullable=True
    )

    # Scoring and confidence
    anomaly_score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)

    # Detection details
    detection_method: Mapped[str] = mapped_column(String(100), nullable=False)
    detection_timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, nullable=True
    )

    # Anomaly explanation
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Statistical metrics
    expected_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    deviation_magnitude: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Review information
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationship to transaction
    transaction: Mapped["Transaction"] = relationship(
        "Transaction", backref="anomalies", passive_deletes=True
    )


class AnomalyPattern(Base):
    """Store learned patterns to improve detection accuracy."""

    __tablename__ = "anomaly_patterns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    pattern_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # e.g., "merchant_spending", "category_timing"
    pattern_key: Mapped[str] = mapped_column(String(200), nullable=False)

    # Pattern statistics
    mean_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    std_deviation: Mapped[float | None] = mapped_column(Float, nullable=True)
    median_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    percentile_95: Mapped[float | None] = mapped_column(Float, nullable=True)
    percentile_99: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Temporal patterns
    typical_days: Mapped[str | None] = mapped_column(String(20), nullable=True)
    typical_hours: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Frequency patterns
    avg_frequency_days: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_frequency_days: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_frequency_days: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Pattern metadata
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    last_updated: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, nullable=True
    )


class AnomalyRule(Base):
    """User-defined rules for anomaly detection."""

    __tablename__ = "anomaly_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Rule conditions
    rule_type: Mapped[AnomalyType] = mapped_column(Enum(AnomalyType), nullable=False)
    category_filter: Mapped[str | None] = mapped_column(String(50), nullable=True)
    merchant_filter: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Thresholds
    amount_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    frequency_threshold: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_period_days: Mapped[int] = mapped_column(Integer, default=30, nullable=True)

    # Rule settings
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=True)
    severity_override: Mapped[AnomalySeverity | None] = mapped_column(
        Enum(AnomalySeverity), nullable=True
    )

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, nullable=True
    )
