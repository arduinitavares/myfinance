"""Module for backend app imports belfius_card_pdf."""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from .contracts import ExtractedTransaction, ExtractionResult, ImportIssue

ROW_RE: Any = re.compile(
    r"^(?P<transaction_day>\d{2}/\d{2})\s+(?P<settlement_day>\d{2}/\d{2})\s+(?P<body>.+?)\s+(?:(?P<foreign_amount>\d{1,3}(?:\.\d{3})*|\d+,\d{2})\s+[A-Z]{3}\s+)?(?P<eur_amount>\d{1,3}(?:\.\d{3})*|\d+,\d{2})\s+EUR\s+(?P<sign>-)?$"
)
PERIOD_RE: Any = re.compile(
    r"Transacties van\s+(\d{2}/\d{2}/\d{4})\s+tot\s+(\d{2}/\d{2}/\d{4})", re.IGNORECASE
)
CARD_RE: Any = re.compile(r"Kaartnummer\s+([0-9X ]{19,})", re.IGNORECASE)
FX_RATE_LINE_RE: Any = re.compile(r"^\d+(?:,\d+)?(?:\.\d+)?[A-Z]{3}$")
INLINE_FX_HELPER_RE: Any = re.compile(r"\s+1 EUR =$")


@dataclass(frozen=True)
class _CardRowStart:
    page_number: int
    line_number: int
    text: str
    period_start: str
    period_end: str


def _collapse_spaces(text: str) -> str:
    return " ".join(text.split())


def _to_iso_date(value: str) -> str:
    return datetime.strptime(value, "%d/%m/%Y").replace(tzinfo=UTC).date().isoformat()


def _parse_eur_amount(amount_text: str, sign: str | None) -> tuple[float, str]:
    absolute_amount = float(amount_text.replace(".", "").replace(",", "."))
    if absolute_amount == 0:
        msg = "zero amount not allowed"
        raise ValueError(msg)
    if sign == "-":
        return -absolute_amount, "debit"
    return absolute_amount, "credit"


def _infer_transaction_date(
    day_month: str, statement_start: str, statement_end: str
) -> str:
    start = date.fromisoformat(statement_start)
    end = date.fromisoformat(statement_end)
    day, month = map(int, day_month.split("/"))

    for candidate_year in (start.year, end.year):
        try:
            candidate = date(candidate_year, month, day)
        except ValueError:
            continue
        if start <= candidate <= end:
            return candidate.isoformat()

    if start.year == end.year:
        return date(start.year, month, day).isoformat()
    if month >= start.month:
        return date(start.year, month, day).isoformat()
    return date(end.year, month, day).isoformat()


