from copy import deepcopy

from app.imports.beobank_mastercard_pdf import AMOUNT_RE, BeobankMastercardPdfExtractor
from app.imports.pdf_text import lineize_pdf_pages
from tests.imports.fixtures.beobank_mastercard_pages import SANITIZED_BEOBANK_PAGE_TEXTS


def test_parser_extracts_transactions_metadata_and_source_locators():
    extractor = BeobankMastercardPdfExtractor()

    result = extractor.extract_from_pages(
        lineize_pdf_pages(SANITIZED_BEOBANK_PAGE_TEXTS),
        raw_artifact_ref="imports/session-1/attempts/1/evidence/raw.json",
    )

    assert result.extractor_id == "beobank_mastercard_pdf_v1"
    assert result.raw_artifact_ref == "imports/session-1/attempts/1/evidence/raw.json"
    assert result.statement_metadata == {
        "statement_period_start": "2025-12-15",
        "statement_period_end": "2026-01-14",
        "card_number_hint": "xxxx xxxx xxxx 1111",
        "currency": "EUR",
    }
    assert [tx.source_description for tx in result.transactions] == [
        "MERCADO EXTRA-1776 PRAIA GRANDE BR",
        "WISSELKOSTEN - MERCADO EXTRA-1776 PRAIA GRANDE BR",
        "CIA DO ESPETO PRAIA GRANDE BR Vervolg beschrijving",
        "TERUGBETALING",
        "ONLINE SHOP BRUSSEL BE",
    ]
    assert [tx.source_locator for tx in result.transactions] == [
        "pdf:p2:l4",
        "pdf:p2:l6-7",
        "pdf:p2:l8-9",
        "pdf:p2:l10",
        "pdf:p3:l4",
    ]
    assert [tx.signed_amount for tx in result.transactions] == [-18.19, -0.38, -21.5, 12.34, -1234.56]
    assert [tx.debit_credit for tx in result.transactions] == [
        "debit",
        "debit",
        "debit",
        "credit",
        "debit",
    ]
    assert all(tx.currency == "EUR" for tx in result.transactions)
    assert all(tx.edit_source == "deterministic_extracted" for tx in result.transactions)
    assert result.issues == []
    assert all("Vorig saldo" not in tx.source_description for tx in result.transactions)


def test_parser_blocks_multiple_distinct_card_headers():
    pages = lineize_pdf_pages(SANITIZED_BEOBANK_PAGE_TEXTS)
    pages[2]["lines"][0]["text"] = "Kaart xxxx xxxx xxxx 2222"

    result = BeobankMastercardPdfExtractor().extract_from_pages(
        pages,
        raw_artifact_ref="imports/session-2/attempts/1/evidence/raw.json",
    )

    assert any(issue.code == "multi_card_not_supported" and issue.blocking for issue in result.issues)


def test_parser_counts_distinct_card_headers_on_page_one_too():
    pages = lineize_pdf_pages(SANITIZED_BEOBANK_PAGE_TEXTS)
    pages[0]["lines"].insert(0, {"line_number": 0, "text": "Kaart xxxx xxxx xxxx 9999"})

    result = BeobankMastercardPdfExtractor().extract_from_pages(
        pages,
        raw_artifact_ref="imports/session-2b/attempts/1/evidence/raw.json",
    )

    assert any(issue.code == "multi_card_not_supported" and issue.blocking for issue in result.issues)


def test_parser_blocks_other_standalone_wisselkosten_shapes():
    page_texts = deepcopy(SANITIZED_BEOBANK_PAGE_TEXTS)
    page_texts[1] = (
        "Kaart xxxx xxxx xxxx 1111\n"
        "Uw transacties\n"
        "Datum Beschrijving Bedrag\n"
        "20/12/2025 MERCADO EXTRA-1776 PRAIA GRANDE BR 18,19\n"
        "WISSELKOSTEN\n"
        "0,38\n"
        "20/12/2025 CIA DO ESPETO PRAIA GRANDE BR 21,50\n"
    )

    result = BeobankMastercardPdfExtractor().extract_from_pages(
        lineize_pdf_pages(page_texts),
        raw_artifact_ref="imports/session-3/attempts/1/evidence/raw.json",
    )

    assert any(issue.code == "unclassifiable_table_line" and issue.blocking for issue in result.issues)
    assert "WISSELKOSTEN" not in [tx.source_description for tx in result.transactions]


