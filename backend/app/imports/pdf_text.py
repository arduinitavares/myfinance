from pypdf import PdfReader


def read_pdf_page_text(file_path: str) -> list[str]:
    reader = PdfReader(file_path)
    return [page.extract_text(extraction_mode="layout") or "" for page in reader.pages]


def lineize_pdf_pages(page_texts: list[str]) -> list[dict]:
    pages = []
    for page_number, text in enumerate(page_texts, start=1):
        normalized = text.replace("\u00A0", " ").replace("\r\n", "\n").replace("\r", "\n")
        lines = []
        for line in normalized.split("\n"):
            trimmed = line.rstrip()
            if not trimmed.strip():
                continue
            lines.append({"line_number": len(lines) + 1, "text": trimmed})
        pages.append({"page_number": page_number, "raw_text": normalized, "lines": lines})
    return pages
