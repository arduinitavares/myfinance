from app.imports.contracts import DetectionResult, ImportStrategyKey


class ImportDetector:
    def detect(self, *, filename: str, content_type: str, sample: bytes) -> DetectionResult:
        lower_name = filename.lower()
        if lower_name.endswith(".pdf") or content_type == "application/pdf":
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

        return DetectionResult(
            strategy_key=ImportStrategyKey.UNKNOWN,
            provider_hint=None,
            language_hint=None,
            charset_hint="latin-1",
            confidence=0.0,
            page_count=None,
            password_protected=False,
            notes=["No registered detector matched the uploaded file"],
        )
