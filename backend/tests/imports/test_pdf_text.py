"""Module for backend tests imports test_pdf_text."""

from pathlib import Path

import pytest
from app.imports.pdf_text import lineize_pdf_pages, read_pdf_page_text


def test_read_pdf_page_text_uses_layout_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify read pdf page text uses layout extraction."""
    calls: list[str | None] = []

    class FakePage:
        def __init__(self, text: str | None) -> None:
            self.text = text

        def extract_text(self, extraction_mode: str | None = None) -> str | None:
            calls.append(extraction_mode)
            return self.text

    class FakeReader:
        def __init__(self, file_path: str) -> None:
            self.file_path = file_path
            self.pages = [FakePage("Page 1"), FakePage(None)]

    monkeypatch.setattr("app.imports.pdf_text.PdfReader", FakeReader)

    page_texts = read_pdf_page_text(str(Path("/statement.pdf")))

    assert page_texts == ["Page 1", ""]
    assert calls == ["layout", "layout"]


def test_lineize_pdf_pages_normalizes_whitespace_and_numbers_lines_from_one() -> None:
    """Verify lineize pdf pages normalizes whitespace and numbers lines from one."""
    pages = lineize_pdf_pages(
        [
            "Header\r\n\r\nSecond line\u00a0 \n",
            "Uw transacties\nDatum Beschrijving Bedrag\n15/12/2025 TEST 12,34\n",
        ]
    )

    assert pages == [
        {
            "page_number": 1,
            "raw_text": "Header\n\nSecond line  \n",
            "lines": [
                {"line_number": 1, "text": "Header"},
                {"line_number": 2, "text": "Second line"},
            ],
        },
        {
            "page_number": 2,
            "raw_text": (
                "Uw transacties\n"
                "Datum Beschrijving Bedrag\n"
                "15/12/2025 TEST 12,34\n"
            ),
            "lines": [
                {"line_number": 1, "text": "Uw transacties"},
                {"line_number": 2, "text": "Datum Beschrijving Bedrag"},
                {"line_number": 3, "text": "15/12/2025 TEST 12,34"},
            ],
        },
    ]
