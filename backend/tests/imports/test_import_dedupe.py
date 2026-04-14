from __future__ import annotations

from datetime import datetime

from sqlalchemy import create_engine, inspect, text

import app.database_manager as database_manager
from app.imports.artifacts import ArtifactStore
from app.imports.dedupe import choose_canonical_import_session
from app.imports.state_machine import ImportSessionStatus
from app.models.imports import ImportSession


def _session(
    *,
    session_id: int,
    status: str,
    created_at: datetime,
    file_name: str = "statement.pdf",
    file_hash: str = "shared-hash",
    strategy_key: str | None = None,
) -> ImportSession:
    return ImportSession(
        id=session_id,
        file_name=file_name,
        file_hash=file_hash,
        mime_type="application/pdf",
        status=status,
        strategy_key=strategy_key,
        created_at=created_at,
        updated_at=created_at,
    )


def test_canonical_selection_prefers_awaiting_review_over_older_failed_session(tmp_path):
    artifact_root = tmp_path / "imports"
    artifacts = ArtifactStore(root=artifact_root)
    older_failed = _session(
        session_id=2,
        status=ImportSessionStatus.FAILED.value,
        created_at=datetime(2024, 1, 1, 12, 0, 0),
    )
    awaiting_review = _session(
        session_id=3,
        status=ImportSessionStatus.AWAITING_REVIEW.value,
        created_at=datetime(2024, 1, 2, 12, 0, 0),
    )

    canonical = choose_canonical_import_session([older_failed, awaiting_review], artifact_root=artifacts.root)

    assert canonical.id == awaiting_review.id


def test_retryable_failed_session_requires_pdf_statement_and_original_file(tmp_path):
    artifact_root = tmp_path / "imports"
    artifacts = ArtifactStore(root=artifact_root)
    retryable = _session(
        session_id=4,
        status=ImportSessionStatus.FAILED.value,
        created_at=datetime(2024, 1, 1, 12, 0, 0),
        strategy_key="pdf_statement",
    )
    non_retryable_strategy = _session(
        session_id=5,
        status=ImportSessionStatus.FAILED.value,
        created_at=datetime(2024, 1, 1, 13, 0, 0),
        strategy_key="csv_import",
    )
    non_retryable_missing_artifact = _session(
        session_id=6,
        status=ImportSessionStatus.FAILED.value,
        created_at=datetime(2024, 1, 1, 14, 0, 0),
        strategy_key="pdf_statement",
    )

    artifacts.write_original_file(str(retryable.id), retryable.file_name, b"%PDF-1.4")

    canonical = choose_canonical_import_session(
        [non_retryable_strategy, non_retryable_missing_artifact, retryable],
        artifact_root=artifacts.root,
    )

    assert canonical.id == retryable.id


def test_canonical_selection_prefers_committed_over_awaiting_review(tmp_path):
    artifact_root = tmp_path / "imports"
    committed = _session(
        session_id=7,
        status=ImportSessionStatus.COMMITTED.value,
        created_at=datetime(2024, 1, 3, 12, 0, 0),
    )
    awaiting_review = _session(
        session_id=8,
        status=ImportSessionStatus.AWAITING_REVIEW.value,
        created_at=datetime(2024, 1, 4, 12, 0, 0),
    )

    canonical = choose_canonical_import_session([awaiting_review, committed], artifact_root=artifact_root)

    assert canonical.id == committed.id


def test_uniqueness_backfill_rewrites_non_canonical_duplicate_hashes_and_preserves_canonical_owner(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "dedupe.sqlite"
    temp_engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    artifact_root = tmp_path / "imports"
    artifact_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(database_manager, "engine", temp_engine)
    monkeypatch.setattr(database_manager, "_import_artifact_root", lambda: artifact_root)

    with temp_engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE import_sessions (
                    id INTEGER PRIMARY KEY,
                    file_name VARCHAR(255) NOT NULL,
                    file_hash VARCHAR(128) NOT NULL,
                    mime_type VARCHAR(100) NOT NULL,
                    status VARCHAR(50) NOT NULL,
                    strategy_key VARCHAR(50),
                    provider_hint VARCHAR(50),
                    language_hint VARCHAR(20),
                    charset_hint VARCHAR(50),
                    extractor_id VARCHAR(100),
                    raw_artifact_ref VARCHAR(255),
                    error_stage VARCHAR(50),
                    error_message TEXT,
                    approved_by VARCHAR(100),
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO import_sessions (
                    id, file_name, file_hash, mime_type, status, strategy_key,
                    created_at, updated_at
                ) VALUES
                    (1, 'statement-a.pdf', 'duplicate-hash', 'application/pdf', 'failed', 'pdf_statement',
                     '2024-01-01 12:00:00', '2024-01-01 12:00:00'),
                    (2, 'statement-b.pdf', 'duplicate-hash', 'application/pdf', 'awaiting_review', NULL,
                     '2024-01-02 12:00:00', '2024-01-02 12:00:00'),
                    (3, 'statement-c.pdf', 'duplicate-hash', 'application/pdf', 'detected', NULL,
                     '2024-01-03 12:00:00', '2024-01-03 12:00:00')
                """
            )
        )
        artifact_store = ArtifactStore(root=artifact_root)
        artifact_store.write_original_file("1", "statement-a.pdf", b"%PDF-1.4")

    database_manager.init_database()

    with temp_engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, file_hash, status FROM import_sessions ORDER BY id")
        ).mappings().all()

    assert rows == [
        {"id": 1, "file_hash": "duplicate-hash#legacy-duplicate#1", "status": "superseded"},
        {"id": 2, "file_hash": "duplicate-hash", "status": "awaiting_review"},
        {"id": 3, "file_hash": "duplicate-hash#legacy-duplicate#3", "status": "detected"},
    ]


def test_unique_index_exists_after_init_database(tmp_path, monkeypatch):
    db_path = tmp_path / "unique.sqlite"
    temp_engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})

    monkeypatch.setattr(database_manager, "engine", temp_engine)
    database_manager.init_database()

    indexes = inspect(temp_engine).get_indexes("import_sessions")

    assert any(index["unique"] and "file_hash" in index["column_names"] for index in indexes)
