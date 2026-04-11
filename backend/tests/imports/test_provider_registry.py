import textwrap

from app.imports.providers import ProviderRegistry


def test_provider_registry_marks_missing_env_provider_unavailable(tmp_path, monkeypatch):
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
    report = registry.validate()

    assert report["document_extraction"]["openai"]["available"] is False
    assert report["document_extraction"]["openai"]["reason"] == "missing_env"
