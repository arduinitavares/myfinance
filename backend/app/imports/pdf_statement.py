"""Module for backend app imports pdf_statement."""

from pathlib import Path

from .belfius_account_pdf import BelfiusAccountPdfExtractor
from .belfius_card_pdf import BelfiusCardPdfExtractor
from .beobank_mastercard_pdf import BeobankMastercardPdfExtractor
from .contracts import ExtractionResult, ImportIssue, RawEvidence
from .pdf_text import lineize_pdf_pages, read_pdf_page_text


class PdfStatementExtractor:
    """Represent pdf statement extractor."""

    def __init__(
        self,
        extractors: list[
            BelfiusCardPdfExtractor
            | BelfiusAccountPdfExtractor
            | BeobankMastercardPdfExtractor
        ]
        | None = None,
    ) -> None:
        """Initialize the instance."""
        self.extractors = extractors or [
            BelfiusCardPdfExtractor(),
            BelfiusAccountPdfExtractor(),
            BeobankMastercardPdfExtractor(),
        ]

    def extract(
        self, *, file_path: str | Path, session_id: str, attempt_number: int
    ) -> tuple[RawEvidence, ExtractionResult]:
        """Handle extract."""
        raw_artifact_ref = (
            f"imports/{session_id}/attempts/{attempt_number}/evidence/raw.json"
        )
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
                        code="unsupported_pdf_statement_layout",
                        message=(
                            "The PDF statement does not match a supported "
                            "deterministic PDF layout."
                        ),
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
                    message=(
                        "No valid transaction rows were extracted from the PDF "
                        "statement."
                    ),
                    blocking=True,
                )
            )

        if issues != result.issues:
            result = result.model_copy(
                update={"issues": issues, "overall_confidence": 0.0}
            )

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

        return [
            ImportIssue(
                code="empty_transaction_page",
                message=(
                    f"Transaction page {page['page_number']} does not contain "
                    "extractable text."
                ),
                blocking=True,
            )
            for page in pages[1:]
            if not page["lines"]
        ]

    def _select_extractor(
        self,
        pages: list[dict],
    ) -> (
        BelfiusCardPdfExtractor
        | BelfiusAccountPdfExtractor
        | BeobankMastercardPdfExtractor
        | None
    ):
        if self._looks_like_belfius_card_statement(pages):
            return self.extractors[0]
        if self._looks_like_belfius_account(pages):
            return self.extractors[1]
        if self._looks_like_beobank_mastercard(pages):
            return self.extractors[2]
        return None

    @staticmethod
    def _looks_like_belfius_card_statement(pages: list[dict]) -> bool:
        if not pages:
            return False
        first_page_lines = [
            " ".join(line["text"].split()).casefold() for line in pages[0]["lines"]
        ]
        first_page_text = "\n".join(first_page_lines)
        has_belfius = "belfius bank nv" in first_page_text
        has_card_markers = (
            "uitgavenstaat" in first_page_text and "kaartnummer" in first_page_text
        )
        has_rows = any(
            any(
                line_text[:5].count("/") >= 1 and "eur" in line_text
                for line_text in (
                    " ".join(line["text"].split()).casefold() for line in page["lines"]
                )
            )
            for page in pages
        )
        return has_belfius and has_card_markers and has_rows

    @staticmethod
    def _looks_like_belfius_account(pages: list[dict]) -> bool:
        if not pages:
            return False
        first_page_lines = [
            " ".join(line["text"].split()).casefold() for line in pages[0]["lines"]
        ]
        first_page_text = "\n".join(first_page_lines)
        has_account = any("be" in line and "bic:" in line for line in first_page_lines)
        has_belfius = "belfius bank nv" in first_page_text
        has_statement_marker = (
            "datum :" in first_page_text or "beats star-rekening" in first_page_text
        )
        has_rows = any(
            any(
                line["text"].strip()[:4].isdigit() and "(VAL." in line["text"]
                for line in page["lines"]
            )
            for page in pages
        )
        return has_belfius and has_statement_marker and has_account and has_rows

    @staticmethod
    def _looks_like_beobank_mastercard(pages: list[dict]) -> bool:
        first_page_lines = [
            " ".join(line["text"].split()).casefold()
            for line in (pages[0]["lines"] if pages else [])
        ]
        first_page_text = "\n".join(first_page_lines)
        page_tokens = {token for line in first_page_lines for token in line.split()}
        return (
            "uittreksel van uw kredietkaart" in first_page_text
            and "beobank" in page_tokens
            and "mastercard" in page_tokens
        )

    @staticmethod
    def _failure_result(
        *, extractor_id: str, raw_artifact_ref: str, issues: list[ImportIssue]
    ) -> ExtractionResult:
        return ExtractionResult(
            extractor_id=extractor_id,
            raw_artifact_ref=raw_artifact_ref,
            source_metadata={"provider_hint": "unknown", "file_type": "pdf"},
            statement_metadata={},
            transactions=[],
            issues=issues,
            overall_confidence=0.0,
        )
