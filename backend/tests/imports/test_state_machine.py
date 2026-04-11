import pytest

from app.imports.state_machine import ImportSessionStatus, assert_transition_allowed


def test_committed_state_requires_approved_chain():
    assert_transition_allowed(ImportSessionStatus.APPROVED, ImportSessionStatus.COMMITTING)
    assert_transition_allowed(ImportSessionStatus.COMMITTING, ImportSessionStatus.COMMITTED)


def test_failed_and_rejected_sessions_can_retry_through_detection():
    assert_transition_allowed(ImportSessionStatus.FAILED, ImportSessionStatus.DETECTED)
    assert_transition_allowed(ImportSessionStatus.REJECTED, ImportSessionStatus.DETECTED)


def test_invalid_transition_raises():
    with pytest.raises(ValueError):
        assert_transition_allowed(ImportSessionStatus.UPLOADED, ImportSessionStatus.COMMITTED)
