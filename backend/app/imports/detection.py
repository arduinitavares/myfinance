"""Module for backend app imports detection."""

from app.imports.contracts import DetectionResult, ImportStrategyKey
from app.imports.csv_support import (
    BELFIUS_HEADER,
    BEOBANK_COMPACT_HEADER,
    BEOBANK_DEBIT_CREDIT_HEADER,
    NEXO_HEADER,
    decode_csv_bytes,
    find_header_row,
)


class ImportDetector:
    """Represent import detector."""

    def detect(
        self,
        *,
        filename: str,
        content_type: str,
        sample: bytes,
    ) -> DetectionResult:
        """Handle detect."""
        normalized_filename = filename.lower()
        normalized_content_type = content_type.lower()
        if (
            sample.startswith(b"%PDF-")
            or normalized_content_type == "application/pdf"
            or normalized_filename.endswith(".pdf")
        ):
            return DetectionResult(
                strategy_key=ImportStrategyKey.PDF_STATEMENT,
                provider_hint=None,
                language_hint=None,
                charset_hint=None,
                confidence=1.0,
                page_count=None,
                password_protected=False,
                notes=[],
            )

        decoded, charset_hint = decode_csv_bytes(sample)
        lines = decoded.splitlines()

        if find_header_row(lines, delimiter=";", expected_header=BELFIUS_HEADER):
            return DetectionResult(
                strategy_key=ImportStrategyKey.BELFIUS_CSV,
                provider_hint="belfius",
                language_hint=None,
                charset_hint=charset_hint,
                confidence=0.95,
                page_count=None,
                password_protected=False,
                notes=["Matched Belfius CSV transaction header"],
            )

        if find_header_row(
            lines, delimiter=";", expected_header=BEOBANK_COMPACT_HEADER
        ):
            return DetectionResult(
                strategy_key=ImportStrategyKey.BEOBANK_CSV,
                provider_hint="beobank",
                language_hint=None,
                charset_hint=charset_hint,
                confidence=0.95,
                page_count=None,
                password_protected=False,
                notes=["Matched Beobank compact CSV header"],
            )

        if find_header_row(
            lines, delimiter=";", expected_header=BEOBANK_DEBIT_CREDIT_HEADER
        ) or find_header_row(
            lines,
            delimiter=",",
            expected_header=BEOBANK_DEBIT_CREDIT_HEADER,
        ):
            return DetectionResult(
                strategy_key=ImportStrategyKey.BEOBANK_CSV,
                provider_hint="beobank",
                language_hint=None,
                charset_hint=charset_hint,
                confidence=0.95,
                page_count=None,
                password_protected=False,
                notes=["Matched Beobank debit/credit CSV header"],
            )

        if find_header_row(lines, delimiter=",", expected_header=NEXO_HEADER):
            return DetectionResult(
                strategy_key=ImportStrategyKey.NEXO_CSV,
                provider_hint="nexo",
                language_hint=None,
                charset_hint=charset_hint,
                confidence=1.0,
                page_count=None,
                password_protected=False,
                notes=["Matched Nexo CSV header"],
            )

        return DetectionResult(
            strategy_key=ImportStrategyKey.UNKNOWN,
            provider_hint=None,
            language_hint=None,
            charset_hint=charset_hint,
            confidence=0.0,
            page_count=None,
            password_protected=False,
            notes=["No registered detector matched the uploaded file"],
        )
