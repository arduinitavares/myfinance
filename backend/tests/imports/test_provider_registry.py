"""Module for backend tests imports test_provider_registry."""

import textwrap
from pathlib import Path

import pytest
from app.imports.providers import ProviderRegistry
from pydantic import ValidationError


def test_provider_registry_missing_file_returns_default_registry(
    tmp_path: Path,
) -> None:
    """Verify provider registry missing file returns default registry."""
    registry = ProviderRegistry.from_path(tmp_path / "missing-config.yaml")
    report = registry.availability_report()

    assert report["document_extraction"]["__family__"]["chain_available"] is False
    assert report["document_extraction"]["__family__"]["reason"] == "no_order"


def test_provider_registry_marks_missing_env_provider_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify provider registry marks missing env provider unavailable."""
    config_path = tmp_path / "config.local.yaml"
    config_path.write_text(
        textwrap.dedent(
            """
            document_extraction:
              order: [openai]
              fallback_on:
                - condition: low_confidence
                  threshold: 0.75
              providers:
                openai:
                  enabled: true
                  kind: openai
                  model: gpt-4o-mini
                  api_key_env: OPENAI_API_KEY
                  timeout_seconds: 30
                  max_retries: 2
                  supports_pdf: true
                  supports_images: true
                  supports_json_schema: true
                  cost_tier: metered
                  requires_confirmation: true
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    registry = ProviderRegistry.from_path(config_path)
    report = registry.availability_report()

    assert report["document_extraction"]["openai"]["available"] is False
    assert report["document_extraction"]["openai"]["reason"] == "missing_env"
    assert report["document_extraction"]["__family__"]["chain_available"] is False
    assert (
        report["document_extraction"]["__family__"]["reason"] == "no_available_provider"
    )


def test_provider_registry_selects_first_available_provider_in_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify provider registry selects first available provider in order."""
    config_path = tmp_path / "config.local.yaml"
    config_path.write_text(
        textwrap.dedent(
            """
            document_extraction:
              order: [openai, ollama]
              fallback_on: []
              providers:
                openai:
                  enabled: true
                  kind: openai
                  model: gpt-4o-mini
                  api_key_env: OPENAI_API_KEY
                  timeout_seconds: 30
                  max_retries: 2
                  supports_pdf: true
                  supports_images: true
                  supports_json_schema: true
                  cost_tier: metered
                  requires_confirmation: true
                ollama:
                  enabled: true
                  kind: ollama
                  model: llama3.2
                  timeout_seconds: 30
                  max_retries: 1
                  supports_pdf: false
                  supports_images: false
                  supports_json_schema: false
                  cost_tier: free
                  requires_confirmation: false
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    registry = ProviderRegistry.from_path(config_path)
    report = registry.availability_report()

    assert report["document_extraction"]["openai"]["available"] is False
    assert report["document_extraction"]["openai"]["reason"] == "missing_env"
    assert report["document_extraction"]["ollama"]["available"] is False
    assert report["document_extraction"]["ollama"]["reason"] == "unsupported_pdf"
    assert report["document_extraction"]["__family__"]["chain_available"] is False
    assert (
        report["document_extraction"]["__family__"]["reason"] == "no_available_provider"
    )
    assert report["document_extraction"]["__family__"]["skipped_providers"] == [
        "openai",
        "ollama",
    ]


def test_provider_registry_marks_invalid_order_reference(tmp_path: Path) -> None:
    """Verify provider registry marks invalid order reference."""
    config_path = tmp_path / "config.local.yaml"
    config_path.write_text(
        textwrap.dedent(
            """
            document_extraction:
              order: [missing_provider]
              fallback_on: []
              providers: {}
            """
        ),
        encoding="utf-8",
    )

    registry = ProviderRegistry.from_path(config_path)
    report = registry.availability_report()

    assert report["document_extraction"]["__family__"]["chain_available"] is False
    assert report["document_extraction"]["__family__"]["reason"] == "invalid_order"
    assert report["document_extraction"]["__family__"]["invalid_references"] == [
        "missing_provider"
    ]


def test_provider_registry_rejects_unknown_provider_keys(tmp_path: Path) -> None:
    """Verify provider registry rejects unknown provider keys."""
    config_path = tmp_path / "config.local.yaml"
    config_path.write_text(
        textwrap.dedent(
            """
            document_extraction:
              order: [openai]
              fallback_on: []
              providers:
                openai:
                  enabled: true
                  kind: openai
                  model: gpt-4o-mini
                  api_keyenv: OPENAI_API_KEY
            """
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        ProviderRegistry.from_path(config_path)
