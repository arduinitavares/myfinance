"""Module for backend app routers projections."""

import logging
from datetime import UTC, date, datetime
from typing import Annotated, Any, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.financial_projection import (
    ParamType as ModelParamType,
)
from ..models.financial_projection import (
    ProjectionParameter,
    ProjectionResult,
    ProjectionScenario,
)
from ..schemas import financial_projection as schemas
from ..services.projection_service import ProjectionService

# Set up logging
logger: Any = logging.getLogger(__name__)
PROJECTION_ROUTER_ERRORS: tuple[type[Exception], ...] = (
    KeyError,
    RuntimeError,
    SQLAlchemyError,
    TypeError,
    ValueError,
)

# Create router
router: Any = APIRouter(prefix="/projections", tags=["projections"])
type DbSession = Annotated[Session, Depends(get_db)]
type ScenarioIdPath = Annotated[int, Path(description="ID of the scenario")]
type TimeHorizonQuery = Annotated[
    int,
    Query(120, description="Number of months to project", ge=12, le=180),
]


def _today() -> date:
    return datetime.now(UTC).date()


def _raise_http_error(status_code: int, detail: str) -> NoReturn:
    raise HTTPException(status_code=status_code, detail=detail)


def _raise_server_error(message: str, exc: Exception) -> NoReturn:
    logger.exception(message)
    raise HTTPException(status_code=500, detail=str(exc)) from exc


def _get_scenario_or_404(db: Session, scenario_id: int) -> ProjectionScenario:
    scenario = (
        db.query(ProjectionScenario)
        .filter(ProjectionScenario.id == scenario_id)
        .first()
    )
    if scenario is None:
        _raise_http_error(
            status_code=404,
            detail=f"Scenario with ID {scenario_id} not found",
        )
    return scenario


def _parameter_response(param: ProjectionParameter) -> schemas.ProjectionParameter:
    return schemas.ProjectionParameter(
        id=param.id,
        scenario_id=param.scenario_id,
        param_name=param.param_name,
        param_value=param.param_value,
        param_type=schemas.ParamType(param.param_type.value),
    )


def _scenario_detail_response(
    db: Session,
    scenario: ProjectionScenario,
) -> schemas.ProjectionScenarioDetail:
    parameters = (
        db.query(ProjectionParameter)
        .filter(ProjectionParameter.scenario_id == scenario.id)
        .all()
    )
    return schemas.ProjectionScenarioDetail(
        id=scenario.id,
        name=scenario.name,
        description=scenario.description,
        is_default=scenario.is_default,
        created_at=scenario.created_at,
        user_id=scenario.user_id,
        parameters=[_parameter_response(param) for param in parameters],
    )


def _add_scenario_parameters(
    db: Session,
    *,
    scenario_id: int,
    parameters: list[schemas.ProjectionParameterCreate],
) -> None:
    for param_data in parameters:
        db.add(
            ProjectionParameter(
                scenario_id=scenario_id,
                param_name=param_data.param_name,
                param_value=param_data.param_value,
                param_type=ModelParamType(param_data.param_type.value),
            )
        )


@router.get("/scenarios", response_model=list[schemas.ProjectionScenarioDetail])
def get_scenarios(db: DbSession) -> list[ProjectionScenario]:
    """Get all projection scenarios."""
    try:
        scenarios = db.query(ProjectionScenario).all()
        if not scenarios:
            # Create default scenarios if none exist
            scenarios = ProjectionService.create_default_scenarios(db)
    except PROJECTION_ROUTER_ERRORS as exc:
        _raise_server_error("Error retrieving projection scenarios", exc)
    return scenarios


@router.post("/scenarios", response_model=schemas.ProjectionScenarioDetail)
def create_scenario(
    scenario_data: schemas.ProjectionScenarioCreate,
    db: DbSession,
) -> schemas.ProjectionScenarioDetail:
    """Create a new projection scenario with parameters."""
    try:
        # Create the scenario
        scenario = ProjectionScenario(
            name=scenario_data.name,
            description=scenario_data.description,
            is_default=scenario_data.is_default,
            created_at=_today(),
        )
        db.add(scenario)
        db.flush()  # Get the ID

        # Add parameters
        _add_scenario_parameters(
            db,
            scenario_id=scenario.id,
            parameters=scenario_data.parameters,
        )

        db.commit()

        # Return the scenario with parameters
        scenario_detail = _scenario_detail_response(db, scenario)
    except PROJECTION_ROUTER_ERRORS as exc:
        db.rollback()
        _raise_server_error("Error creating projection scenario", exc)
    return scenario_detail


@router.get("/scenarios/{scenario_id}", response_model=schemas.ProjectionScenarioDetail)
def get_scenario_detail(
    scenario_id: ScenarioIdPath,
    db: DbSession,
) -> schemas.ProjectionScenarioDetail:
    """Get detailed information about a specific scenario including parameters."""
    try:
        scenario = _get_scenario_or_404(db, scenario_id)
        scenario_detail = _scenario_detail_response(db, scenario)

    except HTTPException:
        raise
    except PROJECTION_ROUTER_ERRORS as exc:
        _raise_server_error("Error retrieving scenario details", exc)
    return scenario_detail


