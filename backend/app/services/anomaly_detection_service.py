"""Module for backend app services anomaly_detection_service."""

import json
import logging
import statistics
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import ClassVar

import numpy as np
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from ..models.anomaly import (
    AnomalySeverity,
    AnomalyStatus,
    AnomalyType,
    TransactionAnomaly,
)
from ..models.transaction import (
    ExpenseCategory,
    Transaction,
    TransactionType,
)

logger: logging.Logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_DAYS: int = 90
HISTORICAL_LOOKBACK_DAYS: int = 365
RECENT_MERCHANT_LOOKBACK_DAYS: int = 30
STATISTICAL_SAMPLE_MINIMUM: int = 10
AMOUNT_SAMPLE_MINIMUM: int = 20
WEEKEND_START_WEEKDAY: int = 5
WEEKEND_ESSENTIAL_AMOUNT_THRESHOLD: int = 100
MERCHANT_FREQUENCY_THRESHOLD: int = 10
EXPECTED_MERCHANT_FREQUENCY: int = 5
NEW_MERCHANT_AMOUNT_THRESHOLD: int = 200
CRITICAL_SEVERITY_MINIMUM: int = 95


class AnomalyDetectionService:
    """Represent anomaly detection service."""

    # Thresholds for anomaly scoring
    Z_SCORE_THRESHOLD = 2.0
    IQR_MULTIPLIER = 1.5
    CONFIDENCE_THRESHOLD = 0.7

    # Severity thresholds (anomaly scores 0-100)
    SEVERITY_THRESHOLDS: ClassVar[dict[AnomalySeverity, tuple[int, int]]] = {
        AnomalySeverity.LOW: (50, 70),
        AnomalySeverity.MEDIUM: (70, 85),
        AnomalySeverity.HIGH: (85, 95),
        AnomalySeverity.CRITICAL: (95, 100),
    }

    @staticmethod
    def detect_anomalies(
        db: Session,
        transaction_ids: list[int] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        force_redetection: bool = False,
    ) -> dict:
        """Detect anomalies in matching transactions."""
        start_time = datetime.now(UTC)
        transactions = AnomalyDetectionService._transactions_for_detection(
            db=db,
            transaction_ids=transaction_ids,
            start_date=start_date,
            end_date=end_date,
        )

        if not transactions:
            return {
                "total_transactions_analyzed": 0,
                "anomalies_detected": 0,
                "anomalies_by_type": {},
                "anomalies_by_severity": {},
                "processing_time_seconds": 0,
            }

        # Update patterns before detection
        AnomalyDetectionService._update_patterns(db, transactions)

        anomalies_detected = 0
        anomalies_by_type = defaultdict(int)
        anomalies_by_severity = defaultdict(int)

        for transaction in transactions:
            if AnomalyDetectionService._skip_existing_anomaly(
                db=db,
                transaction=transaction,
                force_redetection=force_redetection,
            ):
                continue

            detected_anomalies = AnomalyDetectionService._detect_transaction_anomalies(
                db, transaction
            )

            # Save detected anomalies
            for anomaly_data in detected_anomalies:
                # Remove existing anomalies for this transaction if redetecting
                if force_redetection:
                    db.query(TransactionAnomaly).filter(
                        TransactionAnomaly.transaction_id == transaction.id
                    ).delete()

                anomaly = TransactionAnomaly(**anomaly_data)
                db.add(anomaly)

                anomalies_detected += 1
                anomalies_by_type[anomaly_data["anomaly_type"].value] += 1
                anomalies_by_severity[anomaly_data["severity"].value] += 1

        db.commit()

        processing_time = (datetime.now(UTC) - start_time).total_seconds()

        return {
            "total_transactions_analyzed": len(transactions),
            "anomalies_detected": anomalies_detected,
            "anomalies_by_type": dict(anomalies_by_type),
            "anomalies_by_severity": dict(anomalies_by_severity),
            "processing_time_seconds": processing_time,
        }

    @staticmethod
    def _transactions_for_detection(
        *,
        db: Session,
        transaction_ids: list[int] | None,
        start_date: date | None,
        end_date: date | None,
    ) -> list[Transaction]:
        """Return transactions eligible for anomaly detection."""
        query = db.query(Transaction)

        if transaction_ids:
            query = query.filter(Transaction.id.in_(transaction_ids))
        else:
            if start_date:
                query = query.filter(Transaction.transaction_date >= start_date)
            if end_date:
                query = query.filter(Transaction.transaction_date <= end_date)

            # Default to last 90 days if no filters
            if not start_date and not end_date:
                cutoff_date = datetime.now(UTC).date() - timedelta(
                    days=DEFAULT_LOOKBACK_DAYS
                )
                query = query.filter(Transaction.transaction_date >= cutoff_date)

        # Only analyze expense transactions
        query = query.filter(Transaction.transaction_type == TransactionType.EXPENSE)
        return query.all()

    @staticmethod
    def _skip_existing_anomaly(
        *, db: Session, transaction: Transaction, force_redetection: bool
    ) -> bool:
        """Return whether a transaction already has anomaly records."""
        if force_redetection:
            return False
        existing = (
            db.query(TransactionAnomaly)
            .filter(TransactionAnomaly.transaction_id == transaction.id)
            .first()
        )
        return existing is not None

    @staticmethod
    def _detect_transaction_anomalies(
        db: Session, transaction: Transaction
    ) -> list[dict]:
        """Run all anomaly detectors for one transaction."""
        detected_anomalies = []

        stat_anomalies = AnomalyDetectionService._detect_statistical_outliers(
            db, transaction
        )
        detected_anomalies.extend(stat_anomalies)

        temp_anomalies = AnomalyDetectionService._detect_temporal_anomalies(transaction)
        detected_anomalies.extend(temp_anomalies)

        amount_anomalies = AnomalyDetectionService._detect_amount_anomalies(
            db, transaction
        )
        detected_anomalies.extend(amount_anomalies)

        freq_anomalies = AnomalyDetectionService._detect_frequency_anomalies(
            db, transaction
        )
        detected_anomalies.extend(freq_anomalies)

        behav_anomalies = AnomalyDetectionService._detect_behavioral_anomalies(
            db, transaction
        )
        detected_anomalies.extend(behav_anomalies)

        merchant_anomalies = AnomalyDetectionService._detect_merchant_anomalies(
            db, transaction
        )
        detected_anomalies.extend(merchant_anomalies)
        return detected_anomalies

    @staticmethod
    def _detect_statistical_outliers(
        db: Session, transaction: Transaction
    ) -> list[dict]:
        """Detect statistical outliers using Z-score and IQR methods."""
        anomalies = []

        # Only analyze expenses and use expense category
        if transaction.transaction_type != TransactionType.EXPENSE:
            return anomalies

        # Get category for comparison (expenses only)
        category = transaction.expense_category
        if not category:
            return anomalies

        # Get historical expense transactions for same category
        historical = (
            db.query(Transaction)
            .filter(
                and_(
                    Transaction.id != transaction.id,
                    Transaction.transaction_type == TransactionType.EXPENSE,
                    Transaction.expense_category == category,
                    Transaction.transaction_date
                    >= transaction.transaction_date
                    - timedelta(days=HISTORICAL_LOOKBACK_DAYS),
                )
            )
            .all()
        )

        if len(historical) < STATISTICAL_SAMPLE_MINIMUM:
            return anomalies

        amounts = [abs(t.amount) for t in historical]
        mean_amount = statistics.mean(amounts)
        std_amount = statistics.stdev(amounts) if len(amounts) > 1 else 0

        if std_amount == 0:
            return anomalies

        # Z-score analysis
        z_score = abs((abs(transaction.amount) - mean_amount) / std_amount)

        if z_score > AnomalyDetectionService.Z_SCORE_THRESHOLD:
            # Calculate anomaly score (0-100)
            anomaly_score = min(100, (z_score / 4.0) * 100)  # Cap at 100
            confidence = min(1.0, z_score / 4.0)

            severity = AnomalyDetectionService._calculate_severity(anomaly_score)

            anomalies.append(
                {
                    "transaction_id": transaction.id,
                    "anomaly_type": AnomalyType.STATISTICAL_OUTLIER,
                    "severity": severity,
                    "anomaly_score": anomaly_score,
                    "confidence": confidence,
                    "detection_method": "z_score",
                    "reason": (
                        "Transaction amount significantly deviates from "
                        f"historical pattern for {category.value}"
                    ),
                    "details": json.dumps(
                        {
                            "z_score": z_score,
                            "historical_mean": mean_amount,
                            "historical_std": std_amount,
                            "sample_size": len(amounts),
                        }
                    ),
                    "expected_value": mean_amount,
                    "actual_value": abs(transaction.amount),
                    "deviation_magnitude": z_score,
                }
            )

        return anomalies

    @staticmethod
    def _detect_temporal_anomalies(transaction: Transaction) -> list[dict]:
        """Detect temporal anomalies (unusual timing patterns)."""
        anomalies = []

        # Get day of week (0=Monday, 6=Sunday)
        weekday = transaction.transaction_date.weekday()

        # Weekend spending anomaly for certain categories
        essential_categories = [
            cat.value for cat in ExpenseCategory.get_essential_categories()
        ]

        if (
            weekday >= WEEKEND_START_WEEKDAY
            and transaction.transaction_type == TransactionType.EXPENSE
            and transaction.expense_category
            and transaction.expense_category.value in essential_categories
            and abs(transaction.amount) > WEEKEND_ESSENTIAL_AMOUNT_THRESHOLD
        ):
            anomaly_score = 65
            confidence = 0.6

            anomalies.append(
                {
                    "transaction_id": transaction.id,
                    "anomaly_type": AnomalyType.TEMPORAL_ANOMALY,
                    "severity": AnomalyDetectionService._calculate_severity(
                        anomaly_score
                    ),
                    "anomaly_score": anomaly_score,
                    "confidence": confidence,
                    "detection_method": "weekend_essential_spending",
                    "reason": (
                        "Large essential expense "
                        f"({transaction.expense_category.value}) on weekend"
                    ),
                    "details": json.dumps(
                        {
                            "weekday": weekday,
                            "category": transaction.expense_category.value,
                            "amount": abs(transaction.amount),
                        }
                    ),
                    "expected_value": None,
                    "actual_value": abs(transaction.amount),
                    "deviation_magnitude": 1.0,
                }
            )

        return anomalies

    @staticmethod
    def _detect_amount_anomalies(db: Session, transaction: Transaction) -> list[dict]:
        """Detect amount-based anomalies."""
        anomalies = []

        # Very large expense transactions (>95th percentile of historical expenses)
        all_amounts = (
            db.query(Transaction.amount)
            .filter(
                and_(
                    Transaction.transaction_type == TransactionType.EXPENSE,
                    Transaction.transaction_date
                    >= transaction.transaction_date
                    - timedelta(days=HISTORICAL_LOOKBACK_DAYS),
                )
            )
            .all()
        )

        if len(all_amounts) < AMOUNT_SAMPLE_MINIMUM:
            return anomalies

        amounts = [abs(a[0]) for a in all_amounts]
        amounts.sort()

        # Calculate percentiles
        p95_value = np.percentile(amounts, 95)
        p99_value = np.percentile(amounts, 99)

        transaction_amount = abs(transaction.amount)

        if transaction_amount > p99_value:
            anomaly_score = 90
            confidence = 0.85
            severity = AnomalySeverity.HIGH
        elif transaction_amount > p95_value:
            anomaly_score = 75
            confidence = 0.75
            severity = AnomalySeverity.MEDIUM
        else:
            return anomalies

        anomalies.append(
            {
                "transaction_id": transaction.id,
                "anomaly_type": AnomalyType.AMOUNT_ANOMALY,
                "severity": severity,
                "anomaly_score": anomaly_score,
                "confidence": confidence,
                "detection_method": "percentile_analysis",
                "reason": (
                    "Transaction amount in top "
                    f"{'1%' if transaction_amount > p99_value else '5%'} "
                    "of historical transactions"
                ),
                "details": json.dumps(
                    {
                        "percentile_95": p95_value,
                        "percentile_99": p99_value,
                        "sample_size": len(amounts),
                    }
                ),
                "expected_value": p95_value,
                "actual_value": transaction_amount,
                "deviation_magnitude": transaction_amount / p95_value,
            }
        )

        return anomalies

    @staticmethod
    def _detect_frequency_anomalies(
        db: Session, transaction: Transaction
    ) -> list[dict]:
        """Detect frequency-based anomalies."""
        anomalies = []

        # Only consider expenses
        if transaction.transaction_type != TransactionType.EXPENSE:
            return anomalies

        if (
            not transaction.counterparty_account
            or not transaction.counterparty_account.strip()
        ):
            return anomalies

        # Check transaction frequency for this merchant account (expenses only)
        merchant_transactions = (
            db.query(Transaction)
            .filter(
                and_(
                    Transaction.counterparty_account
                    == transaction.counterparty_account,
                    Transaction.transaction_type == TransactionType.EXPENSE,
                    Transaction.transaction_date
                    >= transaction.transaction_date
                    - timedelta(days=RECENT_MERCHANT_LOOKBACK_DAYS),
                    Transaction.id != transaction.id,
                )
            )
            .count()
        )

        # If frequency exceeds normal merchant usage in the lookback window.
        if merchant_transactions > MERCHANT_FREQUENCY_THRESHOLD:
            anomaly_score = 70
            confidence = 0.7

            anomalies.append(
                {
                    "transaction_id": transaction.id,
                    "anomaly_type": AnomalyType.FREQUENCY_ANOMALY,
                    "severity": AnomalyDetectionService._calculate_severity(
                        anomaly_score
                    ),
                    "anomaly_score": anomaly_score,
                    "confidence": confidence,
                    "detection_method": "merchant_frequency",
                    "reason": (
                        "High frequency of transactions with "
                        f"{transaction.counterparty_account}"
                    ),
                    "details": json.dumps(
                        {
                            "merchant_account": transaction.counterparty_account,
                            "frequency_30_days": merchant_transactions + 1,
                        }
                    ),
                    "expected_value": EXPECTED_MERCHANT_FREQUENCY,
                    "actual_value": merchant_transactions + 1,
                    "deviation_magnitude": (merchant_transactions + 1)
                    / EXPECTED_MERCHANT_FREQUENCY,
                }
            )

        return anomalies

    @staticmethod
    def _detect_behavioral_anomalies(
        db: Session, transaction: Transaction
    ) -> list[dict]:
        """Detect behavioral pattern anomalies."""
        anomalies = []

        # Only analyze behavioral anomalies for expenses and expense categories
        if transaction.transaction_type != TransactionType.EXPENSE:
            return anomalies

        category = transaction.expense_category
        if not category:
            return anomalies

        # Check if user has used this expense category before (expenses only)
        category_usage = (
            db.query(Transaction)
            .filter(
                and_(
                    Transaction.expense_category == category,
                    Transaction.transaction_type == TransactionType.EXPENSE,
                    Transaction.id != transaction.id,
                )
            )
            .count()
        )

        # New category usage
        if category_usage == 0:
            anomaly_score = 60
            confidence = 0.6

            anomalies.append(
                {
                    "transaction_id": transaction.id,
                    "anomaly_type": AnomalyType.BEHAVIORAL_ANOMALY,
                    "severity": AnomalyDetectionService._calculate_severity(
                        anomaly_score
                    ),
                    "anomaly_score": anomaly_score,
                    "confidence": confidence,
                    "detection_method": "new_category_usage",
                    "reason": f"First transaction in category: {category.value}",
                    "details": json.dumps(
                        {"category": category.value, "first_usage": True}
                    ),
                    "expected_value": None,
                    "actual_value": abs(transaction.amount),
                    "deviation_magnitude": 1.0,
                }
            )

        return anomalies

    @staticmethod
    def _detect_merchant_anomalies(db: Session, transaction: Transaction) -> list[dict]:
        """Detect merchant-related anomalies."""
        anomalies = []

        # Only consider expenses
        if transaction.transaction_type != TransactionType.EXPENSE:
            return anomalies

        if (
            not transaction.counterparty_account
            or not transaction.counterparty_account.strip()
        ):
            return anomalies

        # Check if this is a new merchant account (expenses only)
        merchant_history = (
            db.query(Transaction)
            .filter(
                and_(
                    Transaction.counterparty_account
                    == transaction.counterparty_account,
                    Transaction.transaction_type == TransactionType.EXPENSE,
                    Transaction.id != transaction.id,
                )
            )
            .count()
        )

        # New merchant account with large amount
        if (
            merchant_history == 0
            and abs(transaction.amount) > NEW_MERCHANT_AMOUNT_THRESHOLD
        ):
            anomaly_score = 75
            confidence = 0.8

            anomalies.append(
                {
                    "transaction_id": transaction.id,
                    "anomaly_type": AnomalyType.MERCHANT_ANOMALY,
                    "severity": AnomalyDetectionService._calculate_severity(
                        anomaly_score
                    ),
                    "anomaly_score": anomaly_score,
                    "confidence": confidence,
                    "detection_method": "new_merchant_large_amount",
                    "reason": (
                        "First transaction with new merchant account: "
                        f"{transaction.counterparty_account}"
                    ),
                    "details": json.dumps(
                        {
                            "merchant_account": transaction.counterparty_account,
                            "first_transaction": True,
                            "amount": abs(transaction.amount),
                        }
                    ),
                    "expected_value": None,
                    "actual_value": abs(transaction.amount),
                    "deviation_magnitude": 1.0,
                }
            )

        return anomalies

    @staticmethod
    def _calculate_severity(anomaly_score: float) -> AnomalySeverity:
        """Calculate severity based on anomaly score."""
        for severity, (
            min_score,
            max_score,
        ) in AnomalyDetectionService.SEVERITY_THRESHOLDS.items():
            if min_score <= anomaly_score < max_score:
                return severity
        return (
            AnomalySeverity.CRITICAL
            if anomaly_score >= CRITICAL_SEVERITY_MINIMUM
            else AnomalySeverity.LOW
        )

    @staticmethod
    def _update_patterns(db: Session, transactions: list[Transaction]) -> None:
        """Update anomaly patterns based on transaction data."""
        # This would update the AnomalyPattern table with learned patterns
        # Implementation can be expanded based on needs

    @staticmethod
    def get_anomaly_statistics(db: Session) -> dict:
        """Get overall anomaly statistics."""
        total = db.query(TransactionAnomaly).count()
        unreviewed = (
            db.query(TransactionAnomaly)
            .filter(TransactionAnomaly.status == AnomalyStatus.DETECTED)
            .count()
        )
        confirmed = (
            db.query(TransactionAnomaly)
            .filter(TransactionAnomaly.status == AnomalyStatus.CONFIRMED)
            .count()
        )
        false_positives = (
            db.query(TransactionAnomaly)
            .filter(TransactionAnomaly.status == AnomalyStatus.FALSE_POSITIVE)
            .count()
        )

        # Count by type
        type_counts = (
            db.query(TransactionAnomaly.anomaly_type, func.count(TransactionAnomaly.id))
            .group_by(TransactionAnomaly.anomaly_type)
            .all()
        )

        # Count by severity
        severity_counts = (
            db.query(TransactionAnomaly.severity, func.count(TransactionAnomaly.id))
            .group_by(TransactionAnomaly.severity)
            .all()
        )

        # Calculate accuracy
        reviewed_total = confirmed + false_positives
        accuracy = (confirmed / reviewed_total * 100) if reviewed_total > 0 else 0

        return {
            "total_anomalies": total,
            "unreviewed_anomalies": unreviewed,
            "confirmed_anomalies": confirmed,
            "false_positives": false_positives,
            "anomalies_by_type": {t.value: c for t, c in type_counts},
            "anomalies_by_severity": {s.value: c for s, c in severity_counts},
            "detection_accuracy": accuracy,
        }

    @staticmethod
    def update_anomaly_status(
        db: Session,
        anomaly_id: int,
        status: AnomalyStatus,
        review_notes: str | None = None,
    ) -> TransactionAnomaly:
        """Update anomaly review status."""
        anomaly = (
            db.query(TransactionAnomaly)
            .filter(TransactionAnomaly.id == anomaly_id)
            .first()
        )

        if not anomaly:
            msg = "Anomaly not found"
            raise ValueError(msg)

        anomaly.status = status
        anomaly.reviewed_at = datetime.now(UTC)
        anomaly.review_notes = review_notes

        db.commit()
        db.refresh(anomaly)

        return anomaly
