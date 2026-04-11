from enum import Enum


class ImportSessionStatus(str, Enum):
    UPLOADED = "uploaded"
    DETECTED = "detected"
    EXTRACTED = "extracted"
    NORMALIZED = "normalized"
    VALIDATED = "validated"
    AWAITING_REVIEW = "awaiting_review"
    APPROVED = "approved"
    COMMITTING = "committing"
    COMMITTED = "committed"
    FAILED = "failed"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    PARTIALLY_COMMITTED = "partially_committed"


ALLOWED_STATUS_TRANSITIONS = {
    ImportSessionStatus.UPLOADED: {ImportSessionStatus.DETECTED, ImportSessionStatus.FAILED},
    ImportSessionStatus.DETECTED: {ImportSessionStatus.EXTRACTED, ImportSessionStatus.FAILED},
    ImportSessionStatus.EXTRACTED: {ImportSessionStatus.NORMALIZED, ImportSessionStatus.FAILED},
    ImportSessionStatus.NORMALIZED: {ImportSessionStatus.VALIDATED, ImportSessionStatus.FAILED},
    ImportSessionStatus.VALIDATED: {ImportSessionStatus.AWAITING_REVIEW, ImportSessionStatus.FAILED},
    ImportSessionStatus.AWAITING_REVIEW: {
        ImportSessionStatus.APPROVED,
        ImportSessionStatus.REJECTED,
        ImportSessionStatus.SUPERSEDED,
    },
    ImportSessionStatus.APPROVED: {ImportSessionStatus.COMMITTING},
    ImportSessionStatus.COMMITTING: {
        ImportSessionStatus.COMMITTED,
        ImportSessionStatus.PARTIALLY_COMMITTED,
        ImportSessionStatus.FAILED,
    },
    ImportSessionStatus.REJECTED: {ImportSessionStatus.DETECTED, ImportSessionStatus.SUPERSEDED},
    ImportSessionStatus.FAILED: {ImportSessionStatus.DETECTED, ImportSessionStatus.SUPERSEDED},
}


def assert_transition_allowed(current: ImportSessionStatus, target: ImportSessionStatus) -> None:
    allowed = ALLOWED_STATUS_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise ValueError(f"Invalid import session transition: {current} -> {target}")
