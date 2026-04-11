import importlib.util
from pathlib import Path


def _load_sanitizer_module():
    module_path = Path(__file__).resolve().parents[2] / ".." / "scripts" / "sanitize_fixture.py"
    spec = importlib.util.spec_from_file_location("sanitize_fixture", module_path.resolve())
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_sanitize_fixture_masks_iban_and_card_shapes():
    sanitizer = _load_sanitizer_module()
    cleaned = sanitizer.sanitize_fixture_text(
        "Naam;BE68539007547034;4976 1234 5678 9012;1234,56"
    )
    assert "BE68539007547034" not in cleaned
    assert "4976 1234 5678 9012" not in cleaned
    assert "1234,56" not in cleaned
