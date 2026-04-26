"""Module for backend app imports dedupe."""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..models.imports import ImportSession
from .state_machine import (
    ALLOWED_STATUS_TRANSITIONS,
    ImportSessionStatus,
    assert_transition_allowed,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.engine import Engine

LEGACY_DUPLICATE_HASH_SUFFIX: str = "#legacy-duplicate#"
MIN_DUPLICATE_GROUP_SIZE: int = 2


def get_import_sessions_by_file_hash(
    db: Session, file_hash: str
) -> list[ImportSession]:
    """Return import sessions by file hash."""
    return (
        db.query(ImportSession)
        .filter(ImportSession.file_hash == file_hash)
        .order_by(ImportSession.created_at.asc(), ImportSession.id.asc())
        .all()
    )


def is_retryable_failed_session(session: ImportSession, artifact_root: Path) -> bool:
    """Handle is retryable failed session."""
    if session.status != ImportSessionStatus.FAILED.value:
        return False
    if session.strategy_key != "pdf_statement":
        return False
    original_file = (
        Path(artifact_root) / str(session.id) / "original" / session.file_name
    )
    return original_file.exists()


def choose_canonical_import_session(
    sessions: Sequence[ImportSession], artifact_root: Path
) -> ImportSession:
    """Handle choose canonical import session."""
    if not sessions:
        msg = "choose_canonical_import_session requires at least one session"
        raise ValueError(msg)

    return min(
        sessions, key=lambda session: _canonical_sort_key(session, artifact_root)
    )


def is_replaceable_duplicate_owner(session: ImportSession, artifact_root: Path) -> bool:
    """Handle is replaceable duplicate owner."""
    return (
        session.status == ImportSessionStatus.FAILED.value
        and not is_retryable_failed_session(session, artifact_root)
    )


def rewrite_import_session_as_legacy_duplicate(session: ImportSession) -> None:
    """Handle rewrite import session as legacy duplicate."""
    if session.file_hash is None:
        msg = "rewrite_import_session_as_legacy_duplicate requires a file_hash"
        raise ValueError(msg)
    session.file_hash = _legacy_duplicate_hash(session.file_hash, session.id)
    _supersede_if_allowed(session)


def ensure_import_session_file_hash_uniqueness(
    engine: Engine, artifact_root: Path
) -> None:
    """Handle ensure import session file hash uniqueness."""
    with Session(engine) as db:
        sessions = (
            db.query(ImportSession)
            .order_by(
                ImportSession.file_hash.asc(),
                ImportSession.created_at.asc(),
                ImportSession.id.asc(),
            )
            .all()
        )
        grouped_sessions: dict[str, list[ImportSession]] = defaultdict(list)
        for session in sessions:
            grouped_sessions[session.file_hash].append(session)

        for original_hash, hash_group in grouped_sessions.items():
            if len(hash_group) < MIN_DUPLICATE_GROUP_SIZE:
                continue

            canonical_session = choose_canonical_import_session(
                hash_group, artifact_root
            )
            for session in hash_group:
                if session.id == canonical_session.id:
                    continue
                session.file_hash = _legacy_duplicate_hash(original_hash, session.id)
                _supersede_if_allowed(session)

        db.commit()

    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_import_sessions_file_hash "
                "ON import_sessions (file_hash)"
            )
        )


def _canonical_sort_key(
    session: ImportSession, artifact_root: Path
) -> tuple[int, datetime, int]:
    return (
        _status_rank(session, artifact_root),
        _created_at_sort_value(session.created_at),
        session.id if session.id is not None else sys.maxsize,
    )


def _status_rank(session: ImportSession, artifact_root: Path) -> int:
    status = session.status
    if status in {
        ImportSessionStatus.COMMITTED.value,
        ImportSessionStatus.PARTIALLY_COMMITTED.value,
    }:
        return 0
    if status == ImportSessionStatus.AWAITING_REVIEW.value:
        return 1
    if is_retryable_failed_session(session, artifact_root):
        return 2
    return 3


def _created_at_sort_value(created_at: datetime | None) -> datetime:
    if created_at is None:
        return datetime.max.replace(tzinfo=None)
    if created_at.tzinfo is not None:
        return created_at.astimezone(UTC).replace(tzinfo=None)
    return created_at


def _legacy_duplicate_hash(original_hash: str, session_id: int | None) -> str:
    return f"{original_hash}{LEGACY_DUPLICATE_HASH_SUFFIX}{session_id}"


def _supersede_if_allowed(session: ImportSession) -> None:
    current_status = ImportSessionStatus(session.status)
    if current_status in {
        ImportSessionStatus.COMMITTED,
        ImportSessionStatus.PARTIALLY_COMMITTED,
    }:
        return
    if current_status == ImportSessionStatus.SUPERSEDED:
        return
    allowed = ALLOWED_STATUS_TRANSITIONS.get(current_status, set())
    if ImportSessionStatus.SUPERSEDED in allowed:
        assert_transition_allowed(current_status, ImportSessionStatus.SUPERSEDED)
        session.status = ImportSessionStatus.SUPERSEDED.value
