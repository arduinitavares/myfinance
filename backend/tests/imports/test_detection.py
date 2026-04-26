"""Module for backend tests imports test_detection."""

import pytest
from app.config import settings
from app.imports.contracts import ImportStrategyKey
from app.imports.detection import ImportDetector
from tests.imports.fixtures.nexo_csv import (
    NEXO_CSV_HEADER,
    build_nexo_csv_bytes,
    nexo_row,
)


def test_detector_flags_belfius_csv_with_metadata_preface() -> None:
    """Verify detector flags belfius csv with metadata preface."""
    sample = (
        b"Boekingsdatum vanaf;01/02/2026\n"
        b"Boekingsdatum tot en met;13/04/2026\n"
        b"Bedrag vanaf;\n"
        b"Bedrag tot en met;\n"
        b"Rekeninguittrekselnummer vanaf;\n"
        b"Rekeninguittrekselnummer tot en met;\n"
        b"Mededeling;\n"
        b"Naam tegenpartij bevat;\n"
        b"Rekening tegenpartij;\n"
        b"Laatste saldo;-140,40 EUR\n"
        b"Datum/uur van het laatste saldo;11/04/2026 13:14:53\n"
        b";\n"
        b"Rekening;Boekingsdatum;Rekeninguittrekselnummer;"
        b"Transactienummer;Rekening tegenpartij;"
        b"Naam tegenpartij bevat;Straat en nummer;Postcode en plaats;"
        b"Transactie;Valutadatum;Bedrag;"
        b"Devies;BIC;Landcode;Mededelingen\n"
    )

    result = ImportDetector().detect(
        filename="belfius.csv",
        content_type="text/csv",
        sample=sample,
    )

    assert result.strategy_key == ImportStrategyKey.BELFIUS_CSV
    assert result.charset_hint == "utf-8"


def test_detector_does_not_scan_belfius_header_past_first_twenty_lines() -> None:
    """Verify detector does not scan belfius header past first twenty lines."""
    lines = [f"metadata-{idx};value" for idx in range(20)]
    lines.append(
        "Rekening;Boekingsdatum;Rekeninguittrekselnummer;"
        "Transactienummer;Rekening tegenpartij;"
        "Naam tegenpartij bevat;Straat en nummer;Postcode en plaats;"
        "Transactie;Valutadatum;Bedrag;"
        "Devies;BIC;Landcode;Mededelingen"
    )
    sample = ("\n".join(lines) + "\n").encode("utf-8")

    result = ImportDetector().detect(
        filename="late-belfius.csv",
        content_type="text/csv",
        sample=sample,
    )

    assert result.strategy_key == ImportStrategyKey.UNKNOWN


def test_detector_flags_beobank_compact_csv() -> None:
    """Verify detector flags beobank compact csv."""
    sample = "Datum;Waardedatum;Debet;Krediet;Omschrijving;Saldo\n".encode("latin-1")

    result = ImportDetector().detect(
        filename="50212984548.csv",
        content_type="text/csv",
        sample=sample,
    )

    assert result.strategy_key == ImportStrategyKey.BEOBANK_CSV
    assert result.charset_hint == "utf-8"


def test_detector_flags_beobank_debit_credit_csv() -> None:
    """Verify detector flags beobank debit credit csv."""
    sample = b"Date;Debit;Credit;Message;Balance\n"

    result = ImportDetector().detect(
        filename="beobank.csv",
        content_type="text/csv",
        sample=sample,
    )

    assert result.strategy_key == ImportStrategyKey.BEOBANK_CSV


def test_detector_flags_nexo_csv_on_exact_header_match() -> None:
    """Verify detector flags nexo csv on exact header match."""
    sample = (
        b"Transaction,Type,Input Currency,Input Amount,Output Currency,"
        b"Output Amount,USD Equivalent,"
        b"Fee,Fee Currency,Details,Date / Time (UTC),normalizedDisplayDetails\n"
    )

    result = ImportDetector().detect(
        filename="nexo.csv",
        content_type="text/csv",
        sample=sample,
    )

    assert result.strategy_key == ImportStrategyKey.NEXO_CSV
    assert result.charset_hint == "utf-8"


