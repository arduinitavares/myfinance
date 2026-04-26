"""Module for backend tests imports test_nexo_csv."""

from pathlib import Path

from app.imports.nexo_csv import NexoCsvExtractor
from app.models.transaction import ExpenseCategory, TransactionType, TransferCategory
from tests.imports.fixtures.nexo_csv import build_nexo_csv_bytes, nexo_row

EXPECTED_REVIEWABLE_TRANSACTION_COUNT: int = 3
PURCHASE_AMOUNT: float = -12.34
CARD_FEE_AMOUNT: float = -0.16
TRANSFER_AMOUNT: float = -250.0

type JsonObject = dict[str, object]


def _write_csv(tmp_path: Path, content: bytes) -> Path:
    file_path = tmp_path / "nexo_transactions.csv"
    file_path.write_bytes(content)
    return file_path


def _json_object(value: object) -> JsonObject:
    if not isinstance(value, dict):
        msg = f"Expected JSON object, got {type(value).__name__}"
        raise TypeError(msg)
    return {str(key): item for key, item in value.items()}


def test_nexo_csv_extractor_emits_expected_transactions_and_evidence(
    tmp_path: Path,
) -> None:
    """Verify nexo csv extractor emits expected transactions and evidence."""
    file_path = _write_csv(
        tmp_path,
        build_nexo_csv_bytes(
            nexo_row(
                "NXT1001",
                "Nexo Card Purchase",
                "xUSD",
                "-12.34",
                "approved / Coffee Shop",
                "2026-04-10 09:15:30",
            ),
            nexo_row(
                "NXT1002",
                "Nexo Card Transaction Fee",
                "xUSD",
                "-0.16",
                "approved / Card fee",
                "2026-04-10 09:15:31",
            ),
            nexo_row(
                "NXT1003",
                "Transfer Out",
                "EUR",
                "-250.00",
                "approved / Bank transfer to BE6800000000000000",
                "2026-04-11 11:22:33",
            ),
            nexo_row(
                "NXT1004",
                "Cashback",
                "NEXO",
                "0.42",
                "approved / Cashback",
                "2026-04-11 11:22:34",
            ),
            nexo_row(
                "NXT1005",
                "Exchange Credit",
                "USDC",
                "100.00",
                "approved / Exchange Credit",
                "2026-04-11 11:22:35",
            ),
            nexo_row(
                "NXT1006",
                "Credit Card Withdrawal Credit",
                "USDC",
                "200.00",
                "approved / Credit Card Withdrawal Credit",
                "2026-04-11 11:22:36",
            ),
            nexo_row(
                "NXT1007",
                "Nexo Card Purchase",
                "xUSD",
                "-9.99",
                "rejected / Grocery Store",
                "2026-04-12 14:00:00",
            ),
            nexo_row(
                "NXT1008",
                "Transfer Out",
                "EUR",
                "-80.00",
                "approved / Auto Transfer from Savings Wallet to Credit Line Wallet",
                "2026-04-12 15:00:00",
            ),
            nexo_row(
                "NXT1009",
                "Transfer Out",
                "EUR",
                "-80.00",
                "approved / Some other ambiguous transfer",
                "2026-04-12 16:00:00",
            ),
        ),
    )

    evidence, result = NexoCsvExtractor().extract(
        file_path=file_path, session_id="17", attempt_number=1
    )

    first_text_block = _json_object(evidence.text_blocks[0])
    assert first_text_block["page_number"] == 1
    raw_text = first_text_block["raw_text"]
    assert isinstance(raw_text, str)
    assert raw_text.startswith("Transaction,Type,Input Currency")
    assert any(
        _json_object(snippet)["transaction_id"] == "NXT1001"
        for snippet in evidence.snippets
    )

    assert result.extractor_id == "nexo_csv_v1"
    assert result.raw_artifact_ref == "imports/17/attempts/1/evidence/raw.json"
    assert result.source_metadata == {
        "provider_hint": "nexo",
        "file_type": "csv",
        "charset": "utf-8",
    }
    assert result.statement_metadata == {
        "account_number_hint": "NEXO",
        "card_number_hint": None,
        "currency": None,
        "statement_period_start": "2026-04-10",
        "statement_period_end": "2026-04-11",
    }
    assert result.overall_confidence == 1.0

    assert len(result.transactions) == EXPECTED_REVIEWABLE_TRANSACTION_COUNT

    purchase = result.transactions[0]
    assert purchase.transaction_date == "2026-04-10"
    assert purchase.source_description == "Coffee Shop"
    assert purchase.signed_amount == PURCHASE_AMOUNT
    assert purchase.currency == "xUSD"
    assert purchase.debit_credit == "debit"
    assert purchase.proposed_transaction_type == TransactionType.EXPENSE
    assert purchase.proposed_expense_category is None
    assert purchase.proposed_transfer_category is None
    assert purchase.source_locator == "csv:r2:NXT1001"
    assert purchase.proposal_source == "deterministic_extracted"
    assert purchase.edit_source == "deterministic_extracted"

    fee = result.transactions[1]
    assert fee.source_description == "Card fee"
    assert fee.signed_amount == CARD_FEE_AMOUNT
    assert fee.currency == "xUSD"
    assert fee.proposed_transaction_type == TransactionType.EXPENSE
    assert fee.proposed_expense_category == ExpenseCategory.FINANCIAL_FEES

    transfer = result.transactions[2]
    assert transfer.source_description == "Bank transfer to BE6800000000000000"
    assert transfer.signed_amount == TRANSFER_AMOUNT
    assert transfer.currency == "EUR"
    assert transfer.proposed_transaction_type == TransactionType.TRANSFER
    assert transfer.proposed_transfer_category == TransferCategory.INTERNAL_TRANSFER

    assert len(result.issues) == 1
    assert result.issues[0].code == "nexo_ambiguous_transfer_out"
    assert result.issues[0].blocking is False
    assert result.issues[0].transaction_ref == "csv:r10:NXT1009"


def test_nexo_csv_extractor_blocks_when_no_reviewable_rows_remain(
    tmp_path: Path,
) -> None:
    """Verify nexo csv extractor blocks when no reviewable rows remain."""
    file_path = _write_csv(
        tmp_path,
        build_nexo_csv_bytes(
            nexo_row(
                "NXT2001",
                "Cashback",
                "NEXO",
                "0.42",
                "approved / Cashback",
                "2026-04-11 11:22:33",
            ),
            nexo_row(
                "NXT2002",
                "Exchange Credit",
                "USDC",
                "100.00",
                "approved / Exchange Credit",
                "2026-04-11 11:22:34",
            ),
            nexo_row(
                "NXT2003",
                "Credit Card Withdrawal Credit",
                "USDC",
                "200.00",
                "approved / Credit Card Withdrawal Credit",
                "2026-04-11 11:22:35",
            ),
            nexo_row(
                "NXT2004",
                "Nexo Card Purchase",
                "xUSD",
                "-9.99",
                "rejected / Grocery Store",
                "2026-04-12 14:00:00",
            ),
            nexo_row(
                "NXT2005",
                "Transfer Out",
                "EUR",
                "-80.00",
                "approved / Auto Transfer from Savings Wallet to Credit Line Wallet",
                "2026-04-12 15:00:00",
            ),
        ),
    )

    _, result = NexoCsvExtractor().extract(
        file_path=file_path, session_id="18", attempt_number=1
    )

    assert result.transactions == []
    assert [issue.code for issue in result.issues] == ["no_importable_nexo_rows"]
    assert result.issues[0].blocking is True
    assert result.overall_confidence == 0.0
