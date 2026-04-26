"""Module for backend tests test_text_normalization."""

from app.services.category_suggestion_service import CategorySuggestionService
from app.utils.text_normalization import normalize_for_matching


def test_normalize_for_matching_strips_dates_refs_cards_and_iban() -> None:
    """Verify normalize for matching strips dates refs cards and iban."""
    raw = (
        "SEPA PROXIMUS 15/03/2026 REF. 12345 BE68539007547034 CARD 4976 1234 5678 9012"
    )
    assert normalize_for_matching(raw) == "sepa proximus"


def test_normalize_for_matching_strips_bare_card_label() -> None:
    """Verify normalize for matching strips bare card label."""
    raw = "CARD 4976 1234 5678 9012"
    assert normalize_for_matching(raw) == ""


def test_normalize_for_matching_keeps_reference_trailing_merchant_text() -> None:
    """Verify normalize for matching keeps reference trailing merchant text."""
    raw = "REF 12345 PROXIMUS"
    assert normalize_for_matching(raw) == "proximus"


def test_normalize_for_matching_strips_dotted_reference_values() -> None:
    """Verify normalize for matching strips dotted reference values."""
    raw = "Reference: INV.2026 PROXIMUS"
    assert normalize_for_matching(raw) == "proximus"


def test_normalize_for_matching_strips_multi_token_reference_values() -> None:
    """Verify normalize for matching strips multi token reference values."""
    raw = "Reference: ABC 123 PROXIMUS"
    assert normalize_for_matching(raw) == "proximus"


def test_normalize_keeps_digit_bearing_merchant_after_reference() -> None:
    """Verify normalize keeps digit bearing merchant after reference."""
    raw = "Reference: ABC 123 7ELEVEN"
    assert normalize_for_matching(raw) == "7eleven"


def test_normalize_keeps_dotted_digit_bearing_merchant_after_reference() -> None:
    """Verify normalize keeps dotted digit bearing merchant after reference."""
    raw = "Reference: INV.2026 SHOP24"
    assert normalize_for_matching(raw) == "shop24"


def test_normalize_for_matching_preserves_word_order() -> None:
    """Verify normalize for matching preserves word order."""
    raw = "LOYER appartement centre ville 31-03-2026 REF ABC987"
    assert normalize_for_matching(raw) == "loyer appartement centre ville"


def test_normalize_for_matching_preserves_short_numeric_tokens() -> None:
    """Verify normalize for matching preserves short numeric tokens."""
    raw = "SHOP 12/34 MARKET"
    assert normalize_for_matching(raw) == "shop 12/34 market"


def test_normalize_for_matching_preserves_dash_separated_tokens() -> None:
    """Verify normalize for matching preserves dash separated tokens."""
    raw = "BUS LINE 10-20 EXPRESS"
    assert normalize_for_matching(raw) == "bus line 10-20 express"


def test_normalize_for_matching_preserves_dot_separated_tokens() -> None:
    """Verify normalize for matching preserves dot separated tokens."""
    raw = "MEETING 07.11 NOTES"
    assert normalize_for_matching(raw) == "meeting 07.11 notes"


def test_normalize_for_matching_preserves_text_after_partial_iban_prefix() -> None:
    """Verify normalize for matching preserves text after partial iban prefix."""
    raw = "PAYMENT BE68 groceries at store"
    assert normalize_for_matching(raw) == "payment be68 groceries at store"


def test_normalize_for_matching_collapses_whitespace() -> None:
    """Verify normalize for matching collapses whitespace."""
    raw = "  EUROPEAN   DIRECT   DEBIT   PROXIMUS   "
    assert normalize_for_matching(raw) == "european direct debit proximus"


def test_preprocess_description_keeps_merchant_prepend() -> None:
    """Verify preprocess description keeps merchant prepend."""
    service = CategorySuggestionService.__new__(CategorySuggestionService)

    result = service._preprocess_description(
        "creditor: PROXIMUS 07.11 15/03/2026 REF 12345"
    )

    assert result.startswith("proximus ")
    assert "07.11" not in result