class BelfiusCardPdfExtractor:
    """Represent belfius card pdf extractor."""

    extractor_id = "belfius_card_pdf_v1"

    def extract_from_pages(
        self, pages: list[dict], raw_artifact_ref: str
    ) -> ExtractionResult:
        """Handle extract from pages."""
        issues: list[ImportIssue] = []
        transactions: list[ExtractedTransaction] = []
        statement_metadata = self._extract_statement_metadata(pages)

        for page in pages:
            if not self._page_has_transaction_rows(page):
                continue
            transactions.extend(
                self._parse_transaction_page(page, statement_metadata, issues)
            )

        return ExtractionResult(
            extractor_id=self.extractor_id,
            raw_artifact_ref=raw_artifact_ref,
            source_metadata={
                "provider_hint": "belfius",
                "file_type": "pdf",
                "language": "nl",
            },
            statement_metadata=statement_metadata,
            transactions=transactions,
            issues=issues,
            overall_confidence=0.0 if any(issue.blocking for issue in issues) else 1.0,
        )

    def _extract_statement_metadata(self, pages: list[dict]) -> dict:
        metadata = {"currency": "EUR"}

        for page in pages:
            for line in page["lines"]:
                text = _collapse_spaces(line["text"])

                if "statement_period_start" not in metadata:
                    period_match = PERIOD_RE.search(text)
                    if period_match:
                        metadata["statement_period_start"] = _to_iso_date(
                            period_match.group(1)
                        )
                        metadata["statement_period_end"] = _to_iso_date(
                            period_match.group(2)
                        )

                if "card_number_hint" not in metadata:
                    card_match = CARD_RE.search(text)
                    if card_match:
                        metadata["card_number_hint"] = _collapse_spaces(
                            card_match.group(1)
                        )

        return metadata

    def _parse_transaction_page(
        self,
        page: dict,
        statement_metadata: dict,
        issues: list[ImportIssue],
    ) -> list[ExtractedTransaction]:
        transactions: list[ExtractedTransaction] = []
        current_row: dict | None = None
        started = False
        after_total = False

        period_start = statement_metadata.get("statement_period_start")
        period_end = statement_metadata.get("statement_period_end")
        if not period_start or not period_end:
            issues.append(
                ImportIssue(
                    code="missing_statement_period",
                    message="Belfius card statement period could not be determined.",
                    blocking=True,
                )
            )
            return transactions

        for line in page["lines"]:
            text = _collapse_spaces(line["text"])
            line_number = line["line_number"]

            if after_total:
                continue

            row_match = ROW_RE.match(text)
            if row_match:
                started = True
                self._append_current_row(page["page_number"], current_row, transactions)
                current_row = self._start_transaction_row(
                    row_match,
                    _CardRowStart(
                        page_number=page["page_number"],
                        line_number=line_number,
                        text=text,
                        period_start=period_start,
                        period_end=period_end,
                    ),
                    issues,
                )
                continue

            if not started:
                continue

            if text.startswith("Totaal"):
                self._append_current_row(page["page_number"], current_row, transactions)
                current_row = None
                after_total = True
                continue

            if current_row is None:
                continue

            if self._is_fx_helper_line(text):
                continue

            cleaned_text = self._clean_continuation_text(text)
            if cleaned_text:
                current_row["description_parts"].append(cleaned_text)
                current_row["end_line"] = line_number

        self._append_current_row(page["page_number"], current_row, transactions)

        return transactions

    def _append_current_row(
        self,
        page_number: int,
        current_row: dict | None,
        transactions: list[ExtractedTransaction],
    ) -> None:
        if current_row is not None:
            transactions.append(self._build_transaction(page_number, current_row))

    def _start_transaction_row(
        self,
        row_match: re.Match[str],
        row_start: _CardRowStart,
        issues: list[ImportIssue],
    ) -> dict | None:
        try:
            signed_amount, debit_credit = _parse_eur_amount(
                row_match.group("eur_amount"), row_match.group("sign")
            )
        except ValueError:
            issues.append(
                self._unclassifiable_issue(
                    row_start.page_number,
                    row_start.line_number,
                    row_start.text,
                )
            )
            return None

        return {
            "transaction_date": _infer_transaction_date(
                row_match.group("transaction_day"),
                row_start.period_start,
                row_start.period_end,
            ),
            "signed_amount": signed_amount,
            "debit_credit": debit_credit,
            "start_line": row_start.line_number,
            "end_line": row_start.line_number,
            "description_parts": [row_match.group("body")],
        }

    @staticmethod
    def _page_has_transaction_rows(page: dict) -> bool:
        return any(
            ROW_RE.match(_collapse_spaces(line["text"])) for line in page["lines"]
        )

    @staticmethod
    def _is_fx_helper_line(text: str) -> bool:
        return text == "1 EUR =" or bool(FX_RATE_LINE_RE.match(text))

    @staticmethod
    def _clean_continuation_text(text: str) -> str:
        return INLINE_FX_HELPER_RE.sub("", text).strip()

    @staticmethod
    def _build_transaction(page_number: int, row: dict) -> ExtractedTransaction:
        locator = f"pdf:p{page_number}:l{row['start_line']}"
        if row["end_line"] != row["start_line"]:
            locator += f"-{row['end_line']}"

        return ExtractedTransaction(
            transaction_date=row["transaction_date"],
            source_description=" ".join(row["description_parts"]).strip(),
            signed_amount=row["signed_amount"],
            currency="EUR",
            debit_credit=row["debit_credit"],
            source_locator=locator,
            edit_source="deterministic_extracted",
        )

    @staticmethod
    def _unclassifiable_issue(
        page_number: int, line_number: int, text: str
    ) -> ImportIssue:
        return ImportIssue(
            code="unclassifiable_table_line",
            message=(
                f"Unclassifiable Belfius card line on page {page_number}, "
                f"line {line_number}: {text}"
            ),
            blocking=True,
            transaction_ref=f"pdf:p{page_number}:l{line_number}",
        )
