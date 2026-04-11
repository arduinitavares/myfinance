from app.utils.text_normalization import normalize_for_matching


def test_normalize_for_matching_strips_dates_refs_cards_and_iban():
    raw = "SEPA PROXIMUS 15/03/2026 REF. 12345 BE68539007547034 CARD 4976 1234 5678 9012"
    assert normalize_for_matching(raw) == "sepa proximus"


def test_normalize_for_matching_preserves_word_order():
    raw = "LOYER appartement centre ville 31-03-2026 REF ABC987"
    assert normalize_for_matching(raw) == "loyer appartement centre ville"


def test_normalize_for_matching_collapses_whitespace():
    raw = "  EUROPEAN   DIRECT   DEBIT   PROXIMUS   "
    assert normalize_for_matching(raw) == "european direct debit proximus"
