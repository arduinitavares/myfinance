"""Module for backend app services projection_service."""

import calendar
import copy
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, ClassVar, NoReturn

import numpy as np
from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import Session

from ..models.financial_health import FinancialHealth
from ..models.financial_projection import (
    ParamType,
    ProjectionParameter,
    ProjectionResult,
    ProjectionScenario,
)
from ..models.statistics import (
    CategoryStatistics,
    FinancialStatistics,
    StatisticsPeriod,
)
from ..models.transaction import (
    ExpenseCategory,
    ExpenseType,
    Transaction,
    TransactionType,
)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger: logging.Logger = logging.getLogger(__name__)

MONTHS_PER_YEAR: int = 12
ANNUAL_GROWTH_MONTH_COUNT: int = 24
MIN_WINSORIZE_POINTS: int = 4

type ProjectionParameterSpec = dict[str, float | ParamType]
type ProjectionParameterSet = dict[str, ProjectionParameterSpec]


def _today() -> date:
    """Return the current UTC date."""
    return datetime.now(UTC).date()


def _raise_value_error(message: str) -> NoReturn:
    raise ValueError(message)


@dataclass(frozen=True)
class ScenarioDefinition:
    """Default scenario metadata and parameter definitions."""

    name: str
    description: str
    parameters: ProjectionParameterSet


@dataclass(frozen=True)
class HistoricalSeries:
    """Monthly financial series used for projection analysis."""

    dates: list[date]
    income: list[float]
    expenses: list[float]
    savings: list[float]


@dataclass
class ProjectionRunState:
    """Mutable state for one projection calculation."""

    current_date: date
    current_income: float
    current_essential_expenses: float
    current_discretionary_expenses: float
    current_investment_rate: float
    expense_ratio_cap: float
    investment_portfolio: float
    net_worth: float
    monthly_income_growth: float
    monthly_essential_growth: float
    monthly_discretionary_growth: float
    monthly_investment_return: float


