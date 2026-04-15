import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.classification import RecurrencePattern
from app.models.imports import ImportSession
from app.models.transaction import Transaction, TransactionType, TransferCategory
from app.services.financial_health_service import FinancialHealthService
from app.services.statistics_service import StatisticsService


logger = logging.getLogger(__name__)


KNOWN_IBAN_ROLE_MAP = {
    "BE11950212984548": "cash_account",
    "BE46063651946836": "cash_account",
    "BE36950263030181": "credit_reimbursement_account",
    "BE74950226230607": "loan_account",
}

BEOBANK_MASTERCARD_EXTRACTOR_ID = "beobank_mastercard_pdf_v1"


def _normalize_identifier(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.upper().replace(" ", "")
    return normalized or None


def _known_role_for_iban(normalized: str | None) -> str | None:
    if normalized is None:
        return None
    return KNOWN_IBAN_ROLE_MAP.get(normalized)


def _contains_known_iban(text: str | None) -> str | None:
    normalized_text = _normalize_identifier(text)
    if normalized_text is None:
        return None

    for iban in KNOWN_IBAN_ROLE_MAP:
        if iban in normalized_text:
            return iban
    return None


def _local_role_for_transaction(db: Session, transaction: Transaction) -> str | None:
    local_role = _known_role_for_iban(_normalize_identifier(transaction.account_number))
    if local_role is not None:
        return local_role

    if transaction.import_session_id is None:
        return None

    import_session = db.get(ImportSession, transaction.import_session_id)
    if import_session and import_session.extractor_id == BEOBANK_MASTERCARD_EXTRACTOR_ID:
        return "credit_reimbursement_account"
    return None


def _counterparty_role_for_transaction(transaction: Transaction) -> str | None:
    counterparty_role = _known_role_for_iban(_normalize_identifier(transaction.counterparty_account))
    if counterparty_role is not None:
        return counterparty_role

    import_source_iban = _contains_known_iban(transaction.import_source_description)
    if import_source_iban is not None:
        return _known_role_for_iban(import_source_iban)

    description_iban = _contains_known_iban(transaction.description)
    if description_iban is not None:
        return _known_role_for_iban(description_iban)

    return None


def _desired_transfer_category(
    local_role: str | None,
    counterparty_role: str | None,
) -> TransferCategory | None:
    if local_role is None or counterparty_role is None:
        return None

    roles = {local_role, counterparty_role}
    if roles == {"cash_account"}:
        return TransferCategory.INTERNAL_TRANSFER
    if roles == {"cash_account", "credit_reimbursement_account"}:
        return TransferCategory.CREDIT_CARD_SETTLEMENT
    if roles == {"cash_account", "loan_account"}:
        return TransferCategory.DEBT_REPAYMENT_SENT
    return None


def _contains_wise_signal(transaction: Transaction) -> bool:
    texts = [transaction.description, transaction.import_source_description]
    return any(text and "wise" in text.lower() for text in texts)


def _has_parser_artifact(transaction: Transaction, db: Session) -> bool:
    texts = [transaction.description, transaction.import_source_description]
    if not any(text and "-2" in text for text in texts):
        return False

    import_session = None
    if transaction.import_session_id is not None:
        import_session = db.get(ImportSession, transaction.import_session_id)

    extractor_id = import_session.extractor_id if import_session else None
    normalized_description = _normalize_identifier(transaction.description) or ""
    normalized_source = _normalize_identifier(transaction.import_source_description) or ""
    return (
        extractor_id == BEOBANK_MASTERCARD_EXTRACTOR_ID
        and ("BETALING" in normalized_description or "BETALING" in normalized_source)
    )


def _pattern_conflicts_with_transfer_semantics(
    pattern: RecurrencePattern | None,
    desired_category: TransferCategory,
) -> bool:
    if pattern is None or not pattern.active:
        return False
    return (
        pattern.transaction_type != TransactionType.TRANSFER
        or pattern.category != desired_category.value
    )


def _post_pass_conflict_details(db: Session, corrected_transaction_ids: list[int]) -> list[dict[str, Any]]:
    if not corrected_transaction_ids:
        return []

    conflicting_rows = (
        db.query(Transaction, RecurrencePattern)
        .join(RecurrencePattern, Transaction.recurrence_pattern_id == RecurrencePattern.id)
        .filter(Transaction.id.in_(corrected_transaction_ids), RecurrencePattern.active.is_(True))
        .all()
    )

    conflicts: list[dict[str, Any]] = []
    for transaction, pattern in conflicting_rows:
        if transaction.transfer_category is None:
            conflicts.append(
                {
                    "transaction_id": transaction.id,
                    "pattern_id": pattern.id,
                    "reason": "corrected transaction lost transfer category",
                }
            )
            continue

        if (
            pattern.transaction_type != TransactionType.TRANSFER
            or pattern.category != transaction.transfer_category.value
        ):
            conflicts.append(
                {
                    "transaction_id": transaction.id,
                    "pattern_id": pattern.id,
                    "pattern_type": pattern.transaction_type.value,
                    "pattern_category": pattern.category,
                    "transaction_category": transaction.transfer_category.value,
                }
            )
    return conflicts


def migrate_europe_iban_reclassification(db: Session) -> dict[str, int]:
    summary = {
        "updated_transactions": 0,
        "skipped_wise": 0,
        "skipped_ambiguous": 0,
        "skipped_parser_artifact": 0,
        "deactivated_patterns": 0,
        "detached_transactions": 0,
        "recomputed_aggregates": 0,
    }
    corrected_transaction_ids: list[int] = []

    try:
        transactions = db.query(Transaction).order_by(Transaction.id.asc()).all()

        for transaction in transactions:
            if _contains_wise_signal(transaction):
                summary["skipped_wise"] += 1
                continue

            if _has_parser_artifact(transaction, db):
                summary["skipped_parser_artifact"] += 1
                continue

            local_role = _local_role_for_transaction(db, transaction)
            counterparty_role = _counterparty_role_for_transaction(transaction)
            desired_category = _desired_transfer_category(local_role, counterparty_role)

            if desired_category is None:
                summary["skipped_ambiguous"] += 1
                continue

            if transaction.transfer_category == desired_category:
                continue

            transaction.transaction_type = TransactionType.TRANSFER
            transaction.transfer_category = desired_category
            transaction.expense_category = None
            transaction.income_category = None
            summary["updated_transactions"] += 1
            corrected_transaction_ids.append(transaction.id)

            pattern = None
            if transaction.recurrence_pattern_id is not None:
                pattern = db.get(RecurrencePattern, transaction.recurrence_pattern_id)

            if _pattern_conflicts_with_transfer_semantics(pattern, desired_category):
                pattern.active = False
                transaction.recurrence_pattern_id = None
                summary["deactivated_patterns"] += 1
                summary["detached_transactions"] += 1

        db.flush()

        conflicts = _post_pass_conflict_details(db, corrected_transaction_ids)
        if conflicts:
            raise RuntimeError(
                "Corrected transactions still reference conflicting active recurrence patterns: "
                f"{conflicts}"
            )

        data_changed = summary["updated_transactions"] > 0 or summary["deactivated_patterns"] > 0
        db.commit()

        if data_changed:
            StatisticsService.initialize_statistics(db)
            StatisticsService.initialize_category_statistics(db)
            FinancialHealthService.initialize_financial_health(db)
            summary["recomputed_aggregates"] = 1

        return summary
    except Exception:
        db.rollback()
        logger.exception("Europe IBAN cleanup migration failed")
        raise