def test_detector_does_not_route_mislabeled_non_pdf_payload_as_pdf_statement() -> None:
    """Verify detector does not route mislabeled non pdf payload as pdf statement."""
    result = ImportDetector().detect(
        filename="statement.pdf",
        content_type="application/pdf",
        sample=b"not actually a pdf",
    )
    assert result.strategy_key == ImportStrategyKey.UNKNOWN
    assert result.password_protected is False


def test_detector_flags_pdf_statements() -> None:
    """Verify detector flags pdf statements."""
    result = ImportDetector().detect(
        filename="statement.pdf",
        content_type="application/pdf",
        sample=b"%PDF-1.7\n",
    )
    assert result.strategy_key == ImportStrategyKey.PDF_STATEMENT
    assert result.password_protected is False


def test_detector_sniffs_pdf_header_with_misleading_metadata() -> None:
    """Verify detector sniffs pdf header with misleading metadata."""
    result = ImportDetector().detect(
        filename="statement.txt",
        content_type="text/plain",
        sample=b"%PDF-1.7\nbody",
    )
    assert result.strategy_key == ImportStrategyKey.PDF_STATEMENT
    assert result.password_protected is False


def test_detector_sets_latin1_charset_for_unknown_csv() -> None:
    """Verify detector sets latin1 charset for unknown csv."""
    sample = "Datum;Omschrijving\n01/01/2026;Café betaling\n".encode("latin-1")
    result = ImportDetector().detect(
        filename="statement.csv",
        content_type="text/csv",
        sample=sample,
    )
    assert result.strategy_key == ImportStrategyKey.UNKNOWN
    assert result.charset_hint == "latin-1"


def test_detector_keeps_utf8_charset_for_utf8_unknown_csv() -> None:
    """Verify detector keeps utf8 charset for utf8 unknown csv."""
    sample = b"Datum;Debet\n01/01/2026;-10.00\n"
    result = ImportDetector().detect(
        filename="statement.csv",
        content_type="text/csv",
        sample=sample,
    )
    assert result.strategy_key == ImportStrategyKey.UNKNOWN
    assert result.charset_hint == "utf-8"


def test_detector_flags_exact_nexo_csv_header_shape() -> None:
    """Verify detector flags exact nexo csv header shape."""
    sample = build_nexo_csv_bytes(
        nexo_row(
            "NXT_PURCHASE_1",
            "Nexo Card Purchase",
            "xUSD",
            "-6.24",
            "approved / Albert Heijn 3143 | Gent | BEL",
            "2026-03-25 17:19:21",
        )
    )
    result = ImportDetector().detect(
        filename="nexo_transactions.csv",
        content_type="text/csv",
        sample=sample,
    )
    assert result.strategy_key == ImportStrategyKey.NEXO_CSV
    assert result.provider_hint == "nexo"
    assert result.charset_hint == "utf-8"


def test_detector_does_not_match_nearly_identical_nexo_header() -> None:
    """Verify detector does not match nearly identical nexo header."""
    malformed_header = list(NEXO_CSV_HEADER)
    malformed_header[10] = "Date / Time"
    sample = (
        build_nexo_csv_bytes(
            nexo_row(
                "NXT_PURCHASE_1",
                "Nexo Card Purchase",
                "xUSD",
                "-6.24",
                "approved / Albert Heijn 3143 | Gent | BEL",
                "2026-03-25 17:19:21",
            )
        )
        .decode("utf-8")
        .replace(",".join(NEXO_CSV_HEADER), ",".join(malformed_header), 1)
        .encode("utf-8")
    )
    result = ImportDetector().detect(
        filename="nexo_transactions.csv",
        content_type="text/csv",
        sample=sample,
    )
    assert result.strategy_key == ImportStrategyKey.UNKNOWN
    assert result.charset_hint == "utf-8"


def test_db_session_fixture_cleans_import_artifacts_before_reuse(
    request: pytest.FixtureRequest,
) -> None:
    """Verify db session fixture cleans import artifacts before reuse."""
    stale_session_dir = settings.imports_dir / "session-1"
    stale_session_dir.mkdir(parents=True, exist_ok=True)
    (stale_session_dir / "meta.json").write_text("stale", encoding="utf-8")

    request.getfixturevalue("db_session")

    assert not stale_session_dir.exists()