def test_parser_accepts_betaling_rows_with_space_separated_thousands():
    page_texts = [
        (
            "BEOBANK\n"
            "MASTERCARD\n"
            "Uittreksel van uw kredietkaart\n"
            "Periode 01/02/2026 - 28/02/2026\n"
        ),
        (
            "Kaart xxxx xxxx xxxx 1111\n"
            "Uw transacties\n"
            "Datum Beschrijving Bedrag (in €)\n"
            "12/02/2026 BETALING IBAN BE11950212984548 Mr ALEXANDRE ARDUINI TAVARES -2 677,24\n"
            "Uw miles\n"
        ),
    ]

    result = BeobankMastercardPdfExtractor().extract_from_pages(
        lineize_pdf_pages(page_texts),
        raw_artifact_ref="imports/session-4b/attempts/1/evidence/raw.json",
    )

    assert result.issues == []
    assert len(result.transactions) == 1
    assert result.transactions[0].source_description == (
        "BETALING IBAN BE11950212984548 Mr ALEXANDRE ARDUINI TAVARES"
    )
    assert result.transactions[0].signed_amount == 2677.24
    assert result.transactions[0].debit_credit == "credit"


def test_parser_accepts_space_grouped_amounts_in_fx_helper_rows():
    page_texts = [
        (
            "BEOBANK\n"
            "MASTERCARD\n"
            "Uittreksel van uw kredietkaart\n"
            "Periode 16/02/2026 - 15/03/2026\n"
        ),
        (
            "Kaart xxxx xxxx xxxx 1111\n"
            "Uw transacties\n"
            "Datum Beschrijving Bedrag (in €)\n"
            "08/03/2026 EBN *ADOBE CURITIBA BR 1,49\n"
            "9 000,00 BRL WISSELKOERS 0.165556\n"
            "Uw miles\n"
        ),
    ]

    result = BeobankMastercardPdfExtractor().extract_from_pages(
        lineize_pdf_pages(page_texts),
        raw_artifact_ref="imports/session-4c/attempts/1/evidence/raw.json",
    )

    assert result.issues == []
    assert [tx.source_description for tx in result.transactions] == ["EBN *ADOBE CURITIBA BR"]
    assert [tx.signed_amount for tx in result.transactions] == [-1.49]


def test_parser_accepts_space_grouped_amounts_in_inline_wisselkosten_rows():
    page_texts = [
        (
            "BEOBANK\n"
            "MASTERCARD\n"
            "Uittreksel van uw kredietkaart\n"
            "Periode 16/02/2026 - 15/03/2026\n"
        ),
        (
            "Kaart xxxx xxxx xxxx 1111\n"
            "Uw transacties\n"
            "Datum Beschrijving Bedrag (in €)\n"
            "08/03/2026 EBN *ADOBE CURITIBA BR 1,49\n"
            "9,00 BRL WISSELKOERS 0.165556\n"
            "WISSELKOSTEN 1 234,56\n"
            "Uw miles\n"
        ),
    ]

    result = BeobankMastercardPdfExtractor().extract_from_pages(
        lineize_pdf_pages(page_texts),
        raw_artifact_ref="imports/session-4d/attempts/1/evidence/raw.json",
    )

    assert result.issues == []
    assert [tx.source_description for tx in result.transactions] == [
        "EBN *ADOBE CURITIBA BR",
        "WISSELKOSTEN - EBN *ADOBE CURITIBA BR",
    ]
    assert [tx.signed_amount for tx in result.transactions] == [-1.49, -1234.56]
    assert [tx.debit_credit for tx in result.transactions] == ["debit", "debit"]


