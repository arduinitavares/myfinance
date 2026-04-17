from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

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
