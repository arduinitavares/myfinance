"""Module for backend tests imports test_state_machine."""

import pytest
from app.imports.state_machine import ImportSessionStatus, assert_transition_allowed


def test_committed_state_requires_approved_chain() -> None:
    """Verify committed state requires approved chain."""
    assert_transition_allowed(
        ImportSessionStatus.APPROVED, ImportSessionStatus.COMMITTING
    )
    assert_transition_allowed(
        ImportSessionStatus.COMMITTING, ImportSessionStatus.COMMITTED
    )


def test_failed_and_rejected_sessions_can_retry_through_detection() -> None:
    """Verify failed and rejected sessions can retry through detection."""
    assert_transition_allowed(ImportSessionStatus.FAILED, ImportSessionStatus.DETECTED)
    assert_transition_allowed(
        ImportSessionStatus.REJECTED, ImportSessionStatus.DETECTED
    )


def test_invalid_transition_raises() -> None:
    """Verify invalid transition raises."""
    with pytest.raises(ValueError, match="Invalid import session transition"):
        assert_transition_allowed(
            ImportSessionStatus.UPLOADED, ImportSessionStatus.COMMITTED
        )