def test_parser_accepts_space_grouped_amounts_in_standalone_wisselkosten_rows():
    page_texts = [
        (
            "BEOBANK\n"
            "MASTERCARD\n"
            "Uittreksel van uw kredietkaart\n"
            "Periode 16/02/2026 - 15/03/2026\n"
        ),
        (
            "Kaart xxxx xxxx xxxx 1111\n"
            "Uw transacties\n"
            "Datum Beschrijving Bedrag (in €)\n"
            "08/03/2026 EBN *ADOBE CURITIBA BR 1,49\n"
            "9 000,00 BRL WISSELKOERS 0.165556\n"
            "WISSELKOSTEN\n"
            "1 234,56\n"
            "Uw miles\n"
        ),
    ]

    result = BeobankMastercardPdfExtractor().extract_from_pages(
        lineize_pdf_pages(page_texts),
        raw_artifact_ref="imports/session-4e/attempts/1/evidence/raw.json",
    )

    assert result.issues == []
    assert [tx.source_description for tx in result.transactions] == [
        "EBN *ADOBE CURITIBA BR",
        "WISSELKOSTEN - EBN *ADOBE CURITIBA BR",
    ]
    assert [tx.signed_amount for tx in result.transactions] == [-1.49, -1234.56]
    assert [tx.debit_credit for tx in result.transactions] == ["debit", "debit"]


def test_parser_blocks_malformed_mixed_separator_row():
    page_texts = [
        (
            "BEOBANK\n"
            "MASTERCARD\n"
            "Uittreksel van uw kredietkaart\n"
            "Periode 01/02/2026 - 28/02/2026\n"
        ),
        (
            "Kaart xxxx xxxx xxxx 1111\n"
            "Uw transacties\n"
            "Datum Beschrijving Bedrag (in €)\n"
            "12/02/2026 SHOP 1.234 567,89\n"
            "Uw miles\n"
        ),
    ]

    result = BeobankMastercardPdfExtractor().extract_from_pages(
        lineize_pdf_pages(page_texts),
        raw_artifact_ref="imports/session-4f/attempts/1/evidence/raw.json",
    )

    assert any(issue.code == "unclassifiable_table_line" and issue.blocking for issue in result.issues)
    assert result.transactions == []


def test_amount_rejects_mixed_grouping_separators():
    assert not AMOUNT_RE.match("1.234 567,89")
    assert not AMOUNT_RE.match("1 234.567,89")


def test_parser_blocks_pages_with_row_candidates_but_without_transaction_marker():
    page_texts = deepcopy(SANITIZED_BEOBANK_PAGE_TEXTS)
    page_texts[2] = (
        "Kaart xxxx xxxx xxxx 1111\n"
        "21/12/2025 ONLINE SHOP BRUSSEL BE 1.234,56\n"
    )

    result = BeobankMastercardPdfExtractor().extract_from_pages(
        lineize_pdf_pages(page_texts),
        raw_artifact_ref="imports/session-4/attempts/1/evidence/raw.json",
    )

    assert any(issue.code == "unclassifiable_table_line" and issue.blocking for issue in result.issues)


def test_parser_blocks_pages_with_marker_and_rows_but_without_required_headers():
    page_texts = deepcopy(SANITIZED_BEOBANK_PAGE_TEXTS)
    page_texts[2] = (
        "Kaart xxxx xxxx xxxx 1111\n"
        "Uw transacties\n"
        "21/12/2025 ONLINE SHOP BRUSSEL BE 1.234,56\n"
    )

    result = BeobankMastercardPdfExtractor().extract_from_pages(
        lineize_pdf_pages(page_texts),
        raw_artifact_ref="imports/session-5/attempts/1/evidence/raw.json",
    )

    assert any(issue.code == "unclassifiable_table_line" and issue.blocking for issue in result.issues)


