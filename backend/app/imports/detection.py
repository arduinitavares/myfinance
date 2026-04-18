import csv
import io

from app.imports.contracts import DetectionResult, ImportStrategyKey

from .nexo_csv import NEXO_CSV_HEADER


class ImportDetector:
    def detect(self, *, filename: str, content_type: str, sample: bytes) -> DetectionResult:
        if sample.startswith(b"%PDF-"):
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

        charset_hint, decoded_sample = self._decode_sample(sample)
        header_row = self._csv_header(decoded_sample)
        if header_row == NEXO_CSV_HEADER:
            return DetectionResult(
                strategy_key=ImportStrategyKey.NEXO_CSV,
                provider_hint="nexo",
                language_hint=None,
                charset_hint=charset_hint,
                confidence=1.0,
                page_count=None,
                password_protected=False,
                notes=["Matched deterministic Nexo CSV header"],
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

    @staticmethod
    def _decode_sample(sample: bytes) -> tuple[str, str]:
        try:
            return "utf-8", sample.decode("utf-8-sig")
        except UnicodeDecodeError:
            return "latin-1", sample.decode("latin-1")

    @staticmethod
    def _csv_header(decoded_sample: str) -> list[str]:
        for line in decoded_sample.splitlines():
            if line.strip():
                return [cell.strip().replace("\ufeff", "") for cell in next(csv.reader(io.StringIO(line)))]
        return []
