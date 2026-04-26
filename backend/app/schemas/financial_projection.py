"""Module for backend app schemas financial_projection."""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel


class ParamType(StrEnum):
    """Represent param type."""

    PERCENTAGE = "percentage"
    AMOUNT = "amount"
    MONTHS = "months"
    INTEGER = "integer"
    BOOLEAN = "boolean"


class ProjectionParameterBase(BaseModel):
    """Represent projection parameter base."""

    param_name: str
    param_value: float
    param_type: ParamType


class ProjectionParameterCreate(ProjectionParameterBase):
    """Represent projection parameter create."""



class ProjectionParameter(ProjectionParameterBase):
    """Represent projection parameter."""

    id: int
    scenario_id: int

    class Config:
        """Represent config."""

        orm_mode = True


class ProjectionScenarioBase(BaseModel):
    """Represent projection scenario base."""

    name: str
    description: str
    is_default: bool = False
    is_base_scenario: bool = False


class ProjectionScenarioCreate(ProjectionScenarioBase):
    """Represent projection scenario create."""

    parameters: list[ProjectionParameterCreate]


class ProjectionScenario(ProjectionScenarioBase):
    """Represent projection scenario."""

    id: int
    created_at: date
    user_id: int | None = None

    class Config:
        """Represent config."""

        orm_mode = True


class ProjectionScenarioDetail(ProjectionScenario):
    """Represent projection scenario detail."""

    parameters: list[ProjectionParameter] = []


class ProjectionResultBase(BaseModel):
    """Represent projection result base."""

    month: int
    year: int
    projected_income: float
    projected_expenses: float
    projected_investments: float
    projected_savings: float
    projected_net_worth: float


class ProjectionResultCreate(ProjectionResultBase):
    """Represent projection result create."""

    scenario_id: int


class ProjectionResult(ProjectionResultBase):
    """Represent projection result."""

    id: int
    scenario_id: int
    created_at: date

    class Config:
        """Represent config."""

        orm_mode = True


class ProjectionTimeseries(BaseModel):
    """Represent projection timeseries."""

    dates: list[str]
    projected_income: list[float]
    projected_expenses: list[float]
    projected_investments: list[float]
    projected_savings: list[float]
    projected_net_worth: list[float]


class ScenarioComparison(BaseModel):
    """Represent scenario comparison."""

    scenario_names: list[str]
    dates: list[str]
    net_worth_series: dict[str, list[float]]
    savings_series: dict[str, list[float]]
    investment_series: dict[str, list[float]]
