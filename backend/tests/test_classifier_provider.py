import textwrap
from datetime import date
import sqlite3

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database import SessionLocal, enable_sqlite_foreign_keys
from app.database_manager import init_database, reset_database
from app.imports.providers import ProviderRegistry
from app.migrations import migrate_classification_assistant as migration_module
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


def test_migrate_classification_assistant_rebuilds_transactions_with_foreign_key(tmp_path, monkeypatch):
    db_path = tmp_path / "classification-migration.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(
            """
            CREATE TABLE transactions (
                id INTEGER NOT NULL PRIMARY KEY,
                account_number VARCHAR(50),
                transaction_date DATE,
                amount FLOAT,
                currency VARCHAR(3),
                description VARCHAR(500),
                counterparty_name VARCHAR(200),
                counterparty_account VARCHAR(50),
                transaction_type VARCHAR(8),
                expense_category VARCHAR(20),
                income_category VARCHAR(20),
                source_bank VARCHAR(10)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO transactions (
                id, account_number, transaction_date, amount, currency, description,
                counterparty_name, counterparty_account, transaction_type, expense_category,
                income_category, source_bank
            ) VALUES (1, 'BE10000000000001', '2025-01-01', -42.5, 'EUR', 'PROXIMUS telecom invoice',
                      'Counterparty', 'BE20000000000002', 'EXPENSE', 'UTILITIES', NULL, 'ing')
            """
        )
        conn.commit()
    finally:
        conn.close()

    temp_engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(migration_module, "engine", temp_engine)

    migration_module.migrate_classification_assistant()
    migration_module.migrate_classification_assistant()

    verify_conn = sqlite3.connect(db_path)
    try:
        columns = {
            row[1]: row
            for row in verify_conn.execute("PRAGMA table_info(transactions)").fetchall()
        }
        foreign_keys = verify_conn.execute("PRAGMA foreign_key_list(transactions)").fetchall()
        rows = verify_conn.execute(
            "SELECT id, classification_source, recurrence_pattern_id, description FROM transactions"
        ).fetchall()
    finally:
        verify_conn.close()
        temp_engine.dispose()

    assert "classification_source" in columns
    assert "recurrence_pattern_id" in columns
    assert any(fk[3] == "recurrence_pattern_id" and fk[2] == "recurrence_patterns" and fk[4] == "id" for fk in foreign_keys)
    assert rows == [(1, None, None, "PROXIMUS telecom invoice")]


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


def test_session_layer_enforces_recurrence_pattern_foreign_key():
    temp_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    event.listen(temp_engine, "connect", enable_sqlite_foreign_keys)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=temp_engine)

    original_engine = migration_module.engine
    migration_module.engine = temp_engine
    try:
        raw_conn = temp_engine.raw_connection()
        try:
            cursor = raw_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=OFF")
            cursor.execute(
                """
                CREATE TABLE transactions (
                    id INTEGER NOT NULL PRIMARY KEY,
                    account_number VARCHAR(50),
                    transaction_date DATE,
                    amount FLOAT,
                    currency VARCHAR(3),
                    description VARCHAR(500),
                    counterparty_name VARCHAR(200),
                    counterparty_account VARCHAR(50),
                    transaction_type VARCHAR(8),
                    expense_category VARCHAR(20),
                    income_category VARCHAR(20),
                    source_bank VARCHAR(10)
                )
                """
            )
            raw_conn.commit()
        finally:
            raw_conn.close()

        migration_module.migrate_classification_assistant()

        db_session = session_factory()
        transaction = Transaction(
            account_number="BE10000000000001",
            transaction_date=date(2025, 1, 1),
            amount=-42.50,
            currency="EUR",
            description="PROXIMUS telecom invoice",
            transaction_type=TransactionType.EXPENSE,
            source_bank="ing",
            recurrence_pattern_id=999999,
        )
        db_session.add(transaction)

        with pytest.raises(IntegrityError):
            db_session.commit()

        db_session.rollback()
        db_session.close()
    finally:
        migration_module.engine = original_engine
        temp_engine.dispose()
