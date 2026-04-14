from ..models.transaction import Transaction
from ..utils.text_normalization import normalize_for_matching


SIMILARITY_THRESHOLD = 0.8
SIMILARITY_PREVIEW_LIMIT = 3

TRANSFER_LIKE_TERMS = (
    "p2p",
    "transfer",
    "mobile",
    "own account",
    "internal transfer",
)

EXCHANGE_FEE_TERMS = (
    "wisselkosten",
    "exchange fee",
)

MERCHANT_OR_BILL_LIKE_TERMS = (
    "energie",
    "proximus",
    "rent",
    "invoice",
    "telecom",
    "utility",
)


def looks_like_transfer(description: str) -> bool:
    normalized = normalize_for_matching(description)
    return any(term in normalized for term in TRANSFER_LIKE_TERMS)


def looks_like_bill_or_merchant(description: str) -> bool:
    normalized = normalize_for_matching(description)
    return any(term in normalized for term in MERCHANT_OR_BILL_LIKE_TERMS)


def looks_like_exchange_fee(description: str) -> bool:
    normalized = normalize_for_matching(description)
    return any(term in normalized for term in EXCHANGE_FEE_TERMS)


def has_conflicting_family(seed: Transaction, candidate: Transaction) -> bool:
    seed_transfer = looks_like_transfer(seed.description)
    candidate_transfer = looks_like_transfer(candidate.description)
    seed_bill = looks_like_bill_or_merchant(seed.description)
    candidate_bill = looks_like_bill_or_merchant(candidate.description)
    seed_exchange_fee = looks_like_exchange_fee(seed.description)
    candidate_exchange_fee = looks_like_exchange_fee(candidate.description)

    if seed_exchange_fee != candidate_exchange_fee:
        return True

    return (seed_transfer and candidate_bill) or (seed_bill and candidate_transfer)


def shares_source_bank(seed: Transaction, candidate: Transaction) -> bool:
    if not seed.source_bank or not candidate.source_bank:
        return True
    return seed.source_bank == candidate.source_bank
