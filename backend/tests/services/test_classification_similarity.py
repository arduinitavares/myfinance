"""Module for backend tests services test_classification_similarity."""

from app.models.transaction import Transaction, TransactionType
from app.services.classification_similarity import has_conflicting_family


def _transaction(description: str) -> Transaction:
    return Transaction(
        id=1,
        account_number="acc",
        transaction_date="2026-04-12",
        amount=-10.0,
        currency="EUR",
        description=description,
        transaction_type=TransactionType.EXPENSE,
        source_bank="Beobank",
    )


def test_exchange_fee_rows_do_not_batch_with_plain_merchant_rows() -> None:
    """Verify exchange fee rows do not batch with plain merchant rows."""
    fee_row = _transaction("WISSELKOSTEN - ADOBE CURITIBA BR")
    merchant_row = _transaction("ADOBE CURITIBA BR")

    assert has_conflicting_family(fee_row, merchant_row) is True


def test_exchange_fee_rows_can_batch_with_other_exchange_fee_rows() -> None:
    """Verify exchange fee rows can batch with other exchange fee rows."""
    first_fee_row = _transaction("WISSELKOSTEN - ADOBE CURITIBA BR")
    second_fee_row = _transaction("WISSELKOSTEN - NETFLIX SAO PAULO BR")

    assert has_conflicting_family(first_fee_row, second_fee_row) is False
