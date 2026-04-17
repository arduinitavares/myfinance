from datetime import date

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.models.fx import FXDailyReferenceRate
from app.database_manager import reset_database
from app.services.reporting_currency import get_reporting_currency


probe_app = FastAPI()


@probe_app.get("/probe-reporting-currency")
def probe_reporting_currency(reporting_currency=Depends(get_reporting_currency)):
    return {"reporting_currency": reporting_currency}


client = TestClient(probe_app)


def test_default_reporting_currency_is_eur_when_header_missing():
    response = client.get("/probe-reporting-currency")

    assert response.status_code == 200
    assert response.json() == {"reporting_currency": "EUR"}


def test_invalid_reporting_currency_returns_allowed_payload():
    response = client.get("/probe-reporting-currency", headers={"X-Reporting-Currency": "GBP"})

    assert response.status_code == 400
    assert response.json() == {
        "detail": {
            "error": "invalid_reporting_currency",
            "allowed": ["EUR", "USD", "BRL"],
        }
    }


def test_fx_table_bootstrap_uses_runtime_schema_and_decimal_safe_columns(db_session):
    reset_database()

    inspector = inspect(db_session.get_bind())
    assert "fx_daily_reference_rates" in inspector.get_table_names()

    columns = {column["name"]: column for column in inspector.get_columns("fx_daily_reference_rates")}
    assert columns["units_per_base"]["type"].__class__.__name__ == "NUMERIC"
    assert getattr(columns["units_per_base"]["type"], "precision", None) == 18
    assert getattr(columns["units_per_base"]["type"], "scale", None) == 8
    assert getattr(columns["source_name"]["type"], "length", None) == 50


def test_fx_daily_reference_rate_identity_is_unique(db_session):
    first = FXDailyReferenceRate(
        rate_date=date(2026, 4, 17),
        base_currency="EUR",
        quoted_currency="USD",
        units_per_base=1.23456789,
        source_name="ecb",
    )
    second = FXDailyReferenceRate(
        rate_date=date(2026, 4, 17),
        base_currency="EUR",
        quoted_currency="USD",
        units_per_base=1.11111111,
        source_name="ecb",
    )

    db_session.add(first)
    db_session.commit()

    db_session.add(second)
    with pytest.raises(IntegrityError):
        db_session.commit()
