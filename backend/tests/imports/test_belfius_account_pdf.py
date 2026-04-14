from app.imports.belfius_account_pdf import BelfiusAccountPdfExtractor
from app.imports.pdf_text import lineize_pdf_pages
from tests.imports.fixtures.belfius_account_pages import SANITIZED_BELFIUS_PAGE_TEXTS


def test_parser_extracts_belfius_account_transactions_and_ignores_appendix_pages():
    result = BelfiusAccountPdfExtractor().extract_from_pages(
        lineize_pdf_pages(SANITIZED_BELFIUS_PAGE_TEXTS),
        raw_artifact_ref="imports/session-21/attempts/1/evidence/raw.json",
    )

    assert result.extractor_id == "belfius_account_pdf_v1"
    assert result.statement_metadata == {
        "statement_period_start": "2026-01-15",
        "statement_period_end": "2026-02-16",
        "account_number_hint": "BE46 0636 5194 6836",
        "currency": "EUR",
    }
    assert [tx.transaction_date for tx in result.transactions] == [
        "2026-01-16",
        "2026-01-16",
        "2026-01-16",
        "2026-01-19",
    ]
    assert [tx.source_description for tx in result.transactions] == [
        "MASTERCARD AFREKENING NUMMER 007",
        "INSTANT STORTING VAN MT50 CFTE 2800 4000 0000 0000 1608 098 Alexandre Arduini Tavares credit card payment NXT1QzMot-Hxt4Kqph NAAR BE46 0636 5194 6836 Alexandre Augusto Tavares",
        "INSTANT OVERSCHRIJVING BELFIUS MOBILE NAAR BE11 9502 1298 4548 ALEXANDRE ARDUINI TAVARES Loan to pay loan",
        "BANCONTACT - AANKOOP - AZ Sint-Lucas - 9000 Gent BE - 16/01/26 22:59 - 776003339729 - VIA INTERNET - KAART 5169 20XX XXXX 0612 - Arduini Tavares A",
    ]
    assert [tx.signed_amount for tx in result.transactions] == [-572.2, 637.0, -637.0, -43.56]
    assert [tx.debit_credit for tx in result.transactions] == ["debit", "credit", "debit", "debit"]
    assert [tx.source_locator for tx in result.transactions] == [
        "pdf:p1:l10-11",
        "pdf:p1:l12-16",
        "pdf:p1:l17-20",
        "pdf:p2:l5-8",
    ]
    assert result.issues == []
