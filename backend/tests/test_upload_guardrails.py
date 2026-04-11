import io
import csv
from fastapi.testclient import TestClient

from app.main import app
from app.routers import transactions as tx_router

client = TestClient(app)


def _reset_rate_limiter():
    # Clear in-memory per-IP rate limiter to avoid test cross-talk
    try:
        tx_router._upload_attempts.clear()  # type: ignore[attr-defined]
    except Exception:
        pass


def _reset_database():
    resp = client.post('/debug/reset-database')
    assert resp.status_code == 200


def _make_minimal_ing_csv(rows: int = 1) -> bytes:
    """Create a minimal valid ING CSV content with the expected headers and delimiter ';'."""
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    # Headers expected by detection and parsing
    writer.writerow([
        'Account Number',
        'Account Name',
        'Counterparty account',
        'Booking date',
        'Amount',
        'Currency',
        'Description',
    ])
    for i in range(rows):
        writer.writerow([
            'BE1234567890',               # Account Number
            'Main Account',               # Account Name
            'BE0987654321',               # Counterparty account
            '01/01/2025',                 # Booking date (DD/MM/YYYY)
            '1.00',                       # Amount
            'EUR',                        # Currency
            f'Test row {i}',              # Description
        ])
    return output.getvalue().encode('utf-8')


def _make_minimal_beobank_compact_csv() -> bytes:
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow([
        'Datum',
        'Waardedatum',
        'Debet',
        'Krediet',
        'Omschrijving',
        'Saldo',
    ])
    writer.writerow([
        '03/01/2026',
        '03/01/2026',
        '-10,00',
        '',
        'Bancontact betaling Nationale Loterij',
        '375,53',
    ])
    return output.getvalue().encode('latin-1')


def _make_minimal_belfius_export_csv() -> bytes:
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['Boekingsdatum vanaf', '01/02/2026'])
    writer.writerow(['Boekingsdatum tot en met', '13/04/2026'])
    writer.writerow(['Bedrag vanaf', ''])
    writer.writerow(['Bedrag tot en met', ''])
    writer.writerow(['Rekeninguittrekselnummer vanaf', ''])
    writer.writerow(['Rekeninguittrekselnummer tot en met', ''])
    writer.writerow(['Mededeling', ''])
    writer.writerow(['Naam tegenpartij bevat', ''])
    writer.writerow(['Rekening tegenpartij', ''])
    writer.writerow(['Laatste saldo', '-140,40 EUR'])
    writer.writerow(['Datum/uur van het laatste saldo', '11/04/2026 13:14:53'])
    writer.writerow(['', ''])
    writer.writerow([
        'Rekening',
        'Boekingsdatum',
        'Rekeninguittrekselnummer',
        'Transactienummer',
        'Rekening tegenpartij',
        'Naam tegenpartij bevat',
        'Straat en nummer',
        'Postcode en plaats',
        'Transactie',
        'Valutadatum',
        'Bedrag',
        'Devies',
        'BIC',
        'Landcode',
        'Mededelingen',
    ])
    writer.writerow([
        'BE46 0636 5194 6836',
        '10/04/2026',
        '00004',
        '33',
        '',
        '',
        '',
        '',
        'INTERESTEN : 01.01.2026 - 31.03.2026',
        '01/04/2026',
        '-3,59',
        'EUR',
        '',
        '',
        'INTERESTEN : 01.01.2026 - 31.03.2026',
    ])
    return output.getvalue().encode('utf-8')


def test_rejects_non_csv_extension():
    _reset_rate_limiter()
    _reset_database()
    files = {
        'file': ('not_csv.txt', b'not a csv', 'text/plain')
    }
    resp = client.post('/transactions/upload/', files=files)
    assert resp.status_code == 400
    assert 'Invalid file format' in resp.text


def test_rejects_unsupported_media_type_with_csv_extension():
    _reset_rate_limiter()
    _reset_database()
    files = {
        # Wrong content type on purpose
        'file': ('data.csv', _make_minimal_ing_csv(1), 'application/pdf')
    }
    resp = client.post('/transactions/upload/', files=files)
    assert resp.status_code == 415
    assert 'Unsupported media type' in resp.text


def test_rate_limit_per_ip():
    _reset_rate_limiter()
    _reset_database()
    files = {
        'file': ('data.csv', _make_minimal_ing_csv(1), 'text/csv')
    }
    # First three should pass guardrail (status may be 200 with [] or list)
    for _ in range(3):
        r = client.post('/transactions/upload/', files=files)
        assert r.status_code in (200, 207, 400, 415, 413)
    # Fourth within window should be rate-limited
    r = client.post('/transactions/upload/', files=files)
    assert r.status_code == 429


def test_row_cap_returns_400():
    _reset_rate_limiter()
    _reset_database()
    # 5001 rows to exceed MAX_ROWS_PER_UPLOAD = 5000
    csv_bytes = _make_minimal_ing_csv(rows=5001)
    files = {
        'file': ('big.csv', csv_bytes, 'text/csv')
    }
    resp = client.post('/transactions/upload/', files=files)
    assert resp.status_code == 400
    assert 'maximum allowed per upload' in resp.text


def test_accepts_beobank_compact_csv_export():
    _reset_rate_limiter()
    _reset_database()
    files = {
        'file': ('50212984548.csv', _make_minimal_beobank_compact_csv(), 'text/csv')
    }

    resp = client.post('/transactions/upload/', files=files)

    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]['source_bank'] == 'Beobank'
    assert items[0]['account_number'] == '50212984548'
    assert items[0]['transaction_date'] == '2026-01-03'
    assert items[0]['amount'] == -10.0
    assert items[0]['description'] == 'Bancontact betaling Nationale Loterij'


def test_accepts_belfius_csv_export_with_metadata_preface():
    _reset_rate_limiter()
    _reset_database()
    files = {
        'file': ('BE46 0636 5194 6836 2026-04-11 13-17-27 1.csv', _make_minimal_belfius_export_csv(), 'text/csv')
    }

    resp = client.post('/transactions/upload/', files=files)

    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]['source_bank'] == 'Belfius'
    assert items[0]['account_number'] == 'BE46 0636 5194 6836'
    assert items[0]['transaction_date'] == '2026-04-10'
    assert items[0]['amount'] == -3.59
    assert items[0]['currency'] == 'EUR'
