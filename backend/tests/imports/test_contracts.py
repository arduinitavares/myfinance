from app.imports.contracts import (
    DetectionResult,
    ExtractionResult,
    ExtractedTransaction,
    ImportIssue,
    ImportStrategyKey,
    RawEvidence,
)


def test_extraction_result_serializes_blocking_issues_and_nullable_fields():
    result = ExtractionResult(
        extractor_id="csv.stub",
        raw_artifact_ref="imports/session-1/attempts/1/evidence/raw.json",
        source_metadata={"provider_hint": "belfius", "file_type": "csv", "language": "nl"},
        statement_metadata={"currency": "EUR"},
        transactions=[
            ExtractedTransaction(
                transaction_date="2026-04-11",
                source_description="Bancontact betaling",
                canonical_description_en=None,
                signed_amount=-10.0,
                currency="EUR",
                debit_credit="debit",
                inferred_category=None,
                category_source=None,
                confidence={"amount": 1.0},
                source_locator="csv:row:2",
                edit_source="ai_extracted",
            )
        ],
        issues=[
            ImportIssue(
                code="missing_balance",
                message="Balance missing from statement footer",
                blocking=True,
                transaction_ref=None,
            )
        ],
        overall_confidence=0.91,
    )

    dumped = result.model_dump()
    assert dumped["issues"][0]["blocking"] is True
    assert dumped["transactions"][0]["canonical_description_en"] is None


def test_raw_evidence_is_json_serializable():
    evidence = RawEvidence(
        text_blocks=[{"page": 1, "text": "Statement header"}],
        ocr_blocks=[],
        snippets=[{"page": 1, "text": "Bancontact betaling"}],
    )
    assert evidence.model_dump()["snippets"][0]["text"] == "Bancontact betaling"


def test_detection_result_exposes_strategy_enum():
    detected = DetectionResult(
        strategy_key=ImportStrategyKey.PDF_STATEMENT,
        provider_hint="beobank",
        language_hint="nl",
        charset_hint=None,
        confidence=0.8,
        page_count=2,
        password_protected=False,
        notes=[],
    )
    assert detected.strategy_key == ImportStrategyKey.PDF_STATEMENT
