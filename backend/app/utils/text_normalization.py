import re

TRANSACTION_DATE_PATTERNS = [
    r"\b(?:0?[1-9]|[12]\d|3[01])[-/](?:0?[1-9]|1[0-2])[-/](?:\d{2}|\d{4})\b",
    r"\b(?:[01]?\d|2[0-3]):[0-5]\d(?:\s?(?:am|pm))?\b",
]

CARD_NUMBER_PATTERNS = [
    r"\bcard(?: number)?\s+\d{4}(?:\s+\d{4}){3}\b",
    r"card number \d*x*\s*\d*x*\s*\d*x*\s*\d*",
    r"\b\d{4}\s\d{4}\s\d{4}\s\d{4}\b",
    r"with \w+ (?:debit|credit) card \d{4}\s*\d*x*\s*\d*x*\s*\d*",
]

REFERENCE_VALUE_PATTERN = r"(?:[A-Z]{2,6}\.?\s+)?(?:[\w.-]*\d[\w.-]*)"

REFERENCE_PATTERNS = [
    rf"\bcreditor ref\.\s*:\s*{REFERENCE_VALUE_PATTERN}\b",
    rf"\bmandate ref\.\s*:\s*{REFERENCE_VALUE_PATTERN}\b",
    rf"\bref(?:erence)?\.?\s*[: ]\s*{REFERENCE_VALUE_PATTERN}\b",
    rf"\breference\s*:\s*{REFERENCE_VALUE_PATTERN}\b",
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
