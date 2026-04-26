"""Module for backend tests services test_reporting_currency."""

from datetime import date
from decimal import Decimal
from typing import Annotated

import pytest
from app.database_manager import reset_database
from app.models.fx import FXDailyReferenceRate
from app.services.reporting_currency import get_reporting_currency
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

HTTP_OK: int = 200
HTTP_BAD_REQUEST: int = 400
FX_RATE_PRECISION: int = 18
FX_RATE_SCALE: int = 8
SOURCE_NAME_LENGTH: int = 50

probe_app: FastAPI = FastAPI()


@probe_app.get("/probe-reporting-currency")
def probe_reporting_currency(
    reporting_currency: Annotated[str, Depends(get_reporting_currency)],
) -> dict[str, str]:
    """Handle probe reporting currency."""
    return {"reporting_currency": reporting_currency}


client: TestClient = TestClient(probe_app)


def test_default_reporting_currency_is_eur_when_header_missing() -> None:
    """Verify default reporting currency is eur when header missing."""
    response = client.get("/probe-reporting-currency")

    assert response.status_code == HTTP_OK
    assert response.json() == {"reporting_currency": "EUR"}


def test_invalid_reporting_currency_returns_allowed_payload() -> None:
    """Verify invalid reporting currency returns allowed payload."""
    response = client.get(
        "/probe-reporting-currency", headers={"X-Reporting-Currency": "GBP"}
    )

    assert response.status_code == HTTP_BAD_REQUEST
    assert response.json() == {
        "detail": {
            "error": "invalid_reporting_currency",
            "allowed": ["EUR", "USD", "BRL"],
        }
    }


def test_fx_table_bootstrap_uses_runtime_schema_and_decimal_safe_columns(
    db_session: Session,
) -> None:
    """Verify fx table bootstrap uses runtime schema and decimal safe columns."""
    reset_database()

    inspector = inspect(db_session.get_bind())
    assert "fx_daily_reference_rates" in inspector.get_table_names()

    columns = {
        column["name"]: column
        for column in inspector.get_columns("fx_daily_reference_rates")
    }
    assert columns["units_per_base"]["type"].__class__.__name__ == "NUMERIC"
    assert getattr(columns["units_per_base"]["type"], "precision", None) == (
        FX_RATE_PRECISION
    )
    assert getattr(columns["units_per_base"]["type"], "scale", None) == FX_RATE_SCALE
    assert (
        getattr(columns["source_name"]["type"], "length", None) == SOURCE_NAME_LENGTH
    )


def test_fx_daily_reference_rate_identity_is_unique(db_session: Session) -> None:
    """Verify fx daily reference rate identity is unique."""
    first = FXDailyReferenceRate(
        rate_date=date(2026, 4, 17),
        base_currency="EUR",
        quoted_currency="USD",
        units_per_base=Decimal("1.23456789"),
        source_name="ecb",
    )
    second = FXDailyReferenceRate(
        rate_date=date(2026, 4, 17),
        base_currency="EUR",
        quoted_currency="USD",
        units_per_base=Decimal("1.11111111"),
        source_name="ecb",
    )

    db_session.add(first)
    db_session.commit()

    db_session.add(second)
    with pytest.raises(IntegrityError):
        db_session.commit()
