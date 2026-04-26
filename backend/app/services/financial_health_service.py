"""Module for backend app services financial_health_service."""

import calendar
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import ClassVar

from dateutil.relativedelta import relativedelta
from sqlalchemy import desc, extract, func, text
from sqlalchemy.orm import Session

from ..models.financial_health import FinancialHealth, FinancialRecommendation
from ..models.statistics import (
    CategoryStatistics,
    FinancialStatistics,
    StatisticsPeriod,
)
from ..models.transaction import ExpenseCategory, Transaction, TransactionType

# Set up logging
logging.basicConfig(level=logging.INFO)
logger: logging.Logger = logging.getLogger(__name__)

HEALTH_SCORE_WEIGHTS: dict[str, float] = {
    "savings_rate": 0.20,
    "expense_ratio": 0.15,
    "budget_adherence": 0.10,
    "debt_to_income": 0.15,
    "emergency_fund": 0.15,
    "investment_rate": 0.15,
    "spending_stability": 0.10,
}
DEFAULT_MIDDLE_SCORE: float = 50.0
DEFAULT_MIDDLE_RATIO: float = 0.5
LOOKBACK_QUARTER_DAYS: int = 90
LOOKBACK_HALF_YEAR_DAYS: int = 180
MIN_SPENDING_STABILITY_MONTHS: int = 3
MAX_EMERGENCY_FUND_MONTHS: int = 12
LOW_SCORE_THRESHOLD: float = 40.0
HIGH_DEBT_TO_INCOME_THRESHOLD: float = 0.4
LOW_EMERGENCY_FUND_MONTHS: float = 1.0
STARTER_EMERGENCY_FUND_EUR: int = 1000
LOW_INVESTMENT_RATE_THRESHOLD: float = 0.05
TARGET_INVESTMENT_RATE_THRESHOLD: float = 0.10
GENERAL_RECOMMENDATION_MINIMUM: int = 3
RECOMMENDATION_LIMIT: int = 5
SCORE_RANGES: dict[str, tuple[int, int]] = {
    "excellent": (80, 100),
    "good": (60, 80),
    "average": (40, 60),
    "poor": (20, 40),
    "critical": (0, 20),
}
NEXT_SCORE_CATEGORY: dict[str, str] = {
    "good": "excellent",
    "average": "good",
    "poor": "average",
    "critical": "poor",
}

type RecommendationPayload = dict[str, object]


def _today() -> date:
    """Return the current UTC date."""
    return datetime.now(UTC).date()


@dataclass(frozen=True)
class HealthScoreComponents:
    """Scores and raw values used to persist financial health."""

    savings_rate_score: float
    expense_ratio_score: float
    budget_adherence_score: float
    debt_to_income_score: float
    emergency_fund_score: float
    spending_stability_score: float
    investment_rate_score: float
    savings_rate: float
    expense_ratio: float
    budget_adherence: float
    debt_to_income: float
    emergency_fund_months: float
    spending_stability: float
    investment_rate: float


@dataclass(frozen=True)
class RecommendationContext:
    """Values needed to generate financial health recommendations."""

    savings_rate_score: float
    expense_ratio_score: float
    budget_adherence_score: float
    debt_to_income_score: float
    emergency_fund_score: float
    spending_stability_score: float
    investment_rate_score: float
    savings_rate: float
    expense_ratio: float
    debt_to_income: float
    emergency_fund_months: float
    investment_rate: float


