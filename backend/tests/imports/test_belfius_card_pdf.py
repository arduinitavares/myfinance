"""Module for backend tests imports test_belfius_card_pdf."""

from app.imports.belfius_card_pdf import BelfiusCardPdfExtractor
from app.imports.pdf_text import lineize_pdf_pages
from tests.imports.fixtures.belfius_card_pages import SANITIZED_BELFIUS_CARD_PAGE_TEXTS


def test_parser_extracts_belfius_card_transactions() -> None:
    """Verify parser extracts card rows and ignores fx helper lines."""
    result = BelfiusCardPdfExtractor().extract_from_pages(
        lineize_pdf_pages(SANITIZED_BELFIUS_CARD_PAGE_TEXTS),
        raw_artifact_ref="imports/session-22/attempts/1/evidence/raw.json",
    )

    assert result.extractor_id == "belfius_card_pdf_v1"
    assert result.statement_metadata == {
        "statement_period_start": "2025-12-08",
        "statement_period_end": "2026-01-07",
        "card_number_hint": "5440 56XX XXXX 3844",
        "currency": "EUR",
    }
    assert [tx.transaction_date for tx in result.transactions] == [
        "2025-12-07",
        "2025-12-19",
        "2025-12-28",
        "2026-01-04",
    ]
    assert [tx.source_description for tx in result.transactions] == [
        "UBR PENDING.UBER.COM AMSTERDAM NL (Via Apple Pay)",
        "PADARIA E CONFEITARIA PRAIA GRANDE BR (Via )",
        "Uber UBER TRIP HELP.U SAO PAULO BR (Via Apple Pay)",
        "Wise Bruxelles BE (Via Apple Pay)",
    ]
    assert [tx.signed_amount for tx in result.transactions] == [
        -30.74,
        -3.15,
        -2.81,
        -500.0,
    ]
    assert [tx.debit_credit for tx in result.transactions] == [
        "debit",
        "debit",
        "debit",
        "debit",
    ]
    assert [tx.source_locator for tx in result.transactions] == [
        "pdf:p1:l8-9",
        "pdf:p1:l10-11",
        "pdf:p1:l14-15",
        "pdf:p1:l16-17",
    ]
    assert result.issues == []