@router.put("/scenarios/{scenario_id}", response_model=schemas.ProjectionScenarioDetail)
def update_scenario(
    scenario_id: ScenarioIdPath,
    scenario_data: schemas.ProjectionScenarioCreate,
    db: DbSession,
) -> schemas.ProjectionScenarioDetail:
    """Update a projection scenario and its parameters."""
    try:
        # Check if scenario exists
        scenario = _get_scenario_or_404(db, scenario_id)

        # Update scenario fields
        scenario.name = scenario_data.name
        scenario.description = scenario_data.description
        scenario.is_default = scenario_data.is_default

        # Delete existing parameters
        db.query(ProjectionParameter).filter(
            ProjectionParameter.scenario_id == scenario_id
        ).delete()

        # Add new parameters
        _add_scenario_parameters(
            db,
            scenario_id=scenario_id,
            parameters=scenario_data.parameters,
        )

        db.commit()

        # Return updated scenario with parameters
        scenario_detail = _scenario_detail_response(db, scenario)
    except HTTPException:
        raise
    except PROJECTION_ROUTER_ERRORS as exc:
        db.rollback()
        _raise_server_error("Error updating projection scenario", exc)
    return scenario_detail


@router.delete("/scenarios/{scenario_id}", response_model=dict[str, bool])
def delete_scenario(scenario_id: ScenarioIdPath, db: DbSession) -> dict[str, bool]:
    """Delete a projection scenario and its parameters."""
    try:
        # Check if scenario exists
        scenario = _get_scenario_or_404(db, scenario_id)

        # Don't allow deletion of default scenarios
        if scenario.is_default:
            _raise_http_error(status_code=400, detail="Cannot delete default scenarios")

        # Delete the scenario (parameters will be cascade deleted)
        db.delete(scenario)
        db.commit()
        result = {"success": True}
    except HTTPException:
        raise
    except PROJECTION_ROUTER_ERRORS as exc:
        db.rollback()
        _raise_server_error("Error deleting projection scenario", exc)
    return result


@router.get(
    "/scenarios/{scenario_id}/parameters",
    response_model=list[schemas.ProjectionParameter],
)
def get_scenario_parameters(
    scenario_id: ScenarioIdPath,
    db: DbSession,
) -> list[schemas.ProjectionParameter]:
    """Get parameters for a specific scenario."""
    try:
        # Check if scenario exists
        _get_scenario_or_404(db, scenario_id)

        # Get parameters
        parameters = (
            db.query(ProjectionParameter)
            .filter(ProjectionParameter.scenario_id == scenario_id)
            .all()
        )

        # Convert SQLAlchemy model instances to Pydantic schema instances
        parameter_response = [_parameter_response(param) for param in parameters]

    except HTTPException:
        raise
    except PROJECTION_ROUTER_ERRORS as exc:
        _raise_server_error("Error retrieving scenario parameters", exc)
    return parameter_response


@router.post("/scenarios/{scenario_id}/calculate", response_model=dict[str, bool])
def calculate_projection(
    scenario_id: ScenarioIdPath,
    time_horizon: TimeHorizonQuery,
    db: DbSession,
) -> dict[str, bool]:
    """Calculate projection for a scenario."""
    try:
        # Check if scenario exists
        _get_scenario_or_404(db, scenario_id)

        # Calculate projection
        ProjectionService.calculate_projection(db, scenario_id, time_horizon)
        result = {"success": True}
    except HTTPException:
        raise
    except PROJECTION_ROUTER_ERRORS as exc:
        _raise_server_error("Error calculating projection", exc)
    return result


@router.get(
    "/scenarios/{scenario_id}/results", response_model=schemas.ProjectionTimeseries
)
def get_projection_results(
    scenario_id: ScenarioIdPath,
    db: DbSession,
) -> dict[str, Any]:
    """Get projection results for a scenario."""
    try:
        # Check if scenario exists
        _get_scenario_or_404(db, scenario_id)

        # Get results
        results = ProjectionService.get_projection_results(db, scenario_id)

    except HTTPException:
        raise
    except PROJECTION_ROUTER_ERRORS as exc:
        _raise_server_error("Error retrieving projection results", exc)
    return results


@router.post("/scenarios/compare", response_model=schemas.ScenarioComparison)
def compare_scenarios(
    scenario_ids: list[int],
    db: DbSession,
) -> dict[str, Any]:
    """Compare multiple scenarios side by side."""
    try:
        if not scenario_ids:
            _raise_http_error(status_code=400, detail="No scenario IDs provided")

        # Check if all scenarios exist
        for scenario_id in scenario_ids:
            _get_scenario_or_404(db, scenario_id)

            # Check if projection has been calculated
            results = (
                db.query(ProjectionResult)
                .filter(ProjectionResult.scenario_id == scenario_id)
                .first()
            )
            if not results:
                # Calculate projection if not already done
                ProjectionService.calculate_projection(db, scenario_id)

        # Compare scenarios
        comparison = ProjectionService.compare_scenarios(db, scenario_ids)

    except HTTPException:
        raise
    except PROJECTION_ROUTER_ERRORS as exc:
        _raise_server_error("Error comparing scenarios", exc)
    return comparison


@router.post("/scenarios/base/recompute", response_model=dict[str, Any])
def recompute_base_scenario_parameters(db: DbSession) -> dict[str, Any]:
    """Recompute the parameters of the base scenario using the latest historical data.

    This endpoint updates the base scenario to reflect the most recent financial
    patterns from the user's historical data.
    """
    try:
        # Recompute base scenario parameters
        result = ProjectionService.recompute_base_case_parameters(db)

        # Calculate projection with new parameters
        ProjectionService.calculate_projection(db, result["scenario_id"])
    except PROJECTION_ROUTER_ERRORS as exc:
        _raise_server_error("Error recomputing base scenario parameters", exc)
    return result
