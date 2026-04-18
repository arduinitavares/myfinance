import pytest
from pydantic import ValidationError

from app.imports import ProviderDescription
from app.imports.contracts import (
    DetectionResult,
    ExtractionResult,
    ExtractedTransaction,
    ImportIssue,
    ImportStrategyKey,
    RawEvidence,
)
from app.models.transaction import ExpenseCategory, TransactionType


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
                proposed_transaction_type=None,
                proposed_expense_category=None,
                proposed_income_category=None,
                proposed_transfer_category=None,
                proposal_source=None,
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
    assert dumped["transactions"][0]["proposed_transfer_category"] is None


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


def test_import_strategy_key_includes_nexo_csv():
    assert ImportStrategyKey.NEXO_CSV.value == "nexo_csv"


def test_extracted_transaction_serializes_proposal_fields():
    tx = ExtractedTransaction(
        transaction_date="2026-04-11",
        source_description="Nexo Card Transaction Fee",
        signed_amount=-0.16,
        currency="xUSD",
        debit_credit="debit",
        source_locator="csv:r3:NXT_FEE_1",
        proposed_transaction_type=TransactionType.EXPENSE,
        proposed_expense_category=ExpenseCategory.FINANCIAL_FEES,
        proposal_source="deterministic_extracted",
        edit_source="deterministic_extracted",
    )

    dumped = tx.model_dump(mode="json")
    assert dumped["proposed_transaction_type"] == "Expense"
    assert dumped["proposed_expense_category"] == "Financial Fees"
    assert dumped["proposal_source"] == "deterministic_extracted"


def test_raw_evidence_rejects_non_json_safe_content():
    with pytest.raises(ValidationError):
        RawEvidence(text_blocks=[{"page": 1, "text": object()}])


def test_extracted_transaction_limits_edit_source_values():
    valid = ExtractedTransaction(
        transaction_date="2026-04-11",
        source_description="Bancontact betaling",
        canonical_description_en=None,
        signed_amount=-10.0,
        currency="EUR",
        debit_credit="debit",
        inferred_category=None,
        category_source=None,
        proposed_transaction_type=TransactionType.EXPENSE,
        proposed_expense_category=ExpenseCategory.GROCERIES,
        proposed_income_category=None,
        proposed_transfer_category=None,
        proposal_source="deterministic_extracted",
        confidence={},
        source_locator="csv:row:2",
        edit_source="user_edited",
    )
    assert valid.edit_source == "user_edited"
    assert valid.proposal_source == "deterministic_extracted"
    assert valid.proposed_expense_category == ExpenseCategory.GROCERIES

    with pytest.raises(ValidationError):
        ExtractedTransaction(
            transaction_date="2026-04-11",
            source_description="Bancontact betaling",
            canonical_description_en=None,
            signed_amount=-10.0,
            currency="EUR",
            debit_credit="debit",
            inferred_category=None,
            category_source=None,
            proposed_transaction_type=None,
            proposed_expense_category=None,
            proposed_income_category=None,
            proposed_transfer_category=None,
            proposal_source="manual",
            confidence={},
            source_locator="csv:row:2",
            edit_source="user_edited",
        )


def test_extracted_transaction_accepts_deterministic_edit_source():
    tx = ExtractedTransaction(
        transaction_date="2026-04-11",
        source_description="WISSELKOSTEN",
        signed_amount=-0.38,
        currency="EUR",
        debit_credit="debit",
        source_locator="pdf:p2:l21",
        proposal_source="ai_extracted",
        edit_source="deterministic_extracted",
    )
    assert tx.edit_source == "deterministic_extracted"


def test_raw_evidence_accepts_page_line_payloads():
    evidence = RawEvidence(
        text_blocks=[
            {
                "page_number": 2,
                "raw_text": "Uw transacties\n15/12/2025 Merchant 14,20",
                "lines": ["Uw transacties", "15/12/2025 Merchant 14,20"],
            }
        ]
    )
    assert evidence.model_dump()["text_blocks"][0]["page_number"] == 2


def test_provider_description_is_exported_from_package_surface():
    provider = ProviderDescription(
        provider_name="belfius",
        model_name="gpt-4.1-mini",
        schema_version="v1",
        prompt_fingerprint="abc123",
    )
    assert provider.model_name == "gpt-4.1-mini"
