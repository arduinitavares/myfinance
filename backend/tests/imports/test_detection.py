from app.imports.contracts import ImportStrategyKey
from app.imports.detection import ImportDetector
from app.config import settings


def test_detector_does_not_route_mislabeled_non_pdf_payload_as_pdf_statement():
    result = ImportDetector().detect(
        filename="statement.pdf",
        content_type="application/pdf",
        sample=b"not actually a pdf",
    )
    assert result.strategy_key == ImportStrategyKey.UNKNOWN
    assert result.password_protected is False


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


def test_db_session_fixture_cleans_import_artifacts_before_reuse(request):
    stale_session_dir = settings.imports_dir / "session-1"
    stale_session_dir.mkdir(parents=True, exist_ok=True)
    (stale_session_dir / "meta.json").write_text("stale", encoding="utf-8")

    request.getfixturevalue("db_session")

    assert not stale_session_dir.exists()
