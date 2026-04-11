import textwrap
from datetime import date

from app.imports.providers import ProviderRegistry
from app.models.transaction import Transaction, TransactionType
from app.services.classifier_providers import StubClassifierProvider


def test_stub_provider_returns_utilities_monthly_for_proximus():
    provider = StubClassifierProvider(name="stub", model_name="stub-classifier-v1")
    transaction = Transaction(
        id=1,
        account_number="BE10000000000001",
        transaction_date=date(2025, 1, 1),
        amount=-42.50,
        currency="EUR",
        description="PROXIMUS telecom invoice",
        transaction_type=TransactionType.EXPENSE,
        source_bank="ing",
    )

    proposal = provider.propose(
        transaction=transaction,
        allowed_categories=["Utilities", "Others"],
        feedback_tag=None,
        feedback_note=None,
    )

    assert proposal.transaction_type == "Expense"
    assert proposal.category == "Utilities"
    assert proposal.confidence == 0.91
    assert proposal.recurrence_frequency == "monthly"
    assert "Proximus" in proposal.rationale


def test_provider_registry_accepts_classification_assistant_family_and_selects_stub(tmp_path):
    config_path = tmp_path / "config.local.yaml"
    config_path.write_text(
        textwrap.dedent(
            """
            classification_assistant:
              order: [stub]
              fallback_on: []
              providers:
                stub:
                  enabled: true
                  kind: stub
                  model: stub-classifier-v1
                  timeout_seconds: 5
                  max_retries: 1
                  supports_pdf: false
                  supports_images: false
                  supports_json_schema: true
                  cost_tier: free
                  requires_confirmation: false
            """
        ),
        encoding="utf-8",
    )

    registry = ProviderRegistry.from_path(config_path)
    report = registry.validate()

    assert report["classification_assistant"]["stub"]["available"] is True
    assert report["classification_assistant"]["__family__"]["chain_available"] is True
    assert report["classification_assistant"]["__family__"]["selected_provider"] == "stub"