def test_parser_accepts_real_world_indented_card_headers_and_continuation_pages():
    page_texts = [
        (
            "BEOBANK\n"
            "MASTERCARD\n"
            "Uittreksel van uw kredietkaart\n"
            "Periode 16/12/2025 - 15/01/2026\n"
        ),
        (
            "Uw transacties\n"
            "Datum Beschrijving Bedrag (in €)\n"
            "    Kaart xxxx xxxx xxxx 1111\n"
            "15/12/2025 DE TRAITEUR BV GENT BE 14,20\n"
        ),
        (
            "Datum Beschrijving Bedrag (in €)\n"
            "08/01/2026 OPENAI *CHATGPT SUBSCR DUBLIN IE 23,00\n"
            "    10,80 USD WISSELKOERS 0.861112\n"
            "    WISSELKOSTEN\n"
            "    0,20\n"
            "Uw miles\n"
            "Miles\n"
            "Vorig saldo 12.438\n"
        ),
    ]

    result = BeobankMastercardPdfExtractor().extract_from_pages(
        lineize_pdf_pages(page_texts),
        raw_artifact_ref="imports/session-6/attempts/1/evidence/raw.json",
    )

    assert result.issues == []
    assert [tx.source_description for tx in result.transactions] == [
        "DE TRAITEUR BV GENT BE",
        "OPENAI *CHATGPT SUBSCR DUBLIN IE",
        "WISSELKOSTEN - OPENAI *CHATGPT SUBSCR DUBLIN IE",
    ]
    assert [tx.source_locator for tx in result.transactions] == [
        "pdf:p2:l4",
        "pdf:p3:l2",
        "pdf:p3:l4-5",
    ]


def test_parser_carries_transaction_date_to_fee_only_continuation_page():
    page_texts = [
        (
            "BEOBANK\n"
            "MASTERCARD\n"
            "Uittreksel van uw kredietkaart\n"
            "Periode 16/12/2025 - 15/01/2026\n"
        ),
        (
            "Uw transacties\n"
            "Datum Beschrijving Bedrag (in €)\n"
            "14/01/2026 AIRLINE SHOP BRUSSELS BE 100,00\n"
        ),
        (
            "Datum Beschrijving Bedrag (in €)\n"
            "    10,80 USD WISSELKOERS 0.861112\n"
            "    WISSELKOSTEN\n"
            "    0,20\n"
            "Uw miles\n"
        ),
    ]

    result = BeobankMastercardPdfExtractor().extract_from_pages(
        lineize_pdf_pages(page_texts),
        raw_artifact_ref="imports/session-7/attempts/1/evidence/raw.json",
    )

    assert result.issues == []
    assert [tx.transaction_date for tx in result.transactions] == [
        "2026-01-14",
        "2026-01-14",
    ]
    assert [tx.source_description for tx in result.transactions] == [
        "AIRLINE SHOP BRUSSELS BE",
        "WISSELKOSTEN - AIRLINE SHOP BRUSSELS BE",
    ]
    assert [tx.source_locator for tx in result.transactions] == [
        "pdf:p2:l3",
        "pdf:p3:l3-4",
    ]


def test_parser_splits_inline_wisselkosten_rows_from_real_world_layout():
    page_texts = [
        (
            "BEOBANK\n"
            "MASTERCARD\n"
            "Uittreksel van uw kredietkaart\n"
            "Periode 16/02/2026 - 15/03/2026\n"
        ),
        (
            "Kaart xxxx xxxx xxxx 1111\n"
            "Uw transacties\n"
            "Datum Beschrijving Bedrag (in €)\n"
            "08/03/2026 EBN *ADOBE CURITIBA BR 1,49\n"
            "9,00 BRL WISSELKOERS 0.165556\n"
            "WISSELKOSTEN 0,03\n"
            "09/03/2026 CLUBE BANCORBRAS BRASILIA BR 62,66\n"
            "379,00 BRL WISSELKOERS 0.165330\n"
            "WISSELKOSTEN 1,32\n"
            "Uw miles\n"
        ),
    ]

    result = BeobankMastercardPdfExtractor().extract_from_pages(
        lineize_pdf_pages(page_texts),
        raw_artifact_ref="imports/session-8/evidence/raw.json",
    )

    assert result.issues == []
    assert [tx.source_description for tx in result.transactions] == [
        "EBN *ADOBE CURITIBA BR",
        "WISSELKOSTEN - EBN *ADOBE CURITIBA BR",
        "CLUBE BANCORBRAS BRASILIA BR",
        "WISSELKOSTEN - CLUBE BANCORBRAS BRASILIA BR",
    ]
    assert [tx.signed_amount for tx in result.transactions] == [-1.49, -0.03, -62.66, -1.32]
    assert [tx.source_locator for tx in result.transactions] == [
        "pdf:p2:l4",
        "pdf:p2:l6",
        "pdf:p2:l7",
        "pdf:p2:l9",
    ]
