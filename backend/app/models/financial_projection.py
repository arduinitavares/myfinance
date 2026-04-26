"""Module for backend app models financial_projection."""

import enum
from datetime import date

from sqlalchemy import Boolean, Date, Enum, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class ParamType(enum.StrEnum):
    """Represent param type."""

    PERCENTAGE = "percentage"
    AMOUNT = "amount"
    MONTHS = "months"
    INTEGER = "integer"
    BOOLEAN = "boolean"


class ProjectionScenario(Base):
    """Represent projection scenario."""

    __tablename__ = "projection_scenarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_at: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=True)
    is_base_scenario: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=True
    )
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Relationships
    parameters: Mapped[list["ProjectionParameter"]] = relationship(
        "ProjectionParameter", back_populates="scenario", cascade="all, delete-orphan"
    )
    results: Mapped[list["ProjectionResult"]] = relationship(
        "ProjectionResult", back_populates="scenario", cascade="all, delete-orphan"
    )


class ProjectionParameter(Base):
    """Represent projection parameter."""

    __tablename__ = "projection_parameters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    scenario_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projection_scenarios.id"), nullable=False
    )
    param_name: Mapped[str] = mapped_column(String(100), nullable=False)
    param_value: Mapped[float] = mapped_column(Float, nullable=False)
    param_type: Mapped[ParamType] = mapped_column(Enum(ParamType), nullable=False)

    # Relationships
    scenario: Mapped["ProjectionScenario"] = relationship(
        "ProjectionScenario", back_populates="parameters"
    )


class ProjectionResult(Base):
    """Represent projection result."""

    __tablename__ = "projection_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    scenario_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projection_scenarios.id"), nullable=False
    )
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    projected_income: Mapped[float] = mapped_column(Float, nullable=False)
    projected_expenses: Mapped[float] = mapped_column(Float, nullable=False)
    projected_investments: Mapped[float] = mapped_column(Float, nullable=False)
    projected_savings: Mapped[float] = mapped_column(Float, nullable=False)
    projected_net_worth: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)

    # Relationships
    scenario: Mapped["ProjectionScenario"] = relationship(
        "ProjectionScenario", back_populates="results"
    )
