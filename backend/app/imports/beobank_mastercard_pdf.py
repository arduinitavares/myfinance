"""Module for backend app imports beobank_mastercard_pdf."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .contracts import ExtractedTransaction, ExtractionResult, ImportIssue

AMOUNT_BODY: Any = r"(?:\d{1,3}(?:\.\d{3})+|\d{1,3}(?: \d{3})+|\d+),\d{2}"
SIGNED_AMOUNT_BODY: Any = rf"-?{AMOUNT_BODY}"
AMOUNT_RE: Any = re.compile(rf"^{SIGNED_AMOUNT_BODY}$")
ROW_RE: Any = re.compile(
    rf"^(?P<date>\d{{2}}/\d{{2}}/\d{{4}})\s+(?P<description>.+?)\s+(?P<amount>{SIGNED_AMOUNT_BODY})$"
)
MALFORMED_ROW_RE: Any = re.compile(
    r"^(?P<date>\d{2}/\d{2}/\d{4})\s+(?P<description>.+?)\s+"
    r"(?P<amount>-?(?=[^,]*\.)(?=[^,]* )\d{1,3}(?:[. ]\d{3})+,\d{2})$"
)
FX_HELPER_RE: Any = re.compile(
    rf"^(?P<amount>{AMOUNT_BODY})\s+[A-Z]{{3}}\s+WISSELKOERS\s+\d+(?:\.\d+)?$",
    re.IGNORECASE,
)
INLINE_WISSELKOSTEN_RE: Any = re.compile(
    rf"^WISSELKOSTEN\s+(?P<amount>{SIGNED_AMOUNT_BODY})$",
    re.IGNORECASE,
)
MALFORMED_FX_HELPER_RE: Any = re.compile(
    r"^(?P<amount>-?(?=[^,]*\.)(?=[^,]* )\d{1,3}(?:[. ]\d{3})+,\d{2})"
    r"\s+[A-Z]{3}\s+WISSELKOERS\s+\d+(?:\.\d+)?$",
    re.IGNORECASE,
)
PAGE_FOOTER_RE: Any = re.compile(r"^(?:Blz\s+\d+|KB\..+)$", re.IGNORECASE)
CARD_HEADER_RE: Any = re.compile(r"^Kaart\s+(?P<card>.+)$", re.IGNORECASE)
DATE_RE: Any = re.compile(r"^\d{2}/\d{2}/\d{4}$")
PERIOD_RE: Any = re.compile(
    r"(?P<start>\d{2}/\d{2}/\d{4})\s*[-\u2013]\s*(?P<end>\d{2}/\d{2}/\d{4})"
)
MIN_MARKERLESS_TRANSACTION_PAGE: int = 2
IGNORED_LINE_CLASSES: set[str] = {
    "card_header",
    "table_header",
    "fx_helper",
    "page_footer_noise",
}
MALFORMED_LINE_CLASSES: set[str] = {
    "malformed_fx_helper_candidate",
    "malformed_row_candidate",
}


@dataclass
class _ParseState:
    current_row: dict | None
    last_transaction_date: str | None
    last_transaction_description: str | None


@dataclass(frozen=True)
class _LineContext:
    page_number: int
    body_lines: list[dict]
    index: int


def _collapse_token(text: str) -> str:
    return " ".join(text.split()).casefold()


def _to_iso_date(value: str) -> str:
    return datetime.strptime(value, "%d/%m/%Y").replace(tzinfo=UTC).date().isoformat()


def _parse_amount_text(amount_text: str) -> tuple[float, str]:
    if not AMOUNT_RE.match(amount_text):
        msg = f"invalid amount: {amount_text}"
        raise ValueError(msg)

    absolute_amount = float(
        amount_text.lstrip("-").replace(" ", "").replace(".", "").replace(",", ".")
    )
    if absolute_amount == 0:
        msg = f"zero amount not allowed: {amount_text}"
        raise ValueError(msg)

    if amount_text.startswith("-"):
        return absolute_amount, "credit"
    return -absolute_amount, "debit"


class BeobankMastercardPdfExtractor:
    """Represent beobank mastercard pdf extractor."""

    extractor_id = "beobank_mastercard_pdf_v1"

    def extract_from_pages(
        self, pages: list[dict], raw_artifact_ref: str
    ) -> ExtractionResult:
        """Handle extract from pages."""
        issues: list[ImportIssue] = []
        transactions: list[ExtractedTransaction] = []
        statement_metadata = self._extract_statement_metadata(pages)
        last_transaction_date: str | None = None
        last_transaction_description: str | None = None

        card_headers = self._collect_card_headers(pages)
        if len(card_headers) > 1:
            issues.append(
                ImportIssue(
                    code="multi_card_not_supported",
                    message=(
                        "More than one distinct card header was detected in the "
                        "statement."
                    ),
                    blocking=True,
                )
            )

        for page in pages:
            if page["page_number"] == 1:
                continue
            last_transaction_date, last_transaction_description = (
                self._parse_transaction_page(
                    page,
                    transactions,
                    issues,
                    last_transaction_date,
                    last_transaction_description,
                )
            )

        return ExtractionResult(
            extractor_id=self.extractor_id,
            raw_artifact_ref=raw_artifact_ref,
            source_metadata={
                "provider_hint": "beobank",
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
                text = " ".join(line["text"].split())
                if "statement_period_start" not in metadata:
                    period_match = PERIOD_RE.search(text)
                    if period_match:
                        metadata["statement_period_start"] = _to_iso_date(
                            period_match.group("start")
                        )
                        metadata["statement_period_end"] = _to_iso_date(
                            period_match.group("end")
                        )

                if "card_number_hint" not in metadata:
                    card_match = CARD_HEADER_RE.match(text)
                    if card_match:
                        metadata["card_number_hint"] = " ".join(
                            card_match.group("card").split()
                        )

        return metadata

    def _collect_card_headers(self, pages: list[dict]) -> set[str]:
        headers: set[str] = set()
        for page in pages:
            for line in page["lines"]:
                card_match = CARD_HEADER_RE.match(" ".join(line["text"].split()))
                if card_match:
                    headers.add(_collapse_token(card_match.group("card")))
        return headers

    def _parse_transaction_page(
        self,
        page: dict,
        transactions: list[ExtractedTransaction],
        issues: list[ImportIssue],
        last_transaction_date: str | None,
        last_transaction_description: str | None,
    ) -> tuple[str | None, str | None]:
        lines = page["lines"]
        if not lines:
            return last_transaction_date, last_transaction_description

        body_start = self._body_start_index(page, lines, issues)
        if body_start is None:
            return last_transaction_date, last_transaction_description

        state = _ParseState(
            current_row=None,
            last_transaction_date=last_transaction_date,
            last_transaction_description=last_transaction_description,
        )
        body_lines = lines[body_start:]
        index = 0
        while index < len(body_lines):
            step = self._process_body_line(
                _LineContext(page["page_number"], body_lines, index),
                transactions,
                issues,
                state,
            )
            if step is None:
                break
            index += step

        self._flush_current_row(page["page_number"], transactions, state)
        return state.last_transaction_date, state.last_transaction_description

    def _body_start_index(
        self, page: dict, lines: list[dict], issues: list[ImportIssue]
    ) -> int | None:
        marker_index = self._find_line_index(lines, "Uw transacties")
        if marker_index is None:
            return self._body_start_without_marker(page, lines, issues)

        body_start = marker_index + 1
        first_content_index = self._find_first_table_content_index(lines, body_start)
        if first_content_index is None:
            return None
        if self._has_required_headers(lines, marker_index, first_content_index):
            return body_start

        issues.append(
            ImportIssue(
                code="unclassifiable_table_line",
                message=(
                    "Missing Dutch transaction table headers before first "
                    f"row on page {page['page_number']}."
                ),
                blocking=True,
            )
        )
        return None

    def _body_start_without_marker(
        self, page: dict, lines: list[dict], issues: list[ImportIssue]
    ) -> int | None:
        first_content_index = self._find_first_table_content_index(lines, 0)
        if first_content_index is None:
            return None
        if page["page_number"] > MIN_MARKERLESS_TRANSACTION_PAGE and (
            self._has_required_headers(lines, -1, first_content_index)
        ):
            return 0

        issues.append(
            ImportIssue(
                code="unclassifiable_table_line",
                message=(
                    "Missing Dutch transaction marker before row-like "
                    f"content on page {page['page_number']}."
                ),
                blocking=True,
            )
        )
        return None

    def _flush_current_row(
        self,
        page_number: int,
        transactions: list[ExtractedTransaction],
        state: _ParseState,
    ) -> None:
        if state.current_row is None:
            return
        transactions.append(self._build_transaction(page_number, state.current_row))
        state.last_transaction_date = state.current_row["transaction_date"]
        state.last_transaction_description = self._joined_description(state.current_row)
        state.current_row = None

    def _process_body_line(
        self,
        context: _LineContext,
        transactions: list[ExtractedTransaction],
        issues: list[ImportIssue],
        state: _ParseState,
    ) -> int | None:
        line = context.body_lines[context.index]
        line_number = line["line_number"]
        text = line["text"]
        if _collapse_token(text) == "uw miles":
            self._flush_current_row(context.page_number, transactions, state)
            step = None
        elif self._is_malformed_standalone_wisselkosten(
            context.body_lines, context.index
        ):
            issues.append(
                self._unclassifiable_issue(context.page_number, line_number, text)
            )
            step = 2
        elif self._is_standalone_wisselkosten(context.body_lines, context.index):
            step = self._handle_standalone_wisselkosten(
                context, transactions, issues, state
            )
        elif self._is_inline_wisselkosten(text):
            step = self._handle_inline_wisselkosten(
                context, transactions, issues, state
            )
        else:
            step = self._handle_classified_line(context, transactions, issues, state)
        return step

    def _handle_classified_line(
        self,
        context: _LineContext,
        transactions: list[ExtractedTransaction],
        issues: list[ImportIssue],
        state: _ParseState,
    ) -> int:
        line = context.body_lines[context.index]
        line_number = line["line_number"]
        text = line["text"]
        line_class = self._classify_line(text, state.current_row is not None)
        if line_class in IGNORED_LINE_CLASSES:
            return 1
        if line_class in MALFORMED_LINE_CLASSES:
            issues.append(
                self._unclassifiable_issue(context.page_number, line_number, text)
            )
            return 1
        if line_class == "row_start":
            self._flush_current_row(context.page_number, transactions, state)
            state.current_row = self._build_row_candidate(line_number, text)
            return 1
        if line_class == "continuation":
            return self._handle_continuation(context, issues, state)
        issues.append(
            self._unclassifiable_issue(context.page_number, line_number, text)
        )
        return 1

    def _inherited_fee_date(self, state: _ParseState) -> str | None:
        if state.current_row is not None:
            return state.current_row["transaction_date"]
        return state.last_transaction_date

    def _handle_standalone_wisselkosten(
        self,
        context: _LineContext,
        transactions: list[ExtractedTransaction],
        issues: list[ImportIssue],
        state: _ParseState,
    ) -> int:
        line = context.body_lines[context.index]
        inherited_date = self._inherited_fee_date(state)
        if inherited_date is None:
            issues.append(
                self._unclassifiable_issue(
                    context.page_number, line["line_number"], line["text"]
                )
            )
            return 1

        fee_context = self._fee_context_description(
            state.current_row, state.last_transaction_description
        )
        self._flush_current_row(context.page_number, transactions, state)
        fee_amount_line = context.body_lines[context.index + 1]
        fee_row = self._build_standalone_wisselkosten_row(
            transaction_date=inherited_date,
            fee_context=fee_context,
            start_line=line["line_number"],
            end_line=fee_amount_line["line_number"],
            amount_text=fee_amount_line["text"],
        )
        transactions.append(self._build_transaction(context.page_number, fee_row))
        state.last_transaction_date = inherited_date
        return 2

    def _handle_inline_wisselkosten(
        self,
        context: _LineContext,
        transactions: list[ExtractedTransaction],
        issues: list[ImportIssue],
        state: _ParseState,
    ) -> int:
        line = context.body_lines[context.index]
        line_number = line["line_number"]
        text = line["text"]
        inherited_date = self._inherited_fee_date(state)
        if inherited_date is None:
            issues.append(
                self._unclassifiable_issue(context.page_number, line_number, text)
            )
            return 1

        fee_context = self._fee_context_description(
            state.current_row, state.last_transaction_description
        )
        self._flush_current_row(context.page_number, transactions, state)
        fee_row = self._build_inline_wisselkosten_row(
            transaction_date=inherited_date,
            fee_context=fee_context,
            line_number=line_number,
            text=text,
        )
        transactions.append(self._build_transaction(context.page_number, fee_row))
        state.last_transaction_date = inherited_date
        return 1

    def _handle_continuation(
        self,
        context: _LineContext,
        issues: list[ImportIssue],
        state: _ParseState,
    ) -> int:
        line = context.body_lines[context.index]
        line_number = line["line_number"]
        text = line["text"]
        if state.current_row is None:
            issues.append(
                self._unclassifiable_issue(context.page_number, line_number, text)
            )
            return 1
        state.current_row["description_parts"].append(" ".join(text.split()))
        state.current_row["end_line"] = line_number
        return 1

    def _find_line_index(self, lines: list[dict], token: str) -> int | None:
        needle = _collapse_token(token)
        for index, line in enumerate(lines):
            if _collapse_token(line["text"]) == needle:
                return index
        return None

    def _find_first_table_content_index(
        self, lines: list[dict], start_index: int
    ) -> int | None:
        for index, line in enumerate(lines[start_index:], start=start_index):
            if self._classify_line(line["text"], has_active_row=False) == "row_start":
                return index
            if (
                self._classify_line(line["text"], has_active_row=False)
                == "malformed_fx_helper_candidate"
            ):
                return index
            if (
                self._classify_line(line["text"], has_active_row=False)
                == "malformed_row_candidate"
            ):
                return index
            if self._is_malformed_standalone_wisselkosten(lines, index):
                return index
            if self._is_standalone_wisselkosten(lines, index):
                return index
        return None

    def _has_required_headers(
        self, lines: list[dict], marker_index: int, first_row_index: int
    ) -> bool:
        header_tokens = {"datum": False, "beschrijving": False, "bedrag": False}
        for line in lines[marker_index + 1 : first_row_index]:
            collapsed = _collapse_token(line["text"])
            for token in header_tokens:
                if token in collapsed:
                    header_tokens[token] = True
        return all(header_tokens.values())

    def _classify_line(self, text: str, has_active_row: bool) -> str | None:
        normalized = " ".join(text.split())
        collapsed = _collapse_token(normalized)
        if CARD_HEADER_RE.match(normalized):
            line_class = "card_header"
        elif all(token in collapsed for token in ("datum", "beschrijving", "bedrag")):
            line_class = "table_header"
        elif FX_HELPER_RE.match(normalized):
            line_class = "fx_helper"
        elif PAGE_FOOTER_RE.match(normalized):
            line_class = "page_footer_noise"
        elif self._is_malformed_fx_helper_candidate(normalized):
            line_class = "malformed_fx_helper_candidate"
        elif self._is_malformed_row_candidate(normalized):
            line_class = "malformed_row_candidate"
        elif self._is_row_start(normalized):
            line_class = "row_start"
        elif has_active_row and self._is_continuation(normalized):
            line_class = "continuation"
        else:
            line_class = None
        return line_class

    def _is_row_start(self, text: str) -> bool:
        match = ROW_RE.match(text)
        if not match:
            return False
        try:
            _parse_amount_text(match.group("amount"))
        except ValueError:
            return False
        return True

    def _is_malformed_row_candidate(self, text: str) -> bool:
        return MALFORMED_ROW_RE.match(text) is not None

    def _is_malformed_fx_helper_candidate(self, text: str) -> bool:
        return MALFORMED_FX_HELPER_RE.match(text) is not None

    def _is_malformed_standalone_wisselkosten(
        self, body_lines: list[dict], index: int
    ) -> bool:
        if body_lines[index]["text"].strip().casefold() != "wisselkosten":
            return False
        if index == 0 or index + 1 >= len(body_lines):
            return False
        if not FX_HELPER_RE.match(" ".join(body_lines[index - 1]["text"].split())):
            return False
        next_line = " ".join(body_lines[index + 1]["text"].split())
        if AMOUNT_RE.match(next_line):
            return False
        return (
            re.match(r"^-?(?=[^,]*\.)(?=[^,]* )\d{1,3}(?:[. ]\d{3})+,\d{2}$", next_line)
            is not None
        )

    def _is_continuation(self, text: str) -> bool:
        stripped = " ".join(text.split())
        if not stripped:
            return False
        if stripped.casefold().startswith("wisselkosten"):
            return False
        if DATE_RE.match(stripped):
            return False
        return not AMOUNT_RE.match(stripped)

    def _is_inline_wisselkosten(self, text: str) -> bool:
        return INLINE_WISSELKOSTEN_RE.match(" ".join(text.split())) is not None

    @staticmethod
    def _fee_context_description(
        current_row: dict | None, last_transaction_description: str | None
    ) -> str | None:
        if current_row is None:
            return last_transaction_description
        description = BeobankMastercardPdfExtractor._joined_description(current_row)
        return description or None

    @staticmethod
    def _joined_description(row: dict) -> str:
        return " ".join(row["description_parts"]).strip()

    def _is_standalone_wisselkosten(self, body_lines: list[dict], index: int) -> bool:
        if body_lines[index]["text"].strip().casefold() != "wisselkosten":
            return False
        if index == 0 or index + 1 >= len(body_lines):
            return False
        if not FX_HELPER_RE.match(" ".join(body_lines[index - 1]["text"].split())):
            return False
        try:
            _parse_amount_text(" ".join(body_lines[index + 1]["text"].split()))
        except ValueError:
            return False
        return True

    def _build_row_candidate(self, line_number: int, text: str) -> dict:
        match = ROW_RE.match(" ".join(text.split()))
        if match is None:
            message = "text does not match a Beobank row"
            raise ValueError(message)
        return {
            "transaction_date": _to_iso_date(match.group("date")),
            "description_parts": [" ".join(match.group("description").split())],
            "amount_text": match.group("amount"),
            "start_line": line_number,
            "end_line": line_number,
        }

    def _build_standalone_wisselkosten_row(
        self,
        transaction_date: str,
        fee_context: str | None,
        start_line: int,
        end_line: int,
        amount_text: str,
    ) -> dict:
        return {
            "transaction_date": transaction_date,
            "description_parts": [self._wisselkosten_description(fee_context)],
            "amount_text": " ".join(amount_text.split()),
            "start_line": start_line,
            "end_line": end_line,
        }

    def _build_inline_wisselkosten_row(
        self,
        *,
        transaction_date: str,
        fee_context: str | None,
        line_number: int,
        text: str,
    ) -> dict:
        normalized = " ".join(text.split())
        match = INLINE_WISSELKOSTEN_RE.match(normalized)
        if match is None:
            message = "text does not match an inline wisselkosten row"
            raise ValueError(message)
        return {
            "transaction_date": transaction_date,
            "description_parts": [self._wisselkosten_description(fee_context)],
            "amount_text": match.group("amount"),
            "start_line": line_number,
            "end_line": line_number,
        }

    @staticmethod
    def _wisselkosten_description(fee_context: str | None) -> str:
        if fee_context:
            return f"WISSELKOSTEN - {fee_context}"
        return "WISSELKOSTEN"

    def _build_transaction(self, page_number: int, row: dict) -> ExtractedTransaction:
        signed_amount, debit_credit = _parse_amount_text(row["amount_text"])
        start_line = row["start_line"]
        end_line = row["end_line"]
        source_locator = (
            f"pdf:p{page_number}:l{start_line}"
            if start_line == end_line
            else f"pdf:p{page_number}:l{start_line}-{end_line}"
        )
        return ExtractedTransaction(
            transaction_date=row["transaction_date"],
            source_description=" ".join(row["description_parts"]),
            canonical_description_en=None,
            signed_amount=signed_amount,
            currency="EUR",
            debit_credit=debit_credit,
            inferred_category=None,
            category_source=None,
            confidence={},
            source_locator=source_locator,
            edit_source="deterministic_extracted",
        )

    def _unclassifiable_issue(
        self, page_number: int, line_number: int, text: str
    ) -> ImportIssue:
        return ImportIssue(
            code="unclassifiable_table_line",
            message=(
                f"Unclassifiable table line on page {page_number}, "
                f"line {line_number}: {text}"
            ),
            blocking=True,
            transaction_ref=f"pdf:p{page_number}:l{line_number}",
        )
