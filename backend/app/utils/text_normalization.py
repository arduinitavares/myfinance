import re

TRANSACTION_DATE_PATTERNS = [
    r"\d{2}[-/]\d{2}[-/]\d{2,4}",
    r"\d{2}[-/]\d{2}",
    r"\d{1,2}[:.]\d{2}\s*(?:am|pm)?",
]

CARD_NUMBER_PATTERNS = [
    r"\bcard(?: number)?\s+\d{4}(?:\s+\d{4}){3}\b",
    r"card number \d*x*\s*\d*x*\s*\d*x*\s*\d*",
    r"\b\d{4}\s\d{4}\s\d{4}\s\d{4}\b",
    r"with \w+ (?:debit|credit) card \d{4}\s*\d*x*\s*\d*x*\s*\d*",
]

REFERENCE_PATTERNS = [
    r"creditor ref\.\s*:\s*[\w\s/.-]+",
    r"mandate ref\.\s*:\s*[\w\s/.-]+",
    r"ref(?:erence)?\.?\s*[: ]\s*[\w\s/.-]+",
    r"reference\s*:\s*[\w\s/.-]+",
]

IBAN_BIC_PATTERNS = [
    r"\b[A-Z]{2}\d{2}(?=[A-Z0-9 ]{10,30}\b)(?=[A-Z0-9 ]*\d)[A-Z0-9 ]{10,30}\b",
    r"(?:bic|swift|bank)\s*[: ]\s*[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}(?:[A-Z0-9]{3})?",
]


def _strip_patterns(text: str, patterns: list[str]) -> str:
    for pattern in patterns:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    return text


def normalize_for_matching(description: str) -> str:
    text = description.lower()
    text = _strip_patterns(text, TRANSACTION_DATE_PATTERNS)
    text = _strip_patterns(text, CARD_NUMBER_PATTERNS)
    text = _strip_patterns(text, REFERENCE_PATTERNS)
    text = _strip_patterns(text, IBAN_BIC_PATTERNS)
    text = re.sub(r"\s+", " ", text).strip()
    return text
