from pathlib import Path

from .beobank_mastercard_pdf import BeobankMastercardPdfExtractor
from .contracts import ExtractionResult, ImportIssue, RawEvidence
from .pdf_text import lineize_pdf_pages, read_pdf_page_text


class PdfStatementExtractor:
    def __init__(self, extractors: list[BeobankMastercardPdfExtractor] | None = None) -> None:
        self.extractors = extractors or [BeobankMastercardPdfExtractor()]

    def extract(self, *, file_path: str | Path, session_id: str, attempt_number: int) -> tuple[RawEvidence, ExtractionResult]:
        raw_artifact_ref = f"imports/{session_id}/attempts/{attempt_number}/evidence/raw.json"
        page_texts = read_pdf_page_text(str(file_path))
        pages = lineize_pdf_pages(page_texts)
        evidence = RawEvidence(
            text_blocks=[
                {
                    "page_number": page["page_number"],
                    "raw_text": page["raw_text"],
                    "lines": [line["text"] for line in page["lines"]],
                }
                for page in pages
            ],
            ocr_blocks=[],
            snippets=[],
        )

        preflight_issues = self._collect_preflight_issues(pages)
        if preflight_issues:
            return evidence, self._failure_result(
                extractor_id="pdf_statement_chain_v1",
                raw_artifact_ref=raw_artifact_ref,
                issues=preflight_issues,
            )

        extractor = self._select_extractor(pages)
        if extractor is None:
            return evidence, self._failure_result(
                extractor_id="pdf_statement_chain_v1",
                raw_artifact_ref=raw_artifact_ref,
                issues=[
                    ImportIssue(
                        code="unsupported_beobank_mastercard_layout",
                        message="The PDF statement does not match the supported Beobank Mastercard layout.",
                        blocking=True,
                    )
                ],
            )

        result = extractor.extract_from_pages(pages, raw_artifact_ref=raw_artifact_ref)
        issues = list(result.issues)
        if not result.transactions:
            issues.append(
                ImportIssue(
                    code="empty_transaction_page",
                    message="No valid transaction rows were extracted from the PDF statement.",
                    blocking=True,
                )
            )

        if issues != result.issues:
            result = result.model_copy(update={"issues": issues, "overall_confidence": 0.0})

        return evidence, result

    def _collect_preflight_issues(self, pages: list[dict]) -> list[ImportIssue]:
        if not pages or all(not page["lines"] for page in pages):
            return [
                ImportIssue(
                    code="image_only_pdf",
                    message="The PDF statement does not contain a usable text layer.",
                    blocking=True,
                )
            ]

        issues = []
        for page in pages[1:]:
            if not page["lines"]:
                issues.append(
                    ImportIssue(
                        code="empty_transaction_page",
                        message=f"Transaction page {page['page_number']} does not contain extractable text.",
                        blocking=True,
                    )
                )
        return issues

    def _select_extractor(self, pages: list[dict]) -> BeobankMastercardPdfExtractor | None:
        if self._looks_like_beobank_mastercard(pages):
            return self.extractors[0]
        return None

    @staticmethod
    def _looks_like_beobank_mastercard(pages: list[dict]) -> bool:
        first_page_lines = [" ".join(line["text"].split()).casefold() for line in (pages[0]["lines"] if pages else [])]
        first_page_text = "\n".join(first_page_lines)
        page_tokens = {token for line in first_page_lines for token in line.split()}
        return (
            "uittreksel van uw kredietkaart" in first_page_text
            and "beobank" in page_tokens
            and "mastercard" in page_tokens
        )

    @staticmethod
    def _failure_result(*, extractor_id: str, raw_artifact_ref: str, issues: list[ImportIssue]) -> ExtractionResult:
        return ExtractionResult(
            extractor_id=extractor_id,
            raw_artifact_ref=raw_artifact_ref,
            source_metadata={"provider_hint": "unknown", "file_type": "pdf"},
            statement_metadata={},
            transactions=[],
            issues=issues,
            overall_confidence=0.0,
        )
