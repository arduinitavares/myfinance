from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..models.classification import RecurrencePattern
from ..models.transaction import Transaction, TransactionType
from ..services.anomaly_detection_service import AnomalyDetectionService
from ..services.csv_parser import CSVParser
from ..services.statistics_service import StatisticsService
from ..utils.text_normalization import normalize_for_matching


logger = logging.getLogger(__name__)

MAX_ROWS_PER_CSV_IMPORT = 5000
MAX_NEW_TRANSACTIONS_PER_CSV_IMPORT = 2000


@dataclass
class CsvImportResult:
    imported_transactions: list[Transaction]
    skipped_duplicate_count: int
    parsed_count: int

    @property
    def imported_count(self) -> int:
        return len(self.imported_transactions)


def _find_recurrence_pattern(db: Session, transaction: Transaction) -> RecurrencePattern | None:
    from ..services.classification_session_service import recurrence_pattern_matches_transaction

    normalized_description_key = normalize_for_matching(transaction.description)
    candidates = (
        db.query(RecurrencePattern)
        .filter(
            RecurrencePattern.active.is_(True),
            RecurrencePattern.normalized_description_key == normalized_description_key,
            RecurrencePattern.currency == transaction.currency,
        )
        .order_by(RecurrencePattern.id.asc())
        .all()
    )

    def _priority(pattern: RecurrencePattern) -> tuple[int, int]:
        if pattern.source_bank == transaction.source_bank:
            return (0, pattern.id)
        if pattern.source_bank is None:
            return (1, pattern.id)
        return (2, pattern.id)

    for candidate in sorted(candidates, key=_priority):
        if recurrence_pattern_matches_transaction(candidate, transaction):
            return candidate
    return None


class CsvImportService:
    @staticmethod
    def import_file(
        db: Session,
        *,
        file_path: str,
        source_filename: str,
    ) -> CsvImportResult:
        from ..services.classification_commit_service import commit_category_change
        from ..routers.suggestions import category_suggestion_service

        try:
            transactions = CSVParser.parse_csv(file_path, source_filename)
            if len(transactions) > MAX_ROWS_PER_CSV_IMPORT:
                raise ValueError(
                    f"CSV contains {len(transactions)} rows. The maximum allowed per upload is {MAX_ROWS_PER_CSV_IMPORT}."
                )

            db_transactions: list[Transaction] = []
            skipped_count = 0

            for trans in transactions:
                existing_transaction = db.query(Transaction).filter(
                    Transaction.account_number == trans.account_number,
                    Transaction.transaction_date == trans.transaction_date,
                    Transaction.amount == trans.amount,
                    Transaction.description == trans.description,
                    Transaction.source_bank == trans.source_bank,
                ).first()

                if existing_transaction:
                    logger.warning(
                        "Skipping duplicate transaction: %s on %s for %s %s",
                        trans.description,
                        trans.transaction_date,
                        trans.amount,
                        trans.currency,
                    )
                    skipped_count += 1
                    continue

                recurrence_pattern = _find_recurrence_pattern(db, trans)
                db_trans = Transaction(**trans.model_dump())
                db.add(db_trans)
                db.flush()

                if recurrence_pattern is not None:
                    logger.info(
                        "Applying recurrence pattern %s to transaction %s",
                        recurrence_pattern.id,
                        trans.description,
                    )
                    db_trans = commit_category_change(
                        db=db,
                        transaction=db_trans,
                        transaction_type=recurrence_pattern.transaction_type,
                        category=recurrence_pattern.category,
                        classification_source="recurrence_pattern",
                        recurrence_pattern_id=recurrence_pattern.id,
                        commit=False,
                    )
                else:
                    suggestions = []
                    if trans.transaction_type != TransactionType.TRANSFER:
                        suggestions = category_suggestion_service.suggest_category(
                            trans.description,
                            trans.amount,
                            trans.transaction_type,
                        )

                    if suggestions and suggestions[0][1] > 0.5:
                        best_category, confidence = suggestions[0]
                        logger.info(
                            "Setting category %s with confidence %s for transaction: %s",
                            best_category,
                            confidence,
                            trans.description,
                        )
                        db_trans = commit_category_change(
                            db=db,
                            transaction=db_trans,
                            transaction_type=db_trans.transaction_type,
                            category=best_category,
                            classification_source="upload_suggester",
                            recurrence_pattern_id=None,
                            commit=False,
                        )

                db_transactions.append(db_trans)

                if len(db_transactions) >= MAX_NEW_TRANSACTIONS_PER_CSV_IMPORT:
                    logger.info(
                        "Reached per-upload creation cap of %s new transactions; remaining rows will be ignored.",
                        MAX_NEW_TRANSACTIONS_PER_CSV_IMPORT,
                    )
                    break

            if skipped_count > 0:
                logger.info("Skipped %s duplicate transactions during import", skipped_count)

            if not db_transactions:
                logger.warning("No new transactions were imported - all were duplicates")
                return CsvImportResult(
                    imported_transactions=[],
                    skipped_duplicate_count=skipped_count,
                    parsed_count=len(transactions),
                )

            db.commit()

            affected_dates = sorted({transaction.transaction_date for transaction in db_transactions})
            for transaction_date in affected_dates:
                try:
                    StatisticsService.update_statistics(db, transaction_date)
                except Exception as exc:
                    db.rollback()
                    logger.warning("Failed to update statistics for %s: %s", transaction_date, exc)

            for trans in db_transactions:
                db.refresh(trans)
                if (
                    trans.transaction_type in {TransactionType.EXPENSE, TransactionType.INCOME}
                    and (trans.expense_category or trans.income_category)
                ):
                    try:
                        category_suggestion_service.add_transaction(trans)
                    except Exception as exc:
                        logger.warning(
                            "Failed to update suggestion index for transaction %s: %s",
                            trans.id,
                            exc,
                        )

            try:
                transaction_ids = [t.id for t in db_transactions]
                AnomalyDetectionService.detect_anomalies(
                    db=db,
                    transaction_ids=transaction_ids,
                    force_redetection=False,
                )
                logger.info("Anomaly detection completed for %s new transactions", len(transaction_ids))
            except Exception as exc:
                logger.warning("Anomaly detection failed for new transactions: %s", exc)

            return CsvImportResult(
                imported_transactions=db_transactions,
                skipped_duplicate_count=skipped_count,
                parsed_count=len(transactions),
            )
        except ValueError:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            raise
