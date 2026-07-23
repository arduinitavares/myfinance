"""Enforce the repository-owned Python quality contract."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import cast

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OWNED_PYTHON_ROOTS = (
    PROJECT_ROOT / "backend" / "app",
    PROJECT_ROOT / "backend" / "scripts",
    PROJECT_ROOT / "backend" / "tests",
    PROJECT_ROOT / "backup",
    PROJECT_ROOT / "scripts",
)
EXPECTED_TY_INCLUDE = [
    "backend/app",
    "backend/scripts",
    "backend/tests",
    "backup",
    "scripts",
]
EXPECTED_RUFF_EXTEND_EXCLUDE = [
    ".codegraph",
    ".worktrees",
    "bank_files",
    "docs",
    "frontend",
]
EXPECTED_BANDIT_EXCLUDES = [
    ".codegraph",
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".vscode",
    ".worktrees",
    "backend/tests",
    "bank_files",
    "docs",
    "frontend",
]
EXPECTED_PYTEST_ADDOPTS = "--ignore=backend/tests/live"
FORBIDDEN_SOURCE_MARKERS = (
    "no" + "qa",
    "no" + "sec",
    "type:" + " ignore",
    "ty:" + " ignore",
)


def _pyproject() -> dict[str, object]:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as stream:
        return tomllib.load(stream)


def _table(container: dict[str, object], key: str) -> dict[str, object]:
    value = container[key]
    assert isinstance(value, dict)
    return cast("dict[str, object]", value)


def _quality_suppression_markers(text: str) -> list[str]:
    folded_text = text.casefold()
    return [marker for marker in FORBIDDEN_SOURCE_MARKERS if marker in folded_text]


def test_python_tool_scope_matches_owned_code() -> None:
    """Require explicit owned-code scope without disabling rules."""
    config = _pyproject()
    tool = _table(config, "tool")
    ruff = _table(tool, "ruff")
    ty = _table(tool, "ty")
    ty_environment = _table(ty, "environment")
    ty_src = _table(ty, "src")
    bandit = _table(tool, "bandit")
    pytest_tool = _table(tool, "pytest")
    pytest_config = _table(pytest_tool, "ini_options")

    assert set(ruff) == {"extend-exclude"}
    assert ruff["extend-exclude"] == EXPECTED_RUFF_EXTEND_EXCLUDE
    assert set(ty) == {"environment", "src"}
    assert ty_environment == {
        "python": ".venv",
        "python-version": "3.13",
    }
    assert set(ty_src) == {"include"}
    assert ty_src["include"] == EXPECTED_TY_INCLUDE
    assert set(bandit) == {"exclude_dirs"}
    assert bandit["exclude_dirs"] == EXPECTED_BANDIT_EXCLUDES
    assert set(pytest_config) == {
        "addopts",
        "filterwarnings",
        "pythonpath",
        "testpaths",
    }
    assert pytest_config["testpaths"] == ["backend/tests"]
    assert pytest_config["pythonpath"] == ["backend"]
    assert pytest_config["filterwarnings"] == ["error"]
    assert pytest_config["addopts"] == EXPECTED_PYTEST_ADDOPTS


def test_quality_suppression_markers_are_case_insensitive() -> None:
    """Reject every supported marker regardless of letter case."""
    source = "\n".join(
        (
            "# " + "NO" + "QA",
            "# " + "No" + "SeC",
            "# " + "TyPe:" + " IgNoRe",
            "# " + "Ty:" + " IgNoRe",
        )
    )
    expected = [
        "no" + "qa",
        "no" + "sec",
        "type:" + " ignore",
        "ty:" + " ignore",
    ]

    assert _quality_suppression_markers(source) == expected


def test_owned_python_has_no_quality_suppression_markers() -> None:
    """Reject inline suppressions in application code, scripts, and tests."""
    violations: list[str] = []
    for owned_root in OWNED_PYTHON_ROOTS:
        for path in sorted(owned_root.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for marker in _quality_suppression_markers(text):
                violations.append(f"{path.relative_to(PROJECT_ROOT)}: {marker}")

    assert violations == []


def test_quality_configuration_has_no_rule_suppression_tables() -> None:
    """Reject rule-ignore configuration while allowing path exclusions."""
    config = _pyproject()
    tool = _table(config, "tool")
    ruff_value = tool.get("ruff", {})
    assert isinstance(ruff_value, dict)
    ruff = cast("dict[str, object]", ruff_value)
    lint_value = ruff.get("lint", {})
    assert isinstance(lint_value, dict)
    lint = cast("dict[str, object]", lint_value)

    assert lint == {}
