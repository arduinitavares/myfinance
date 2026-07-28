"""Module for backend tests test_upload_guardrails."""

import csv
import io
from typing import Any

from app.database_manager import reset_database
from app.main import app
from app.routers import imports as imports_router
from fastapi.testclient import TestClient

client: Any = TestClient(app)
HTTP_OK: int = 200
HTTP_BAD_REQUEST: int = 400
HTTP_UNSUPPORTED_MEDIA_TYPE: int = 415
HTTP_TOO_MANY_REQUESTS: int = 429


def _reset_rate_limiter() -> None:
    # Clear in-memory per-IP rate limiter to avoid test cross-talk
    try:
        imports_router._upload_attempts.clear()
    except AttributeError:
        return


def _reset_database() -> None:
    reset_database()


def _make_minimal_beobank_compact_csv(rows: int = 1) -> bytes:
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(
        [
            "Datum",
            "Waardedatum",
            "Debet",
            "Krediet",
            "Omschrijving",
            "Saldo",
        ]
    )
    for i in range(rows):
        writer.writerow(
            [
                "03/01/2026",
                "03/01/2026",
                "-10,00",
                "",
                f"Bancontact betaling Nationale Loterij {i}",
                "375,53",
            ]
        )
    return output.getvalue().encode("latin-1")


def _make_minimal_belfius_export_csv() -> bytes:
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Boekingsdatum vanaf", "01/02/2026"])
    writer.writerow(["Boekingsdatum tot en met", "13/04/2026"])
    writer.writerow(["Bedrag vanaf", ""])
    writer.writerow(["Bedrag tot en met", ""])
    writer.writerow(["Rekeninguittrekselnummer vanaf", ""])
    writer.writerow(["Rekeninguittrekselnummer tot en met", ""])
    writer.writerow(["Mededeling", ""])
    writer.writerow(["Naam tegenpartij bevat", ""])
    writer.writerow(["Rekening tegenpartij", ""])
    writer.writerow(["Laatste saldo", "-140,40 EUR"])
    writer.writerow(["Datum/uur van het laatste saldo", "11/04/2026 13:14:53"])
    writer.writerow(["", ""])
    writer.writerow(
        [
            "Rekening",
            "Boekingsdatum",
            "Rekeninguittrekselnummer",
            "Transactienummer",
            "Rekening tegenpartij",
            "Naam tegenpartij bevat",
            "Straat en nummer",
            "Postcode en plaats",
            "Transactie",
            "Valutadatum",
            "Bedrag",
            "Devies",
            "BIC",
            "Landcode",
            "Mededelingen",
        ]
    )
    writer.writerow(
        [
            "BE46 0636 5194 6836",
            "10/04/2026",
            "00004",
            "33",
            "",
            "",
            "",
            "",
            "INTERESTEN : 01.01.2026 - 31.03.2026",
            "01/04/2026",
            "-3,59",
            "EUR",
            "",
            "",
            "INTERESTEN : 01.01.2026 - 31.03.2026",
        ]
    )
    return output.getvalue().encode("utf-8")


def test_rejects_non_csv_extension() -> None:
    """Verify rejects non csv extension."""
    _reset_rate_limiter()
    _reset_database()
    files = {"file": ("not_csv.txt", b"not a csv", "text/plain")}
    resp = client.post("/imports/upload", files=files)
    assert resp.status_code == HTTP_BAD_REQUEST
    assert "Invalid file format" in resp.text


def test_rejects_unsupported_media_type_with_csv_extension() -> None:
    """Verify rejects unsupported media type with csv extension."""
    _reset_rate_limiter()
    _reset_database()
    files = {
        # Wrong content type on purpose
        "file": ("data.csv", _make_minimal_beobank_compact_csv(1), "application/json")
    }
    resp = client.post("/imports/upload", files=files)
    assert resp.status_code == HTTP_UNSUPPORTED_MEDIA_TYPE
    assert "Unsupported media type" in resp.text


def test_rate_limit_per_ip() -> None:
    """Verify rate limit per ip."""
    _reset_rate_limiter()
    _reset_database()
    for index in range(3):
        files = {
            "file": (
                f"data-{index}.csv",
                _make_minimal_beobank_compact_csv(index + 1),
                "text/csv",
            )
        }
        r = client.post("/imports/upload", files=files)
        assert r.status_code == HTTP_OK
    # Fourth within window should be rate-limited
    r = client.post(
        "/imports/upload",
        files={
            "file": ("data-4.csv", _make_minimal_beobank_compact_csv(4), "text/csv")
        },
    )
    assert r.status_code == HTTP_TOO_MANY_REQUESTS


def test_row_cap_returns_400() -> None:
    """Verify row cap returns 400."""
    _reset_rate_limiter()
    _reset_database()
    # 5001 rows to exceed MAX_ROWS_PER_UPLOAD = 5000
    csv_bytes = _make_minimal_beobank_compact_csv(rows=5001)
    files = {"file": ("big.csv", csv_bytes, "text/csv")}
    resp = client.post("/imports/upload", files=files)
    assert resp.status_code == HTTP_BAD_REQUEST
    assert "maximum allowed per upload" in resp.text


def test_accepts_beobank_compact_csv_export() -> None:
    """Verify accepts beobank compact csv export."""
    _reset_rate_limiter()
    _reset_database()
    files = {
        "file": ("50212984548.csv", _make_minimal_beobank_compact_csv(), "text/csv")
    }

    resp = client.post("/imports/upload", files=files)

    assert resp.status_code == HTTP_OK
    payload = resp.json()
    assert payload["status"] == "awaiting_review"
    assert payload["strategy_key"] == "beobank_csv"
    assert payload["provider_hint"] == "beobank"
    assert payload["extractor_id"] == "beobank_csv_v1"


def test_accepts_belfius_csv_export_with_metadata_preface() -> None:
    """Verify accepts belfius csv export with metadata preface."""
    _reset_rate_limiter()
    _reset_database()
    files = {
        "file": (
            "BE46 0636 5194 6836 2026-04-11 13-17-27 1.csv",
            _make_minimal_belfius_export_csv(),
            "text/csv",
        )
    }

    resp = client.post("/imports/upload", files=files)

    assert resp.status_code == HTTP_OK
    payload = resp.json()
    assert payload["status"] == "awaiting_review"
    assert payload["strategy_key"] == "belfius_csv"
    assert payload["provider_hint"] == "belfius"
    assert payload["extractor_id"] == "belfius_csv_v1"