class ProjectionService:
    """Service for analyzing financial data and creating future projections."""

    # Default parameters for projection scenarios
    DEFAULT_PARAMETERS: ClassVar[dict[str, ProjectionParameterSet]] = {
        "base_case": {
            "income_growth_rate": {"value": 0.03, "type": ParamType.PERCENTAGE},
            "essential_expenses_growth_rate": {
                "value": 0.03,
                "type": ParamType.PERCENTAGE,
            },
            "discretionary_expenses_growth_rate": {
                "value": 0.03,
                "type": ParamType.PERCENTAGE,
            },
            "investment_rate": {"value": 0.10, "type": ParamType.PERCENTAGE},
            "inflation_rate": {"value": 0.02, "type": ParamType.PERCENTAGE},
            "investment_return_rate": {"value": 0.07, "type": ParamType.PERCENTAGE},
            "emergency_fund_target": {"value": 6.0, "type": ParamType.MONTHS},
            "holdings_market_value": {"value": 0.0, "type": ParamType.AMOUNT},
        },
        "optimistic_case": {
            "income_growth_rate": {"value": 0.05, "type": ParamType.PERCENTAGE},
            "essential_expenses_growth_rate": {
                "value": 0.02,
                "type": ParamType.PERCENTAGE,
            },
            "discretionary_expenses_growth_rate": {
                "value": 0.02,
                "type": ParamType.PERCENTAGE,
            },
            "investment_rate": {"value": 0.15, "type": ParamType.PERCENTAGE},
            "inflation_rate": {"value": 0.02, "type": ParamType.PERCENTAGE},
            "investment_return_rate": {"value": 0.08, "type": ParamType.PERCENTAGE},
            "emergency_fund_target": {"value": 6.0, "type": ParamType.MONTHS},
            "holdings_market_value": {"value": 0.0, "type": ParamType.AMOUNT},
        },
        "conservative_case": {
            "income_growth_rate": {"value": 0.02, "type": ParamType.PERCENTAGE},
            "essential_expenses_growth_rate": {
                "value": 0.03,
                "type": ParamType.PERCENTAGE,
            },
            "discretionary_expenses_growth_rate": {
                "value": 0.03,
                "type": ParamType.PERCENTAGE,
            },
            "investment_rate": {"value": 0.10, "type": ParamType.PERCENTAGE},
            "inflation_rate": {"value": 0.03, "type": ParamType.PERCENTAGE},
            "investment_return_rate": {"value": 0.05, "type": ParamType.PERCENTAGE},
            "emergency_fund_target": {"value": 9.0, "type": ParamType.MONTHS},
            "holdings_market_value": {"value": 0.0, "type": ParamType.AMOUNT},
        },
        "expense_reduction": {
            "income_growth_rate": {"value": 0.03, "type": ParamType.PERCENTAGE},
            "essential_expenses_growth_rate": {
                "value": 0.02,
                "type": ParamType.PERCENTAGE,
            },
            "discretionary_expenses_growth_rate": {
                "value": -0.05,
                "type": ParamType.PERCENTAGE,
            },
            "investment_rate": {"value": 0.12, "type": ParamType.PERCENTAGE},
            "inflation_rate": {"value": 0.02, "type": ParamType.PERCENTAGE},
            "investment_return_rate": {"value": 0.07, "type": ParamType.PERCENTAGE},
            "emergency_fund_target": {"value": 6.0, "type": ParamType.MONTHS},
            "holdings_market_value": {"value": 0.0, "type": ParamType.AMOUNT},
        },
        "investment_focus": {
            "income_growth_rate": {"value": 0.03, "type": ParamType.PERCENTAGE},
            "essential_expenses_growth_rate": {
                "value": 0.03,
                "type": ParamType.PERCENTAGE,
            },
            "discretionary_expenses_growth_rate": {
                "value": 0.01,
                "type": ParamType.PERCENTAGE,
            },
            "investment_rate": {"value": 0.20, "type": ParamType.PERCENTAGE},
            "inflation_rate": {"value": 0.02, "type": ParamType.PERCENTAGE},
            "investment_return_rate": {"value": 0.07, "type": ParamType.PERCENTAGE},
            "emergency_fund_target": {"value": 6.0, "type": ParamType.MONTHS},
            "holdings_market_value": {"value": 0.0, "type": ParamType.AMOUNT},
        },
    }

    @staticmethod
    def create_default_scenarios(db: Session) -> list[ProjectionScenario]:
        """Create the default projection scenarios if they don't exist."""
        scenarios = []

        # Check if default scenarios already exist
        existing_defaults = (
            db.query(ProjectionScenario).filter(ProjectionScenario.is_default).all()
        )
        if existing_defaults:
            return existing_defaults

        # Define default scenarios
        historical_data = ProjectionService.analyze_historical_data(db)

        # Start with a deep copy of the default base_case parameters
        base_case_params = copy.deepcopy(
            ProjectionService.DEFAULT_PARAMETERS["base_case"]
        )

        # Keep original defaults when historical data has no replacement value.
        base_case_params["income_growth_rate"]["value"] = historical_data.get(
            "avg_annual_income_growth", base_case_params["income_growth_rate"]["value"]
        )
        base_case_params["essential_expenses_growth_rate"]["value"] = (
            historical_data.get(
                "avg_annual_essential_expense_growth",
                base_case_params["essential_expenses_growth_rate"]["value"],
            )
        )
        base_case_params["discretionary_expenses_growth_rate"]["value"] = (
            historical_data.get(
                "avg_annual_discretionary_expense_growth",
                base_case_params["discretionary_expenses_growth_rate"]["value"],
            )
        )
        base_case_params["investment_rate"]["value"] = historical_data.get(
            "avg_investment_rate", base_case_params["investment_rate"]["value"]
        )

        scenario_definitions = {
            "base_case": ScenarioDefinition(
                name="Base Case",
                description=(
                    "Projection based on current patterns and average growth rates"
                ),
                parameters=base_case_params,
            ),
            "optimistic_case": ScenarioDefinition(
                name="Optimistic Case",
                description=(
                    "Projection with higher income growth and investment returns"
                ),
                parameters=ProjectionService.DEFAULT_PARAMETERS["optimistic_case"],
            ),
            "conservative_case": ScenarioDefinition(
                name="Conservative Case",
                description=(
                    "Projection with lower income growth and investment returns"
                ),
                parameters=ProjectionService.DEFAULT_PARAMETERS["conservative_case"],
            ),
            "expense_reduction": ScenarioDefinition(
                name="Expense Reduction",
                description="Projection focused on reducing discretionary spending",
                parameters=ProjectionService.DEFAULT_PARAMETERS["expense_reduction"],
            ),
            "investment_focus": ScenarioDefinition(
                name="Investment Focus",
                description="Projection prioritizing increased investments",
                parameters=ProjectionService.DEFAULT_PARAMETERS["investment_focus"],
            ),
        }

        try:
            # Create each default scenario
            for key, definition in scenario_definitions.items():
                # Set is_base_scenario to True only for the Base Case
                is_base = key == "base_case"

                scenario = ProjectionScenario(
                    name=definition.name,
                    description=definition.description,
                    is_default=True,
                    is_base_scenario=is_base,
                    created_at=_today(),
                )
                db.add(scenario)
                db.flush()  # Get the ID

                # Add parameters
                for param_name, param_info in definition.parameters.items():
                    param = ProjectionParameter(
                        scenario_id=scenario.id,
                        param_name=param_name,
                        param_value=param_info["value"],
                        param_type=param_info["type"],
                    )
                    db.add(param)

                scenarios.append(scenario)

            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Error creating default scenarios")
            raise
        else:
            return scenarios

    @staticmethod
    def calculate_annual_growth(monthly_amounts: list[float]) -> float | None:
        """Calculate annualized growth between two consecutive years.

        Args:
            monthly_amounts: Monthly values in chronological order.

        Returns:
            The annual growth rate as a decimal, or None if calculation is not possible

        Methodology:
            1. Sum first 12 months (year 1 total)
            2. Sum next 12 months (year 2 total)
            3. Calculate (year2_total / year1_total) - 1
        """
        # Validate input length
        if len(monthly_amounts) < ANNUAL_GROWTH_MONTH_COUNT:
            return None

        # Calculate total for year 1 (first 12 months)
        year1_total = sum(monthly_amounts[:MONTHS_PER_YEAR])

        # Calculate total for year 2 (next 12 months)
        year2_total = sum(monthly_amounts[MONTHS_PER_YEAR:ANNUAL_GROWTH_MONTH_COUNT])

        # Handle zero beginning value
        if year1_total == 0:
            return None

        # Calculate annual growth rate
        return (year2_total / year1_total) - 1

    @staticmethod
    def _historical_cutoff_date(db: Session) -> date:
        latest_transaction = (
            db.query(Transaction).order_by(Transaction.transaction_date.desc()).first()
        )
        reference_date = (
            latest_transaction.transaction_date if latest_transaction else _today()
        )
        cutoff_date = reference_date - relativedelta(years=2)
        return cutoff_date.replace(
            day=calendar.monthrange(cutoff_date.year, cutoff_date.month)[1]
        )

    @staticmethod
    def _monthly_financial_stats_since(
        db: Session, cutoff_date: date
    ) -> list[FinancialStatistics]:
        return (
            db.query(FinancialStatistics)
            .filter(
                FinancialStatistics.period == StatisticsPeriod.MONTHLY,
                FinancialStatistics.date > cutoff_date,
            )
            .order_by(FinancialStatistics.date)
            .all()
        )

    @staticmethod
    def _investment_amounts_by_month(
        db: Session, cutoff_date: date
    ) -> dict[str, float]:
        investment_categories = (
            db.query(CategoryStatistics)
            .filter(
                CategoryStatistics.period == StatisticsPeriod.MONTHLY,
                CategoryStatistics.date >= cutoff_date,
                CategoryStatistics.transaction_type == TransactionType.EXPENSE,
                CategoryStatistics.category_name == ExpenseCategory.INVESTMENTS.value,
            )
            .order_by(CategoryStatistics.date)
            .all()
        )
        investment_stats: dict[str, float] = {}
        for stat in investment_categories:
            if stat.date is None:
                continue
            month_key = stat.date.strftime("%Y-%m")
            investment_stats[month_key] = investment_stats.get(month_key, 0.0) + (
                stat.period_amount or 0.0
            )
        return investment_stats

    @staticmethod
    def _historical_series(
        monthly_stats: list[FinancialStatistics],
        investment_stats: dict[str, float],
    ) -> HistoricalSeries:
        dates: list[date] = []
        income_series: list[float] = []
        expense_series: list[float] = []
        savings_series: list[float] = []

        for stat in monthly_stats:
            if stat.date is None:
                continue
            dates.append(stat.date)
            income_series.append(stat.period_income or 0.0)
            investment_amount = investment_stats.get(stat.date.strftime("%Y-%m"), 0.0)
            adjusted_expenses = max(
                0.0,
                (stat.period_expenses or 0.0) - investment_amount,
            )
            expense_series.append(adjusted_expenses)
            savings_series.append(stat.period_net_savings or 0.0)

        return HistoricalSeries(
            dates=dates,
            income=income_series,
            expenses=expense_series,
            savings=savings_series,
        )

    @staticmethod
    def _expense_type_monthly_totals(
        db: Session, cutoff_date: date
    ) -> tuple[list[float], list[float]]:
        category_stats = (
            db.query(CategoryStatistics)
            .filter(
                CategoryStatistics.period == StatisticsPeriod.MONTHLY,
                CategoryStatistics.date >= cutoff_date,
                CategoryStatistics.transaction_type == TransactionType.EXPENSE,
            )
            .order_by(CategoryStatistics.date)
            .all()
        )
        monthly_expense_stats: dict[str, dict[str, list[float]]] = {}
        for stat in category_stats:
            if stat.category_name == ExpenseCategory.INVESTMENTS.value:
                continue
            if stat.date is None:
                continue

            month_key = stat.date.strftime("%Y-%m")
            month_data = monthly_expense_stats.setdefault(
                month_key,
                {"essential": [], "discretionary": []},
            )
            expense_type = (
                "essential"
                if stat.expense_type == ExpenseType.FIXED_ESSENTIAL
                else "discretionary"
            )
            month_data[expense_type].append(stat.period_amount or 0.0)

        if not monthly_expense_stats:
            return [0.0], [0.0]

        monthly_essential = [
            sum(ProjectionService._winsorize(month_data["essential"]))
            for month_data in monthly_expense_stats.values()
        ]
        monthly_discretionary = [
            sum(ProjectionService._winsorize(month_data["discretionary"]))
            for month_data in monthly_expense_stats.values()
        ]
        return monthly_essential, monthly_discretionary

    @staticmethod
    def analyze_historical_data(db: Session) -> dict[str, Any]:
        """Analyze historical financial data to extract patterns and trends."""
        try:
            two_years_ago = ProjectionService._historical_cutoff_date(db)
            monthly_stats = ProjectionService._monthly_financial_stats_since(
                db, two_years_ago
            )
            if not monthly_stats:
                _raise_value_error(
                    "Not enough historical data for analysis (need at least 3 months)"
                )

            investment_stats = ProjectionService._investment_amounts_by_month(
                db, two_years_ago
            )
            series = ProjectionService._historical_series(
                monthly_stats,
                investment_stats,
            )

            # Apply winsorization to handle outliers before calculating averages
            income_series_w = ProjectionService._winsorize(series.income)
            expense_series_w = ProjectionService._winsorize(series.expenses)
            savings_series_w = ProjectionService._winsorize(series.savings)

            # Calculate averages using winsorized data
            avg_monthly_income = np.mean(income_series_w)
            avg_monthly_expenses = np.mean(expense_series_w)
            avg_monthly_savings = np.mean(savings_series_w)

            # Year-over-year comparison avoids noisy month-over-month averages.
            annual_income_growth = ProjectionService.calculate_annual_growth(
                series.income
            )
            annual_expense_growth = ProjectionService.calculate_annual_growth(
                series.expenses
            )

            # Default to 3% if we can't calculate from historical data
            avg_annual_income_growth = (
                annual_income_growth if annual_income_growth is not None else 0.03
            )
            avg_annual_expense_growth = (
                annual_expense_growth if annual_expense_growth is not None else 0.03
            )

            # Calculate average investment rate over the last two years
            financial_health_records = (
                db.query(FinancialHealth)
                .filter(FinancialHealth.date >= two_years_ago)
                .order_by(FinancialHealth.date)
                .all()
            )

            investment_rates = [
                record.investment_rate
                for record in financial_health_records
                if record.investment_rate is not None
            ]
            avg_investment_rate = (
                np.mean(investment_rates) if investment_rates else 0.10
            )

            monthly_essential, monthly_discretionary = (
                ProjectionService._expense_type_monthly_totals(db, two_years_ago)
            )

            annual_essential_expense_growth = ProjectionService.calculate_annual_growth(
                monthly_essential
            )
            annual_discretionary_expense_growth = (
                ProjectionService.calculate_annual_growth(monthly_discretionary)
            )

            # Default to 3% if we can't calculate from historical data
            avg_annual_essential_expense_growth = (
                annual_essential_expense_growth
                if annual_essential_expense_growth is not None
                else 0.03
            )
            avg_annual_discretionary_expense_growth = (
                annual_discretionary_expense_growth
                if annual_discretionary_expense_growth is not None
                else 0.03
            )

            avg_essential_ratio = (
                np.mean(monthly_essential) / avg_monthly_expenses
                if avg_monthly_expenses > 0
                else 0.6
            )
            avg_discretionary_ratio = (
                np.mean(monthly_discretionary) / avg_monthly_expenses
                if avg_monthly_expenses > 0
                else 0.4
            )

            avg_expense_to_income_ratio = (
                (avg_monthly_expenses / avg_monthly_income)
                if avg_monthly_income > 0
                else 0.85
            )

            # Calculate seasonality (not implemented in this version)
            # This would identify recurring patterns in income/expenses

            return {
                "avg_monthly_income": avg_monthly_income,
                "avg_monthly_expenses": avg_monthly_expenses,
                "avg_monthly_savings": avg_monthly_savings,
                "avg_annual_income_growth": avg_annual_income_growth,
                "avg_annual_expense_growth": avg_annual_expense_growth,
                "avg_annual_essential_expense_growth": (
                    avg_annual_essential_expense_growth
                ),
                "avg_annual_discretionary_expense_growth": (
                    avg_annual_discretionary_expense_growth
                ),
                "avg_investment_rate": avg_investment_rate,
                "essential_expense_ratio": avg_essential_ratio,
                "discretionary_expense_ratio": avg_discretionary_ratio,
                "avg_expense_to_income_ratio": avg_expense_to_income_ratio,
                "latest_date": series.dates[-1] if series.dates else _today(),
            }

        except Exception:
            logger.exception("Error analyzing historical data")
            raise

    @staticmethod
    def calculate_projection(
        db: Session, scenario_id: int, time_horizon: int = 120
    ) -> list[ProjectionResult]:
        """
        Calculate financial projections for a scenario.

        Args:
            db: Database session
            scenario_id: ID of the scenario to calculate
            time_horizon: Number of months to project (default: 60 = 5 years)

        Returns:
            List of projection results
        """
        try:
            # Get the scenario and its parameters
            scenario = (
                db.query(ProjectionScenario)
                .filter(ProjectionScenario.id == scenario_id)
                .first()
            )
            if not scenario:
                _raise_value_error(f"Scenario with ID {scenario_id} not found")

            # Recompute base case parameters if it's the base scenario
            if scenario.is_base_scenario:
                ProjectionService.recompute_base_case_parameters(db)

            param_dict = ProjectionService._scenario_parameters(db, scenario_id)
            historical_data = ProjectionService.analyze_historical_data(db)
            db.query(ProjectionResult).filter(
                ProjectionResult.scenario_id == scenario_id
            ).delete()
            state = ProjectionService._projection_run_state(
                db=db,
                param_dict=param_dict,
                historical_data=historical_data,
            )
            results = ProjectionService._generate_projection_results(
                db=db,
                scenario_id=scenario_id,
                time_horizon=time_horizon,
                state=state,
            )
            db.commit()

        except Exception:
            db.rollback()
            logger.exception("Error calculating projection")
            raise
        else:
            return results

    @staticmethod
    def _scenario_parameters(db: Session, scenario_id: int) -> dict[str, float]:
        parameters = (
            db.query(ProjectionParameter)
            .filter(ProjectionParameter.scenario_id == scenario_id)
            .all()
        )
        return {param.param_name: param.param_value for param in parameters}

    @staticmethod
    def _projection_run_state(
        *,
        db: Session,
        param_dict: dict[str, float],
        historical_data: dict[str, Any],
    ) -> ProjectionRunState:
        current_income = historical_data["avg_monthly_income"]
        investment_portfolio = param_dict.get("holdings_market_value", 0.0)
        latest_stats = (
            db.query(FinancialStatistics)
            .filter(FinancialStatistics.period == StatisticsPeriod.ALL_TIME)
            .first()
        )
        savings_base = (
            latest_stats.total_net_savings
            if latest_stats
            else current_income * (MONTHS_PER_YEAR / 2)
        )
        return ProjectionRunState(
            current_date=historical_data["latest_date"],
            current_income=current_income,
            current_essential_expenses=(
                historical_data["avg_monthly_expenses"]
                * historical_data["essential_expense_ratio"]
            ),
            current_discretionary_expenses=(
                historical_data["avg_monthly_expenses"]
                * historical_data["discretionary_expense_ratio"]
            ),
            current_investment_rate=historical_data["avg_investment_rate"]
            or param_dict.get("investment_rate", 0.10),
            expense_ratio_cap=min(
                0.95,
                historical_data.get("avg_expense_to_income_ratio", 0.85),
            ),
            investment_portfolio=investment_portfolio,
            net_worth=savings_base + investment_portfolio,
            monthly_income_growth=ProjectionService._monthly_growth(
                param_dict.get(
                    "income_growth_rate",
                    historical_data.get("avg_annual_income_growth", 0.03),
                )
            ),
            monthly_essential_growth=ProjectionService._monthly_growth(
                param_dict.get(
                    "essential_expenses_growth_rate",
                    historical_data.get("avg_annual_essential_expense_growth", 0.03),
                )
            ),
            monthly_discretionary_growth=ProjectionService._monthly_growth(
                param_dict.get(
                    "discretionary_expenses_growth_rate",
                    historical_data.get(
                        "avg_annual_discretionary_expense_growth", 0.03
                    ),
                )
            ),
            monthly_investment_return=ProjectionService._monthly_growth(
                param_dict.get("investment_return_rate", 0.07)
            ),
        )

    @staticmethod
    def _monthly_growth(annual_rate: float) -> float:
        return (1 + annual_rate) ** (1 / MONTHS_PER_YEAR) - 1

    @staticmethod
    def _generate_projection_results(
        *,
        db: Session,
        scenario_id: int,
        time_horizon: int,
        state: ProjectionRunState,
    ) -> list[ProjectionResult]:
        results: list[ProjectionResult] = []
        for month_index in range(time_horizon):
            result = ProjectionService._projection_result_for_month(
                scenario_id=scenario_id,
                month_index=month_index,
                state=state,
            )
            db.add(result)
            results.append(result)
        return results

    @staticmethod
    def _projection_result_for_month(
        *,
        scenario_id: int,
        month_index: int,
        state: ProjectionRunState,
    ) -> ProjectionResult:
        projection_date = state.current_date + relativedelta(months=month_index + 1)
        if month_index > 0:
            state.current_income *= 1 + state.monthly_income_growth
            state.current_essential_expenses *= 1 + state.monthly_essential_growth
            state.current_discretionary_expenses *= (
                1 + state.monthly_discretionary_growth
            )

        total_expenses_pre = (
            state.current_essential_expenses + state.current_discretionary_expenses
        )
        total_expenses = ProjectionService._capped_expenses(
            state,
            total_expenses_pre,
        )
        investment_amount = state.current_income * state.current_investment_rate
        savings = state.current_income - total_expenses - investment_amount
        state.investment_portfolio = (
            state.investment_portfolio * (1 + state.monthly_investment_return)
        ) + investment_amount
        state.net_worth += savings + investment_amount

        return ProjectionResult(
            scenario_id=scenario_id,
            month=projection_date.month,
            year=projection_date.year,
            projected_income=state.current_income,
            projected_expenses=total_expenses,
            projected_investments=investment_amount,
            projected_savings=savings,
            projected_net_worth=state.net_worth,
            created_at=_today(),
        )

    @staticmethod
    def _capped_expenses(state: ProjectionRunState, total_expenses_pre: float) -> float:
        cap_amount = state.current_income * state.expense_ratio_cap
        if total_expenses_pre <= cap_amount or total_expenses_pre <= 0:
            return total_expenses_pre

        scale = cap_amount / total_expenses_pre
        state.current_essential_expenses *= scale
        state.current_discretionary_expenses *= scale
        return cap_amount

    @staticmethod
    def get_projection_results(db: Session, scenario_id: int) -> dict[str, Any]:
        """Get projection results in a format suitable for visualization."""
        try:
            results = (
                db.query(ProjectionResult)
                .filter(ProjectionResult.scenario_id == scenario_id)
                .order_by(ProjectionResult.year, ProjectionResult.month)
                .all()
            )

            if not results:
                _raise_value_error(
                    f"No projection results found for scenario {scenario_id}"
                )

            # Format results for visualization
            dates = []
            income_series = []
            expense_series = []
            investment_series = []
            savings_series = []
            net_worth_series = []

            for result in results:
                date_str = f"{result.year}-{result.month:02d}"
                dates.append(date_str)
                income_series.append(round(result.projected_income, 2))
                expense_series.append(round(result.projected_expenses, 2))
                investment_series.append(round(result.projected_investments, 2))
                savings_series.append(round(result.projected_savings, 2))
                net_worth_series.append(round(result.projected_net_worth, 2))

            payload = {
                "dates": dates,
                "projected_income": income_series,
                "projected_expenses": expense_series,
                "projected_investments": investment_series,
                "projected_savings": savings_series,
                "projected_net_worth": net_worth_series,
            }

        except Exception:
            logger.exception("Error retrieving projection results")
            raise
        else:
            return payload

    @staticmethod
    def recompute_base_case_parameters(db: Session) -> dict[str, Any]:
        """Recompute base case parameters from latest historical data.

        This method updates the base case scenario parameters to reflect the most recent
        financial patterns from the user's historical data. It's useful for keeping the
        base case scenario relevant as new financial data is added over time.

        Returns:
            Scenario ID, name, parameter changes, and a success message.
        """
        try:
            # Find the base scenario using the is_base_scenario flag
            base_case = (
                db.query(ProjectionScenario)
                .filter(ProjectionScenario.is_base_scenario)
                .first()
            )

            if not base_case:
                _raise_value_error(
                    "Base scenario not found. Please ensure one scenario has "
                    "is_base_scenario set to True."
                )

            # Get current parameters
            current_params = {}
            params = (
                db.query(ProjectionParameter)
                .filter(ProjectionParameter.scenario_id == base_case.id)
                .all()
            )
            for param in params:
                current_params[param.param_name] = {
                    "value": param.param_value,
                    "type": param.param_type,
                }

            # Get latest historical data
            historical_data = ProjectionService.analyze_historical_data(db)

            # Define parameters to update with their corresponding historical data keys
            param_mapping = {
                "income_growth_rate": "avg_annual_income_growth",
                "essential_expenses_growth_rate": "avg_annual_essential_expense_growth",
                "discretionary_expenses_growth_rate": (
                    "avg_annual_discretionary_expense_growth"
                ),
                "investment_rate": "avg_investment_rate",
            }

            # Track changes for return value
            changes = {}

            # Update parameters
            for param_name, historical_key in param_mapping.items():
                param = (
                    db.query(ProjectionParameter)
                    .filter(
                        ProjectionParameter.scenario_id == base_case.id,
                        ProjectionParameter.param_name == param_name,
                    )
                    .first()
                )

                if param and historical_key in historical_data:
                    # Record old value
                    old_value = param.param_value

                    # Update with new value
                    param.param_value = historical_data[historical_key]

                    # Track the change
                    changes[param_name] = {
                        "old": old_value,
                        "new": param.param_value,
                        "type": param.param_type.value,
                    }

            # Commit changes
            db.commit()

            # Delete any existing projection results for this scenario
            # so they will be recalculated with the new parameters
            db.query(ProjectionResult).filter(
                ProjectionResult.scenario_id == base_case.id
            ).delete()
            db.commit()

            payload = {
                "scenario_id": base_case.id,
                "scenario_name": base_case.name,
                "changes": changes,
                "message": "Base Case parameters updated successfully",
            }

        except Exception:
            db.rollback()
            logger.exception("Error recomputing base case parameters")
            raise
        else:
            return payload

    @staticmethod
    def _winsorize(data_series: list[float], limits: float = 0.05) -> list[float]:
        """Cap extreme values at configured percentile bounds.

        Args:
            data_series: List of numerical values.
            limits: Proportion to cut off on each tail.

        Returns:
            List of values with extremes capped to reduce the impact of outliers.
        """
        if not data_series or len(data_series) < MIN_WINSORIZE_POINTS:
            return data_series

        # Convert to numpy array for easier calculations
        data_array = np.array(data_series)

        # Compute lower and upper percentile bounds
        lower_pct = limits * 100.0
        upper_pct = 100.0 - lower_pct

        lower_bound = np.percentile(data_array, lower_pct)
        upper_bound = np.percentile(data_array, upper_pct)

        # Clamp values to bounds
        return [min(max(x, lower_bound), upper_bound) for x in data_series]

    @staticmethod
    def compare_scenarios(db: Session, scenario_ids: list[int]) -> dict[str, Any]:
        """Compare multiple scenarios side by side."""
        try:
            comparison = {
                "scenario_names": [],
                "dates": [],
                "net_worth_series": {},
                "savings_series": {},
                "investment_series": {},
            }

            # Get the first scenario's dates to use as reference
            if not scenario_ids:
                _raise_value_error("No scenarios provided for comparison")

            first_results = (
                db.query(ProjectionResult)
                .filter(ProjectionResult.scenario_id == scenario_ids[0])
                .order_by(ProjectionResult.year, ProjectionResult.month)
                .all()
            )

            if not first_results:
                _raise_value_error(
                    f"No projection results found for scenario {scenario_ids[0]}"
                )

            # Set up dates
            for result in first_results:
                date_str = f"{result.year}-{result.month:02d}"
                comparison["dates"].append(date_str)

            # Get data for each scenario
            for scenario_id in scenario_ids:
                scenario = (
                    db.query(ProjectionScenario)
                    .filter(ProjectionScenario.id == scenario_id)
                    .first()
                )
                if not scenario:
                    continue

                comparison["scenario_names"].append(scenario.name)

                results = (
                    db.query(ProjectionResult)
                    .filter(ProjectionResult.scenario_id == scenario_id)
                    .order_by(ProjectionResult.year, ProjectionResult.month)
                    .all()
                )

                if not results:
                    continue

                # Extract series
                net_worth_series = [round(r.projected_net_worth, 2) for r in results]
                savings_series = [round(r.projected_savings, 2) for r in results]
                investment_series = [round(r.projected_investments, 2) for r in results]

                comparison["net_worth_series"][scenario.name] = net_worth_series
                comparison["savings_series"][scenario.name] = savings_series
                comparison["investment_series"][scenario.name] = investment_series

        except Exception:
            logger.exception("Error comparing scenarios")
            raise
        else:
            return comparison