class FinancialHealthService:
    """Service for calculating and managing financial health metrics."""

    # Thresholds for scoring components (these could be made configurable)
    THRESHOLDS: ClassVar[dict[str, dict[str, float]]] = {
        "savings_rate": {
            "excellent": 0.20,  # 20% or more is excellent
            "good": 0.15,  # 15-20% is good
            "average": 0.10,  # 10-15% is average
            "poor": 0.05,  # 5-10% is poor
            "critical": 0.0,  # Less than 5% is critical
        },
        "investment_rate": {
            "excellent": 0.15,  # 15% or more is excellent
            "good": 0.10,  # 10-15% is good
            "average": 0.05,  # 5-10% is average
            "poor": 0.02,  # 2-5% is poor
            "critical": 0.0,  # Less than 2% is critical
        },
        "spending_stability": {
            "excellent": 0.90,  # Very stable (less than 10% variation)
            "good": 0.80,  # Stable (10-20% variation)
            "average": 0.70,  # Somewhat stable (20-30% variation)
            "poor": 0.50,  # Unstable (30-50% variation)
            "critical": 0.0,  # Very unstable (more than 50% variation)
        },
        "budget_adherence": {
            "excellent": 0.90,  # Less than 10% deviation
            "good": 0.80,  # 10-20% deviation
            "average": 0.70,  # 20-30% deviation
            "poor": 0.50,  # 30-50% deviation
            "critical": 0.0,  # More than 50% deviation
        },
        "expense_ratio": {
            "excellent": 0.60,  # 60% or less is excellent
            "good": 0.70,  # 60-70% is good
            "average": 0.80,  # 70-80% is average
            "poor": 0.90,  # 80-90% is poor
            "critical": 1.0,  # More than 90% is critical
        },
        "emergency_fund": {
            "excellent": 6.0,  # 6+ months is excellent
            "good": 4.0,  # 4-6 months is good
            "average": 3.0,  # 3-4 months is average
            "poor": 1.0,  # 1-3 months is poor
            "critical": 0.0,  # Less than 1 month is critical
        },
        "debt_to_income": {
            "excellent": 0.20,  # Less than 20% is excellent
            "good": 0.30,  # 20-30% is good
            "average": 0.36,  # 30-36% is average
            "poor": 0.43,  # 36-43% is poor
            "critical": 0.50,  # More than 43% is critical
        },
    }

    @staticmethod
    def calculate_health_score(
        db: Session,
        target_date: date | None = None,
        force: bool = False,
        *,
        commit: bool = True,
    ) -> FinancialHealth:
        """Calculate the financial health score for a given date.

        Args:
            db: Database session
            target_date: The date to calculate the score for (defaults to today)
            force: If True, recalculate even if a score already exists for this month

        Returns:
            The financial health score object
        """
        target_date = target_date or _today()
        last_day = FinancialHealthService._month_end(target_date)
        existing_score = FinancialHealthService._existing_health_score(db, target_date)

        if existing_score and not force:
            return existing_score

        if existing_score and force:
            db.delete(existing_score)
            db.flush()

        monthly_stats = FinancialHealthService._monthly_statistics(db, target_date)

        if not monthly_stats:
            return FinancialHealthService._create_empty_health_score(
                db=db,
                last_day=last_day,
                target_date=target_date,
                commit=commit,
            )

        components = FinancialHealthService._calculate_components(
            db, target_date, monthly_stats
        )
        recommendations = FinancialHealthService._generate_recommendations(
            FinancialHealthService._recommendation_context(components)
        )
        health_score = FinancialHealthService._build_health_score(
            last_day=last_day,
            components=components,
            recommendations=recommendations,
        )

        db.add(health_score)
        if commit:
            db.commit()
        else:
            db.flush()
        db.refresh(health_score)

        # Clear existing recommendations for this month if we're recalculating
        if force:
            FinancialHealthService._delete_month_recommendations(db, last_day)

        FinancialHealthService._add_recommendation_records(
            db=db,
            last_day=last_day,
            recommendations=recommendations,
        )

        # Commit the recommendations
        if commit:
            db.commit()
        else:
            db.flush()

        return health_score

    @staticmethod
    def _month_end(target_date: date) -> date:
        return target_date.replace(
            day=calendar.monthrange(target_date.year, target_date.month)[1]
        )

    @staticmethod
    def _existing_health_score(
        db: Session, target_date: date
    ) -> FinancialHealth | None:
        return (
            db.query(FinancialHealth)
            .filter(
                extract("year", FinancialHealth.date) == target_date.year,
                extract("month", FinancialHealth.date) == target_date.month,
            )
            .first()
        )

    @staticmethod
    def _monthly_statistics(
        db: Session, target_date: date
    ) -> FinancialStatistics | None:
        return (
            db.query(FinancialStatistics)
            .filter(
                FinancialStatistics.period == StatisticsPeriod.MONTHLY,
                extract("year", FinancialStatistics.date) == target_date.year,
                extract("month", FinancialStatistics.date) == target_date.month,
            )
            .first()
        )

    @staticmethod
    def _create_empty_health_score(
        *,
        db: Session,
        last_day: date,
        target_date: date,
        commit: bool,
    ) -> FinancialHealth:
        logger.warning(
            "No monthly statistics found for %s. Creating empty health score.",
            target_date,
        )
        health_score = FinancialHealth(
            date=last_day,
            overall_score=0,
            savings_rate_score=0,
            expense_ratio_score=0,
            budget_adherence_score=0,
            debt_to_income_score=0,
            emergency_fund_score=0,
            spending_stability_score=0,
            savings_rate=0,
            expense_ratio=0,
            budget_adherence=0,
            debt_to_income=0,
            emergency_fund_months=0,
            spending_stability=0,
            recommendations=[],
        )
        db.add(health_score)
        if commit:
            db.commit()
        else:
            db.flush()
        db.refresh(health_score)
        return health_score

    @staticmethod
    def _calculate_components(
        db: Session,
        target_date: date,
        monthly_stats: FinancialStatistics,
    ) -> HealthScoreComponents:
        savings_rate = monthly_stats.savings_rate / 100
        savings_rate_score = FinancialHealthService._score_component(
            savings_rate,
            FinancialHealthService.THRESHOLDS["savings_rate"],
            higher_is_better=True,
        )
        expense_ratio = (
            monthly_stats.period_expenses / monthly_stats.period_income
            if monthly_stats.period_income > 0
            else 1.0
        )
        expense_ratio_score = FinancialHealthService._score_component(
            expense_ratio,
            FinancialHealthService.THRESHOLDS["expense_ratio"],
            higher_is_better=False,
        )
        budget_adherence_score, budget_adherence = (
            FinancialHealthService._calculate_budget_adherence(db, target_date)
        )
        debt_to_income_score, debt_to_income = (
            FinancialHealthService._calculate_debt_to_income(db, target_date)
        )
        emergency_fund_score, emergency_fund_months = (
            FinancialHealthService._calculate_emergency_fund(db, target_date)
        )
        spending_stability_score, spending_stability = (
            FinancialHealthService._calculate_spending_stability(db, target_date)
        )
        investment_rate_score, investment_rate = (
            FinancialHealthService._calculate_investment_rate(db, target_date)
        )
        return HealthScoreComponents(
            savings_rate_score=savings_rate_score,
            expense_ratio_score=expense_ratio_score,
            budget_adherence_score=budget_adherence_score,
            debt_to_income_score=debt_to_income_score,
            emergency_fund_score=emergency_fund_score,
            spending_stability_score=spending_stability_score,
            investment_rate_score=investment_rate_score,
            savings_rate=savings_rate,
            expense_ratio=expense_ratio,
            budget_adherence=budget_adherence,
            debt_to_income=debt_to_income,
            emergency_fund_months=emergency_fund_months,
            spending_stability=spending_stability,
            investment_rate=investment_rate,
        )

    @staticmethod
    def _overall_score(components: HealthScoreComponents) -> float:
        return (
            components.savings_rate_score * HEALTH_SCORE_WEIGHTS["savings_rate"]
            + components.expense_ratio_score * HEALTH_SCORE_WEIGHTS["expense_ratio"]
            + components.budget_adherence_score
            * HEALTH_SCORE_WEIGHTS["budget_adherence"]
            + components.debt_to_income_score * HEALTH_SCORE_WEIGHTS["debt_to_income"]
            + components.emergency_fund_score * HEALTH_SCORE_WEIGHTS["emergency_fund"]
            + components.investment_rate_score * HEALTH_SCORE_WEIGHTS["investment_rate"]
            + components.spending_stability_score
            * HEALTH_SCORE_WEIGHTS["spending_stability"]
        )

    @staticmethod
    def _recommendation_context(
        components: HealthScoreComponents,
    ) -> RecommendationContext:
        return RecommendationContext(
            savings_rate_score=components.savings_rate_score,
            expense_ratio_score=components.expense_ratio_score,
            budget_adherence_score=components.budget_adherence_score,
            debt_to_income_score=components.debt_to_income_score,
            emergency_fund_score=components.emergency_fund_score,
            spending_stability_score=components.spending_stability_score,
            investment_rate_score=components.investment_rate_score,
            savings_rate=components.savings_rate,
            expense_ratio=components.expense_ratio,
            debt_to_income=components.debt_to_income,
            emergency_fund_months=components.emergency_fund_months,
            investment_rate=components.investment_rate,
        )

    @staticmethod
    def _build_health_score(
        *,
        last_day: date,
        components: HealthScoreComponents,
        recommendations: list[RecommendationPayload],
    ) -> FinancialHealth:
        return FinancialHealth(
            date=last_day,
            overall_score=FinancialHealthService._overall_score(components),
            savings_rate_score=components.savings_rate_score,
            expense_ratio_score=components.expense_ratio_score,
            budget_adherence_score=components.budget_adherence_score,
            debt_to_income_score=components.debt_to_income_score,
            emergency_fund_score=components.emergency_fund_score,
            spending_stability_score=components.spending_stability_score,
            investment_rate_score=components.investment_rate_score,
            savings_rate=components.savings_rate,
            expense_ratio=components.expense_ratio,
            budget_adherence=components.budget_adherence,
            debt_to_income=components.debt_to_income,
            emergency_fund_months=components.emergency_fund_months,
            spending_stability=components.spending_stability,
            investment_rate=components.investment_rate,
            recommendations=recommendations,
        )

    @staticmethod
    def _delete_month_recommendations(db: Session, last_day: date) -> None:
        month_start = last_day.replace(day=1)
        db.query(FinancialRecommendation).filter(
            FinancialRecommendation.date_created >= month_start,
            FinancialRecommendation.date_created <= last_day,
        ).delete()
        db.flush()

    @staticmethod
    def _add_recommendation_records(
        *,
        db: Session,
        last_day: date,
        recommendations: list[RecommendationPayload],
    ) -> None:
        for rec_data in recommendations:
            recommendation = FinancialRecommendation(
                title=str(rec_data["title"]),
                description=str(rec_data["description"]),
                category=str(rec_data["category"]),
                impact_area=str(rec_data["impact_area"]),
                priority=FinancialHealthService._payload_int(rec_data, "priority"),
                estimated_score_improvement=FinancialHealthService._payload_float(
                    rec_data,
                    "estimated_score_improvement",
                ),
                date_created=last_day,
                is_completed=False,
                date_completed=None,
            )
            db.add(recommendation)

    @staticmethod
    def _payload_int(payload: RecommendationPayload, key: str) -> int:
        value = payload[key]
        if isinstance(value, int):
            return value
        if isinstance(value, float | str):
            return int(value)
        msg = "Recommendation payload field must be convertible to int."
        raise TypeError(msg)

    @staticmethod
    def _payload_float(payload: RecommendationPayload, key: str) -> float:
        value = payload[key]
        if isinstance(value, int | float | str):
            return float(value)
        msg = "Recommendation payload field must be convertible to float."
        raise TypeError(msg)

    @staticmethod
    def get_health_history(db: Session, months: int = 12) -> dict:
        """Get historical health scores for the specified number of months."""
        latest_transaction = (
            db.query(Transaction).order_by(Transaction.transaction_date.desc()).first()
        )
        if latest_transaction:
            latest_date = latest_transaction.transaction_date
        else:
            latest_date = _today()

        start_date = latest_date.replace(
            day=calendar.monthrange(latest_date.year, latest_date.month)[1]
        ) - relativedelta(months=months)
        start_date = start_date.replace(
            day=calendar.monthrange(start_date.year, start_date.month)[1]
        )

        health_scores = (
            db.query(FinancialHealth)
            .filter(FinancialHealth.date > start_date)
            .order_by(FinancialHealth.date)
            .all()
        )

        history = {
            "dates": [],
            "overall_scores": [],
            "savings_rate_scores": [],
            "expense_ratio_scores": [],
            "budget_adherence_scores": [],
            "debt_to_income_scores": [],
            "emergency_fund_scores": [],
            "spending_stability_scores": [],
            "investment_rate_scores": [],
        }

        for score in health_scores:
            history["dates"].append(score.date)
            history["overall_scores"].append(score.overall_score)
            history["savings_rate_scores"].append(score.savings_rate_score)
            history["expense_ratio_scores"].append(score.expense_ratio_score)
            history["budget_adherence_scores"].append(score.budget_adherence_score)
            history["debt_to_income_scores"].append(score.debt_to_income_score)
            history["emergency_fund_scores"].append(score.emergency_fund_score)
            history["spending_stability_scores"].append(score.spending_stability_score)
            history["investment_rate_scores"].append(score.investment_rate_score)

        return history

    @staticmethod
    def get_recommendations(
        db: Session, active_only: bool = True
    ) -> list[FinancialRecommendation]:
        """Get active recommendations sorted by priority."""
        query = db.query(FinancialRecommendation)

        if active_only:
            query = query.filter(FinancialRecommendation.is_completed.is_(False))

        return query.order_by(desc(FinancialRecommendation.priority)).all()

    @staticmethod
    def update_recommendation(
        db: Session, recommendation_id: int, is_completed: bool
    ) -> FinancialRecommendation | None:
        """Mark a recommendation as completed or not completed."""
        recommendation = (
            db.query(FinancialRecommendation)
            .filter(FinancialRecommendation.id == recommendation_id)
            .first()
        )

        if not recommendation:
            return None

        recommendation.is_completed = is_completed
        recommendation.date_completed = _today() if is_completed else None

        db.commit()
        db.refresh(recommendation)

        return recommendation

    @staticmethod
    def initialize_financial_health(db: Session, *, commit: bool = True) -> None:
        """Initialize health scores for historical months with transactions."""
        try:
            logger.info(
                "Initializing financial health scores for all historical data..."
            )
            # Lock the database to prevent concurrent initialization writes.
            if commit:
                db.execute(text("BEGIN"))

            # Clear existing financial health scores
            db.query(FinancialHealth).delete()
            db.flush()

            # Get all unique months from transactions
            months = (
                db.query(
                    extract("year", Transaction.transaction_date).label("year"),
                    extract("month", Transaction.transaction_date).label("month"),
                )
                .distinct()
                .all()
            )

            if not months:
                logger.info(
                    "No transaction data found for financial health initialization"
                )
                if commit:
                    db.commit()
                else:
                    db.flush()
                return

            logger.info("Found %s months with transaction data", len(months))

            # Calculate health scores for each month
            for year, month in months:
                # Set day to the last day of the month
                last_day = date(
                    year=int(year),
                    month=int(month),
                    day=calendar.monthrange(int(year), int(month))[1],
                )

                logger.info("Calculating financial health score for %s", last_day)

                try:
                    # Calculate health score for this month
                    # Force calculation even if statistics are incomplete.
                    FinancialHealthService.calculate_health_score(
                        db,
                        last_day,
                        force=True,
                        commit=commit,
                    )
                except Exception as e:
                    if not commit:
                        raise
                    logger.warning(
                        "Error calculating health score for %s: %s", last_day, e
                    )
                    # Continue with other months even if one fails
                    continue

            if commit:
                db.commit()
            else:
                db.flush()
            logger.info("Financial health initialization completed successfully")
        except Exception:
            if commit:
                db.rollback()
            logger.exception("Error initializing financial health scores")
            raise

    @staticmethod
    def _score_component(
        value: float, thresholds: dict[str, float], higher_is_better: bool
    ) -> float:
        """Convert a raw metric to a 0-100 score based on thresholds."""
        category = FinancialHealthService._component_category(
            value=value,
            thresholds=thresholds,
            higher_is_better=higher_is_better,
        )
        low_score, high_score = SCORE_RANGES[category]

        if category == "excellent":
            return high_score - (high_score - low_score) * DEFAULT_MIDDLE_RATIO
        if category == "critical":
            return low_score

        position = FinancialHealthService._component_position(
            value=value,
            thresholds=thresholds,
            category=category,
            higher_is_better=higher_is_better,
        )
        return low_score + position * (high_score - low_score)

    @staticmethod
    def _component_category(
        *,
        value: float,
        thresholds: dict[str, float],
        higher_is_better: bool,
    ) -> str:
        categories = ("excellent", "good", "average", "poor")
        if higher_is_better:
            for category in categories:
                if value >= thresholds[category]:
                    return category
            return "critical"

        for category in categories:
            if value <= thresholds[category]:
                return category
        return "critical"

    @staticmethod
    def _component_position(
        *,
        value: float,
        thresholds: dict[str, float],
        category: str,
        higher_is_better: bool,
    ) -> float:
        next_category = NEXT_SCORE_CATEGORY[category]
        if higher_is_better:
            lower_bound = thresholds[category]
            upper_bound = thresholds[next_category]
            position = FinancialHealthService._safe_ratio(
                value - lower_bound, upper_bound - lower_bound
            )
        else:
            upper_bound = thresholds[category]
            lower_bound = thresholds[next_category]
            position = FinancialHealthService._safe_ratio(
                upper_bound - value, upper_bound - lower_bound
            )
        return max(0, min(1, position))

    @staticmethod
    def _safe_ratio(numerator: float, denominator: float) -> float:
        if denominator == 0:
            return DEFAULT_MIDDLE_RATIO
        return numerator / denominator

    @staticmethod
    def _calculate_budget_adherence(
        db: Session, target_date: date
    ) -> tuple[float, float]:
        """Calculate budget adherence based on current versus historical spend.

        The score measures how well spending stays within
        historical averages for each category.
        """
        month_start = target_date.replace(day=1)
        month_expenses = FinancialHealthService._month_expenses(
            db=db,
            month_start=month_start,
            month_end=FinancialHealthService._month_end(target_date),
        )
        if not month_expenses:
            return DEFAULT_MIDDLE_SCORE, DEFAULT_MIDDLE_RATIO

        category_averages = FinancialHealthService._category_spending_averages(
            db, month_start
        )
        if not category_averages:
            return DEFAULT_MIDDLE_SCORE, DEFAULT_MIDDLE_RATIO

        current_spending = FinancialHealthService._current_spending_by_category(
            month_expenses
        )
        deviations = FinancialHealthService._spending_deviations(
            current_spending=current_spending,
            category_averages=category_averages,
        )
        if not deviations:
            return DEFAULT_MIDDLE_SCORE, DEFAULT_MIDDLE_RATIO

        avg_deviation = sum(deviations) / len(deviations)
        adherence = max(0, 1 - avg_deviation)
        adherence_score = FinancialHealthService._score_component(
            adherence,
            FinancialHealthService.THRESHOLDS["budget_adherence"],
            higher_is_better=True,
        )

        return adherence_score, adherence

    @staticmethod
    def _month_expenses(
        *,
        db: Session,
        month_start: date,
        month_end: date,
    ) -> list[Transaction]:
        return (
            db.query(Transaction)
            .filter(
                Transaction.transaction_type == TransactionType.EXPENSE,
                Transaction.transaction_date >= month_start,
                Transaction.transaction_date <= month_end,
            )
            .all()
        )

    @staticmethod
    def _category_spending_averages(db: Session, month_start: date) -> dict[str, float]:
        category_stats = (
            db.query(CategoryStatistics)
            .filter(
                CategoryStatistics.transaction_type == TransactionType.EXPENSE,
                CategoryStatistics.period == StatisticsPeriod.MONTHLY,
                CategoryStatistics.date
                >= month_start - timedelta(days=LOOKBACK_QUARTER_DAYS),
                CategoryStatistics.date < month_start,
            )
            .all()
        )
        category_amounts: dict[str, list[float]] = {}
        for stat in category_stats:
            category_amounts.setdefault(stat.category_name, []).append(
                stat.period_amount
            )
        return {
            category: sum(amounts) / len(amounts)
            for category, amounts in category_amounts.items()
            if amounts
        }

    @staticmethod
    def _current_spending_by_category(
        month_expenses: list[Transaction],
    ) -> dict[str, float]:
        current_spending: dict[str, float] = {}
        for expense in month_expenses:
            category = (
                expense.expense_category.value if expense.expense_category else "Others"
            )
            current_spending[category] = current_spending.get(category, 0.0) + abs(
                expense.amount
            )
        return current_spending

    @staticmethod
    def _spending_deviations(
        *,
        current_spending: dict[str, float],
        category_averages: dict[str, float],
    ) -> list[float]:
        deviations: list[float] = []
        for category, amount in current_spending.items():
            average = category_averages.get(category, amount)
            if average > 0:
                deviations.append(abs(amount - average) / average)
        return deviations

    @staticmethod
    def _calculate_debt_to_income(
        db: Session, target_date: date
    ) -> tuple[float, float]:
        """
        Calculate debt-to-income ratio score.

        Returns:
            Tuple of (score, debt_to_income_ratio)
        """
        # Simplified approach based on transactions with the debt category.
        month_start = target_date.replace(day=1)
        month_end = target_date.replace(
            day=calendar.monthrange(target_date.year, target_date.month)[1]
        )

        # Get all debt payments for the month
        debt_payments = (
            db.query(func.sum(Transaction.amount))
            .filter(
                Transaction.transaction_type == TransactionType.EXPENSE,
                Transaction.expense_category == ExpenseCategory.DEBT,
                Transaction.transaction_date >= month_start,
                Transaction.transaction_date <= month_end,
            )
            .scalar()
            or 0
        )

        # Get total income for the month
        total_income = (
            db.query(func.sum(Transaction.amount))
            .filter(
                Transaction.transaction_type == TransactionType.INCOME,
                Transaction.transaction_date >= month_start,
                Transaction.transaction_date <= month_end,
            )
            .scalar()
            or 0
        )

        debt_to_income = abs(debt_payments) / total_income if total_income > 0 else 1.0

        # Score the debt-to-income ratio
        debt_to_income_score = FinancialHealthService._score_component(
            debt_to_income,
            FinancialHealthService.THRESHOLDS["debt_to_income"],
            higher_is_better=False,
        )

        return debt_to_income_score, debt_to_income

    @staticmethod
    def _calculate_emergency_fund(
        db: Session, target_date: date
    ) -> tuple[float, float]:
        """
        Calculate emergency fund score from savings and essential expenses.

        Returns:
            Tuple of (score, emergency_fund_months)
        """
        # Get average monthly essential expenses over the last 6 months
        six_months_ago = target_date - timedelta(days=LOOKBACK_HALF_YEAR_DAYS)

        # First, get the monthly dates for the last 6 months
        monthly_dates = (
            db.query(FinancialStatistics.date)
            .filter(
                FinancialStatistics.period == StatisticsPeriod.MONTHLY,
                FinancialStatistics.date >= six_months_ago,
                FinancialStatistics.date <= target_date,
            )
            .all()
        )

        # Calculate essential expenses for each month
        total_essential_expenses = 0
        months_count = 0

        for date_record in monthly_dates:
            month_date = date_record[0]

            # Get total essential expenses for the month
            essential_expenses = 0

            # Get all essential expense categories
            essential_categories = [
                cat.value for cat in ExpenseCategory.get_essential_categories()
            ]

            # Sum up all expenses from essential categories
            for category in essential_categories:
                category_expense = (
                    db.query(CategoryStatistics.period_amount)
                    .filter(
                        CategoryStatistics.period == StatisticsPeriod.MONTHLY,
                        CategoryStatistics.date == month_date,
                        CategoryStatistics.transaction_type == TransactionType.EXPENSE,
                        CategoryStatistics.category_name == category,
                    )
                    .scalar()
                    or 0
                )

                essential_expenses += category_expense

            if essential_expenses > 0:
                total_essential_expenses += essential_expenses
                months_count += 1

        # Calculate average monthly essential expenses
        avg_monthly_essential_expense = (
            total_essential_expenses / months_count if months_count > 0 else 0
        )

        # Estimate emergency fund from total savings
        # This is a simplified approach - in a real app, you might have a specific
        # emergency fund account or category
        total_savings = (
            db.query(FinancialStatistics)
            .filter(FinancialStatistics.period == StatisticsPeriod.ALL_TIME)
            .first()
        )

        if total_savings and avg_monthly_essential_expense > 0:
            emergency_fund_months = (
                total_savings.total_net_savings / avg_monthly_essential_expense
            )
        else:
            emergency_fund_months = 0

        # Cap at reasonable maximum for scoring.
        emergency_fund_months = min(emergency_fund_months, MAX_EMERGENCY_FUND_MONTHS)

        # Score the emergency fund
        emergency_fund_score = FinancialHealthService._score_component(
            emergency_fund_months,
            FinancialHealthService.THRESHOLDS["emergency_fund"],
            higher_is_better=True,
        )

        return emergency_fund_score, emergency_fund_months

    @staticmethod
    def _calculate_investment_rate(
        db: Session, target_date: date
    ) -> tuple[float, float]:
        """
        Calculate investment rate score as income allocated to investments.

        Returns:
            Tuple of (score, investment_rate)
        """
        # Get the last 3 months of data
        end_date = target_date.replace(
            day=calendar.monthrange(target_date.year, target_date.month)[1]
        )
        start_date = (end_date - relativedelta(months=3)).replace(day=1)

        # Get total income for the period
        income_query = db.query(func.sum(Transaction.amount)).filter(
            Transaction.transaction_type == TransactionType.INCOME,
            Transaction.transaction_date >= start_date,
            Transaction.transaction_date <= end_date,
        )
        total_income = income_query.scalar() or 0

        # Get total investments for the period
        investments_query = db.query(func.sum(Transaction.amount)).filter(
            Transaction.transaction_type == TransactionType.EXPENSE,
            Transaction.expense_category == ExpenseCategory.INVESTMENTS,
            Transaction.transaction_date >= start_date,
            Transaction.transaction_date <= end_date,
        )
        total_investments = abs(
            investments_query.scalar() or 0
        )  # Use abs since expenses are negative

        # Calculate investment rate
        if total_income <= 0:
            return 0, 0  # No income, can't calculate investment rate

        investment_rate = total_investments / total_income

        # Score the investment rate
        investment_rate_score = FinancialHealthService._score_component(
            investment_rate,
            FinancialHealthService.THRESHOLDS["investment_rate"],
            higher_is_better=True,
        )

        return investment_rate_score, investment_rate

    @staticmethod
    def _calculate_spending_stability(
        db: Session, target_date: date
    ) -> tuple[float, float]:
        """
        Calculate spending stability score based on consistency of spending patterns.

        Returns:
            Tuple of (score, stability_coefficient)
        """
        # Get monthly expenses for the last 6 months
        six_months_ago = target_date - timedelta(days=LOOKBACK_HALF_YEAR_DAYS)

        monthly_expenses = (
            db.query(FinancialStatistics.period_expenses)
            .filter(
                FinancialStatistics.period == StatisticsPeriod.MONTHLY,
                FinancialStatistics.date >= six_months_ago,
                FinancialStatistics.date <= target_date,
            )
            .all()
        )

        if (
            not monthly_expenses
            or len(monthly_expenses) < MIN_SPENDING_STABILITY_MONTHS
        ):
            return DEFAULT_MIDDLE_SCORE, DEFAULT_MIDDLE_RATIO

        # Calculate coefficient of variation (standard deviation / mean)
        expenses = [expense[0] for expense in monthly_expenses]
        mean = sum(expenses) / len(expenses)

        if mean == 0:
            return DEFAULT_MIDDLE_SCORE, DEFAULT_MIDDLE_RATIO

        variance = sum((x - mean) ** 2 for x in expenses) / len(expenses)
        std_dev = variance**0.5

        coefficient_of_variation = std_dev / mean

        # Convert to stability (lower coefficient = higher stability)
        stability = max(0, 1 - coefficient_of_variation)

        # Score the stability
        stability_score = FinancialHealthService._score_component(
            stability,
            FinancialHealthService.THRESHOLDS["spending_stability"],
            higher_is_better=True,
        )

        return stability_score, stability

    @staticmethod
    def _generate_recommendations(
        context: RecommendationContext,
    ) -> list[RecommendationPayload]:
        """Generate personalized recommendations based on financial health scores."""
        recommendations: list[RecommendationPayload] = []
        FinancialHealthService._add_savings_recommendations(recommendations, context)
        FinancialHealthService._add_expense_recommendations(recommendations, context)
        FinancialHealthService._add_budget_recommendations(recommendations, context)
        FinancialHealthService._add_debt_recommendations(recommendations, context)
        FinancialHealthService._add_emergency_fund_recommendations(
            recommendations, context
        )
        FinancialHealthService._add_spending_stability_recommendations(
            recommendations, context
        )
        FinancialHealthService._add_investment_recommendations(recommendations, context)
        if len(recommendations) < GENERAL_RECOMMENDATION_MINIMUM:
            FinancialHealthService._add_general_recommendations(recommendations)

        recommendations.sort(
            key=FinancialHealthService._recommendation_priority,
            reverse=True,
        )
        return recommendations[:RECOMMENDATION_LIMIT]

    @staticmethod
    def _add_savings_recommendations(
        recommendations: list[RecommendationPayload],
        context: RecommendationContext,
    ) -> None:
        if context.savings_rate_score >= LOW_SCORE_THRESHOLD:
            return
        recommendations.append(
            {
                "title": "Increase Your Savings Rate",
                "description": (
                    f"Your current savings rate is {context.savings_rate:.1%}, "
                    "which is below recommended levels. Aim to save at least "
                    "15% of your income."
                ),
                "category": "savings_rate",
                "impact_area": "Savings Rate",
                "priority": 5,
                "estimated_score_improvement": 20,
            }
        )
        recommendations.append(
            {
                "title": "Implement the 50/30/20 Budget Rule",
                "description": (
                    "Allocate 50% of income to needs, 30% to wants, and 20% "
                    "to savings and debt repayment."
                ),
                "category": "savings_rate",
                "impact_area": "Savings Rate",
                "priority": 4,
                "estimated_score_improvement": 15,
            }
        )

    @staticmethod
    def _add_expense_recommendations(
        recommendations: list[RecommendationPayload],
        context: RecommendationContext,
    ) -> None:
        if context.expense_ratio_score >= LOW_SCORE_THRESHOLD:
            return
        recommendations.append(
            {
                "title": "Reduce Your Expense-to-Income Ratio",
                "description": (
                    f"Your expenses are {context.expense_ratio:.1%} of your "
                    "income, which is higher than recommended. Try to keep "
                    "expenses below 70% of income."
                ),
                "category": "expense_ratio",
                "impact_area": "Expense Ratio",
                "priority": 5,
                "estimated_score_improvement": 20,
            }
        )
        recommendations.append(
            {
                "title": "Review Subscriptions and Recurring Expenses",
                "description": (
                    "Cancel unused subscriptions and negotiate bills to quickly "
                    "reduce monthly expenses."
                ),
                "category": "expense_ratio",
                "impact_area": "Expense Ratio",
                "priority": 4,
                "estimated_score_improvement": 10,
            }
        )

    @staticmethod
    def _add_budget_recommendations(
        recommendations: list[RecommendationPayload],
        context: RecommendationContext,
    ) -> None:
        if context.budget_adherence_score >= LOW_SCORE_THRESHOLD:
            return
        recommendations.append(
            {
                "title": "Improve Budget Consistency",
                "description": (
                    "Your spending varies significantly from your typical "
                    "patterns. Track expenses more closely to stay within "
                    "category budgets."
                ),
                "category": "budget_adherence",
                "impact_area": "Budget Adherence",
                "priority": 3,
                "estimated_score_improvement": 15,
            }
        )

    @staticmethod
    def _add_debt_recommendations(
        recommendations: list[RecommendationPayload],
        context: RecommendationContext,
    ) -> None:
        if context.debt_to_income_score >= LOW_SCORE_THRESHOLD:
            return
        recommendations.append(
            {
                "title": "Reduce Debt-to-Income Ratio",
                "description": (
                    f"Your debt payments are {context.debt_to_income:.1%} "
                    "of your income, which is higher than recommended. Aim "
                    "to keep this below 30%."
                ),
                "category": "debt_to_income",
                "impact_area": "Debt-to-Income Ratio",
                "priority": 4,
                "estimated_score_improvement": 15,
            }
        )
        if context.debt_to_income > HIGH_DEBT_TO_INCOME_THRESHOLD:
            recommendations.append(
                {
                    "title": "Consider Debt Consolidation",
                    "description": (
                        "Consolidating high-interest debt can lower monthly "
                        "payments and reduce total interest paid."
                    ),
                    "category": "debt_to_income",
                    "impact_area": "Debt-to-Income Ratio",
                    "priority": 5,
                    "estimated_score_improvement": 10,
                }
            )

    @staticmethod
    def _add_emergency_fund_recommendations(
        recommendations: list[RecommendationPayload],
        context: RecommendationContext,
    ) -> None:
        if context.emergency_fund_score >= LOW_SCORE_THRESHOLD:
            return
        recommendations.append(
            {
                "title": "Build Your Emergency Fund",
                "description": (
                    "You have approximately "
                    f"{context.emergency_fund_months:.1f} months of expenses "
                    "saved. Aim for at least 3-6 months."
                ),
                "category": "emergency_fund",
                "impact_area": "Emergency Fund",
                "priority": 5,
                "estimated_score_improvement": 20,
            }
        )
        if context.emergency_fund_months < LOW_EMERGENCY_FUND_MONTHS:
            recommendations.append(
                {
                    "title": (
                        f"Start a EUR {STARTER_EMERGENCY_FUND_EUR:,} Emergency Fund"
                    ),
                    "description": (
                        "Before focusing on other financial goals, build a "
                        f"starter emergency fund of EUR "
                        f"{STARTER_EMERGENCY_FUND_EUR:,}."
                    ),
                    "category": "emergency_fund",
                    "impact_area": "Emergency Fund",
                    "priority": 5,
                    "estimated_score_improvement": 10,
                }
            )

    @staticmethod
    def _add_spending_stability_recommendations(
        recommendations: list[RecommendationPayload],
        context: RecommendationContext,
    ) -> None:
        if context.spending_stability_score >= LOW_SCORE_THRESHOLD:
            return
        recommendations.append(
            {
                "title": "Stabilize Your Spending Patterns",
                "description": (
                    "Your monthly expenses fluctuate significantly, which can "
                    "make budgeting difficult. Work on more consistent "
                    "spending habits."
                ),
                "category": "spending_stability",
                "impact_area": "Spending Stability",
                "priority": 2,
                "estimated_score_improvement": 10,
            }
        )

    @staticmethod
    def _add_investment_recommendations(
        recommendations: list[RecommendationPayload],
        context: RecommendationContext,
    ) -> None:
        if context.investment_rate_score >= LOW_SCORE_THRESHOLD:
            return
        recommendations.append(
            {
                "title": "Increase Your Investment Rate",
                "description": (
                    f"You're currently investing {context.investment_rate:.1%} "
                    "of your income, which is below recommended levels. Aim "
                    "to invest at least 10% of your income for long-term growth."
                ),
                "category": "investment_rate",
                "impact_area": "Investment Rate",
                "priority": 4,
                "estimated_score_improvement": 15,
            }
        )
        if context.investment_rate < LOW_INVESTMENT_RATE_THRESHOLD:
            recommendations.append(
                {
                    "title": "Start with Automated Investing",
                    "description": (
                        "Set up automatic transfers to investment accounts on "
                        "payday to build the habit of investing consistently."
                    ),
                    "category": "investment_rate",
                    "impact_area": "Investment Rate",
                    "priority": 3,
                    "estimated_score_improvement": 10,
                }
            )
        elif context.investment_rate < TARGET_INVESTMENT_RATE_THRESHOLD:
            recommendations.append(
                {
                    "title": "Diversify Your Investment Portfolio",
                    "description": (
                        "Consider a mix of stocks, bonds, and other assets to "
                        "optimize your returns while managing risk."
                    ),
                    "category": "investment_rate",
                    "impact_area": "Investment Rate",
                    "priority": 3,
                    "estimated_score_improvement": 8,
                }
            )

    @staticmethod
    def _add_general_recommendations(
        recommendations: list[RecommendationPayload],
    ) -> None:
        recommendations.append(
            {
                "title": "Review Your Financial Goals",
                "description": (
                    "Set specific, measurable, achievable, relevant, and "
                    "time-bound (SMART) financial goals to improve your "
                    "financial health."
                ),
                "category": "general",
                "impact_area": "Overall Score",
                "priority": 3,
                "estimated_score_improvement": 5,
            }
        )
        recommendations.append(
            {
                "title": "Automate Your Finances",
                "description": (
                    "Set up automatic transfers to savings and investment "
                    "accounts to ensure consistent progress toward your goals."
                ),
                "category": "general",
                "impact_area": "Overall Score",
                "priority": 3,
                "estimated_score_improvement": 5,
            }
        )

    @staticmethod
    def _recommendation_priority(recommendation: RecommendationPayload) -> int:
        priority = recommendation.get("priority", 0)
        return priority if isinstance(priority, int) else 0
