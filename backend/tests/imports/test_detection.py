from app.imports.contracts import ImportStrategyKey
from app.imports.detection import ImportDetector


def test_detector_flags_pdf_statements():
    result = ImportDetector().detect(
        filename="statement.pdf",
        content_type="application/pdf",
        sample=b"%PDF-1.7\n",
    )
    assert result.strategy_key == ImportStrategyKey.PDF_STATEMENT
    assert result.password_protected is False


def test_detector_sniffs_pdf_header_with_misleading_metadata():
    result = ImportDetector().detect(
        filename="statement.txt",
        content_type="text/plain",
        sample=b"%PDF-1.7\nbody",
    )
    assert result.strategy_key == ImportStrategyKey.PDF_STATEMENT
    assert result.password_protected is False


def test_detector_sets_latin1_charset_for_unknown_csv():
    sample = "Datum;Omschrijving\n01/01/2026;Café betaling\n".encode("latin-1")
    result = ImportDetector().detect(
        filename="statement.csv",
        content_type="text/csv",
        sample=sample,
    )
    assert result.strategy_key == ImportStrategyKey.UNKNOWN
    assert result.charset_hint == "latin-1"


def test_detector_keeps_utf8_charset_for_utf8_unknown_csv():
    sample = "Datum;Debet\n01/01/2026;-10.00\n".encode("utf-8")
    result = ImportDetector().detect(
        filename="statement.csv",
        content_type="text/csv",
        sample=sample,
    )
    assert result.strategy_key == ImportStrategyKey.UNKNOWN
    assert result.charset_hint == "utf-8"
