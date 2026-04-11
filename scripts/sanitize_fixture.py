import re
import sys
from pathlib import Path

IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")
CARD_RE = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
AMOUNT_RE = re.compile(r"\b\d{1,6},\d{2}\b")
LEADING_NAME_RE = re.compile(r"(^|\n)Naam;([^;\n]+)")


def sanitize_fixture_text(text: str) -> str:
    text = LEADING_NAME_RE.sub(r"\1Fixture Name;Fixture Person", text)
    text = IBAN_RE.sub("BE00SANITIZED00000000", text)
    text = CARD_RE.sub("0000 0000 0000 0000", text)
    text = AMOUNT_RE.sub("99,99", text)
    return text.replace("Naam", "Fixture Name")


def read_text_with_fallback(source: Path) -> str:
    try:
        return source.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return source.read_text(encoding="latin-1")


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: sanitize_fixture.py <input> <output>")
        return 1
    source = Path(sys.argv[1])
    target = Path(sys.argv[2])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(sanitize_fixture_text(read_text_with_fallback(source)), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
