import textwrap
from datetime import date

from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.database_manager import init_database, reset_database
from app.imports.providers import ProviderRegistry
from app.models.classification import ClassificationSession, ClassificationSessionStatus
from app.models.transaction import Transaction, TransactionType
from app.services.classifier_providers import StubClassifierProvider
from app.services.classification_session_service import ClassificationSessionService


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


def test_transaction_model_declares_recurrence_pattern_foreign_key():
    foreign_keys = {fk.target_fullname for fk in Transaction.__table__.c.recurrence_pattern_id.foreign_keys}

    assert foreign_keys == {"recurrence_patterns.id"}


def test_create_or_resume_session_recovers_from_integrity_error(monkeypatch):
    init_database()
    reset_database()

    db_session = SessionLocal()
    transaction = Transaction(
        account_number="BE10000000000001",
        transaction_date=date(2025, 1, 1),
        amount=-42.50,
        currency="EUR",
        description="PROXIMUS telecom invoice",
        transaction_type=TransactionType.EXPENSE,
        source_bank="ing",
    )
    db_session.add(transaction)
    db_session.commit()
    db_session.refresh(transaction)

    provider = StubClassifierProvider(name="stub", model_name="stub-classifier-v1")
    monkeypatch.setattr(ClassificationSessionService, "_build_provider", classmethod(lambda cls: provider))

    original_commit = db_session.commit
    state = {"raised": False}

    def racing_commit():
        if state["raised"]:
            return original_commit()

        competing_db = SessionLocal()
        try:
            competing_session = ClassificationSession(
                transaction_id=transaction.id,
                status=ClassificationSessionStatus.OPEN,
                provider_name="stub",
                model_name="stub-classifier-v1",
            )
            competing_db.add(competing_session)
            competing_db.commit()
        finally:
            competing_db.close()
        state["raised"] = True
        raise IntegrityError("insert", {}, Exception("duplicate open session"))

    monkeypatch.setattr(db_session, "commit", racing_commit)

    session = ClassificationSessionService.create_or_resume_session(db_session, transaction.id)

    assert session.transaction_id == transaction.id
    assert session.status == ClassificationSessionStatus.OPEN
    assert session.provider_name == "stub"
    assert session.model_name == "stub-classifier-v1"
    db_session.close()
