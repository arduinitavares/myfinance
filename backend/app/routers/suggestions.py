"""Module for backend app routers suggestions."""

import logging
from typing import Annotated, Any, NoReturn

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.transaction import TransactionType
from ..services.category_suggestion_service import CategorySuggestionService

# Set up logging
logger: Any = logging.getLogger(__name__)

# Create router
router: Any = APIRouter(prefix="/suggestions", tags=["suggestions"])
DbSession: object = Annotated[Session, Depends(get_db)]
SUGGESTION_ROUTER_ERRORS: tuple[type[Exception], ...] = (
    RuntimeError,
    TypeError,
    ValueError,
)

# Initialize the service
category_suggestion_service: Any = CategorySuggestionService()

# Initialize category suggestions
with next(get_db()) as db:
    category_suggestion_service.train_on_existing_transactions(db)


# Schema for the request body
class CategorySuggestionRequest(BaseModel):
    """Represent category suggestion request."""

    description: str
    amount: float
    transaction_type: TransactionType


def _raise_server_error(message: str, exc: Exception) -> NoReturn:
    logger.exception(message)
    raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/category")
def suggest_category(request: CategorySuggestionRequest) -> dict[str, object]:
    """Handle suggest category."""
    try:
        suggestions = category_suggestion_service.suggest_category(
            request.description, request.amount, request.transaction_type
        )
        suggestion_payload: list[dict[str, object]] = [
            {"category": category, "confidence": float(confidence)}
            for category, confidence in suggestions
        ]
        response: dict[str, object] = {"suggestions": suggestion_payload}
    except SUGGESTION_ROUTER_ERRORS as exc:
        _raise_server_error("Error suggesting category", exc)
    return response


@router.post("/initialize")
def initialize_category_suggestions(db: DbSession) -> dict[str, str]:
    """Initialize category suggestions."""
    try:
        category_suggestion_service.train_on_existing_transactions(db)
        response = {"message": "Category suggestion model initialized successfully"}
    except SUGGESTION_ROUTER_ERRORS as exc:
        _raise_server_error("Error initializing category suggestions", exc)
    return response
