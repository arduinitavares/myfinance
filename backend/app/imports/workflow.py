import json
import logging
import re
from calendar import monthrange
from datetime import date, datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.imports.belfius_csv import BelfiusCsvExtractor
from app.imports.beobank_csv import BeobankCsvExtractor
from app.models.imports import (
    ImportIssue as ImportIssueModel,
    ImportSession,
    ImportStatementDraft,
    ImportTransactionDraft,
)
from app.models.statistics import CategoryStatistics, FinancialStatistics, StatisticsPeriod
from app.models.transaction import Transaction, TransactionType
from app.schemas.imports import build_import_transaction_draft_response_payload
from app.schemas.transaction import TransactionCreate
from app.services.anomaly_detection_service import AnomalyDetectionService
from app.services.currency_conversion import CurrencyConversionService, DisplayMoney
from app.services.statistics_service import StatisticsService
from app.routers.suggestions import category_suggestion_service

from .artifacts import ArtifactStore
from .contracts import ExtractionResult, ExtractedTransaction, ImportStrategyKey
from .enrichment import enrich_draft_proposals
from .nexo_csv import NexoCsvExtractor
from .pdf_statement import PdfStatementExtractor
from .state_machine import ImportSessionStatus, assert_transition_allowed

logger = logging.getLogger(__name__)


class ImportWorkflowError(Exception):
    pass


class ImportSessionNotFoundError(ImportWorkflowError):
    pass


class ImportSessionStateError(ImportWorkflowError):
    pass


class ImportApprovalConflictError(ImportWorkflowError):
    def __init__(self, duplicates: list[dict]) -> None:
        super().__init__("Approval would create duplicate committed transactions.")
        self.duplicates = duplicates


class ImportWorkflowService:
    def __init__(
        self,
        db: Session,
        pdf_statement_extractor: PdfStatementExtractor | None = None,
        belfius_csv_extractor: BelfiusCsvExtractor | None = None,
        beobank_csv_extractor: BeobankCsvExtractor | None = None,
        nexo_csv_extractor: NexoCsvExtractor | None = None,
        artifacts: ArtifactStore | None = None,
    ) -> None:
        self.db = db
        self.pdf_statement_extractor = pdf_statement_extractor or PdfStatementExtractor()
        self.belfius_csv_extractor = belfius_csv_extractor or BelfiusCsvExtractor()
        self.beobank_csv_extractor = beobank_csv_extractor or BeobankCsvExtractor()
        self.nexo_csv_extractor = nexo_csv_extractor or NexoCsvExtractor()
        self.artifacts = artifacts or ArtifactStore()

    def extract_detected_session(self, session_id: int) -> ImportSession:
        session = self._get_session(session_id)
        if session.status != ImportSessionStatus.DETECTED.value:
            raise ImportSessionStateError(f"Import session {session_id} must be in detected state.")

        attempt_number = self._next_attempt_number(session.id)
        original_file = self.artifacts.session_dir(str(session.id)) / "original" / session.file_name

        result: ExtractionResult | None = None
        try:
            if not original_file.exists():
                raise FileNotFoundError(f"Original upload missing for import session {session.id}.")
            extractor = self._extractor_for_strategy(session.strategy_key)
            if extractor is None:
                raise ImportSessionStateError(
                    f"Import session {session_id} uses unsupported strategy {session.strategy_key!r}."
                )
            evidence, result = extractor.extract(
                file_path=original_file,
                session_id=str(session.id),
                attempt_number=attempt_number,
            )
            self.artifacts.write_raw_evidence(str(session.id), attempt_number, evidence)
            self.artifacts.write_normalized_result(str(session.id), attempt_number, result)

            session.extractor_id = result.extractor_id
            session.raw_artifact_ref = result.raw_artifact_ref
            session.provider_hint = result.source_metadata.get("provider_hint") or session.provider_hint
            session.language_hint = result.source_metadata.get("language") or session.language_hint
            self._persist_issues(session.id, attempt_number, result)

            if any(issue.blocking for issue in result.issues):
                assert_transition_allowed(ImportSessionStatus(session.status), ImportSessionStatus.FAILED)
                session.status = ImportSessionStatus.FAILED.value
                session.error_stage = "extraction"
                session.error_message = self._failure_message(result)
            else:
                statement_draft = self._persist_statement_draft(session.id, attempt_number, result)
                self._enrich_csv_drafts_before_review(session, statement_draft)
                self._advance_to_awaiting_review(session)
                session.error_stage = None
                session.error_message = None

            self._write_workflow_meta(
                session_id=str(session.id),
                attempt_number=attempt_number,
                state=session.status,
                extraction_succeeded=result is not None,
            )
            self.db.commit()
            self.db.refresh(session)
            return session
        except Exception as exc:
            self.db.rollback()
            persisted_session = self.db.get(ImportSession, session_id)
            if persisted_session is None:
                raise
            if persisted_session.status == ImportSessionStatus.DETECTED.value:
                assert_transition_allowed(ImportSessionStatus.DETECTED, ImportSessionStatus.FAILED)
                persisted_session.status = ImportSessionStatus.FAILED.value
                persisted_session.error_stage = "extraction"
                persisted_session.error_message = str(exc)
                if result is None:
                    persisted_session.extractor_id = None
                    persisted_session.raw_artifact_ref = None
                else:
                    persisted_session.extractor_id = result.extractor_id
                    persisted_session.raw_artifact_ref = result.raw_artifact_ref
                try:
                    self._write_workflow_meta(
                        session_id=str(persisted_session.id),
                        attempt_number=attempt_number,
                        state=persisted_session.status,
                        extraction_succeeded=result is not None,
                    )
                except Exception:
                    logger.warning(
                        "Failed to sync import workflow manifest during rescue for session %s",
                        persisted_session.id,
                        exc_info=True,
                    )
                self.db.commit()
                self.db.refresh(persisted_session)
            raise

    def get_session_snapshot(self, session_id: int) -> dict:
        session = self._get_session(session_id)
        return self._serialize_session(session)

    def get_review_payload(self, session_id: int, *, reporting_currency: str) -> dict:
        session = self._get_session(session_id)
        attempt_number = self._latest_attempt_number(session.id)
        statement = self._latest_statement_draft(session.id, attempt_number) if attempt_number else None
        transactions = self._statement_transactions(statement.id) if statement is not None else []
        issues = self._issues_for_attempt(session.id, attempt_number) if attempt_number else []
        conversion_service = CurrencyConversionService(self.db)

        return {
            "session": self._serialize_session(session),
            "statement": self._serialize_statement(statement) if statement is not None else None,
            "transactions": [
                self._serialize_transaction_draft(
                    transaction,
                    conversion_service=conversion_service,
                    reporting_currency=reporting_currency,
                )
                for transaction in transactions
            ],
            "issues": [self._serialize_issue(issue) for issue in issues],
            "evidence": self._read_raw_evidence(session.id, attempt_number),
        }

    def approve_session(self, session_id: int) -> ImportSession:
        session = self._get_session(session_id)
        if session.status != ImportSessionStatus.AWAITING_REVIEW.value:
            raise ImportSessionStateError(f"Import session {session_id} must be awaiting review.")

        attempt_number = self._latest_attempt_number(session.id)
        issues = self._issues_for_attempt(session.id, attempt_number)
        if any(issue.blocking for issue in issues):
            raise ImportSessionStateError(
                f"Import session {session_id} cannot be approved while the latest attempt has blocking issues."
            )

        statement = self._latest_statement_draft(session.id, attempt_number)
        if statement is None:
            raise ImportSessionStateError(f"Import session {session_id} has no reviewable statement draft.")

        drafts = self._statement_transactions(statement.id)
        duplicates = self._find_duplicate_transactions(statement, drafts)
        if duplicates:
            raise ImportApprovalConflictError(duplicates)

        current = ImportSessionStatus(session.status)
        for target in (ImportSessionStatus.APPROVED, ImportSessionStatus.COMMITTING):
            assert_transition_allowed(current, target)
            session.status = target.value
            current = target

        statement.review_status = "approved"

        affected_dates: set[date] = set()
        committed_transactions: list[Transaction] = []
        for draft in drafts:
            transaction = self._build_committed_transaction(session.id, statement, draft)
            self.db.add(transaction)
            committed_transactions.append(transaction)
            if transaction.transaction_date is not None:
                affected_dates.add(transaction.transaction_date)

        try:
            self.db.flush()
            self._refresh_statistics_in_transaction(affected_dates)

            assert_transition_allowed(current, ImportSessionStatus.COMMITTED)
            session.status = ImportSessionStatus.COMMITTED.value
            committed_session = self._commit_session_state(session, meta_state=session.status)
            self._sync_category_suggestion_index(committed_transactions)
            self._run_anomaly_detection(committed_transactions)
            return committed_session
        except Exception:
            self.db.rollback()
            raise

    def reject_session(self, session_id: int) -> ImportSession:
        session = self._get_session(session_id)
        if session.status != ImportSessionStatus.AWAITING_REVIEW.value:
            raise ImportSessionStateError(f"Import session {session_id} must be awaiting review.")

        statement = self._latest_statement_draft(session.id, self._latest_attempt_number(session.id))
        if statement is not None:
            statement.review_status = "rejected"

        assert_transition_allowed(ImportSessionStatus(session.status), ImportSessionStatus.REJECTED)
        session.status = ImportSessionStatus.REJECTED.value
        return self._commit_session_state(session, meta_state=session.status)

    def retry_session(self, session_id: int) -> ImportSession:
        session = self._get_session(session_id)
        current_status = ImportSessionStatus(session.status)

        if current_status == ImportSessionStatus.AWAITING_REVIEW:
            statement = self._latest_statement_draft(session.id, self._latest_attempt_number(session.id))
            if statement is not None:
                statement.review_status = "superseded"
            assert_transition_allowed(current_status, ImportSessionStatus.REJECTED)
            session.status = ImportSessionStatus.REJECTED.value
            current_status = ImportSessionStatus.REJECTED
        elif current_status != ImportSessionStatus.FAILED:
            raise ImportSessionStateError(
                f"Import session {session_id} can only be retried from failed or awaiting_review state."
            )

        assert_transition_allowed(current_status, ImportSessionStatus.DETECTED)
        session.status = ImportSessionStatus.DETECTED.value
        session.error_stage = None
        session.error_message = None
        self._commit_session_state(session)

        return self.extract_detected_session(session.id)

    def _next_attempt_number(self, session_id: int) -> int:
        last_issue_attempt = (
            self.db.query(func.max(ImportIssueModel.attempt_number))
            .filter(ImportIssueModel.import_session_id == session_id)
            .scalar()
        )
        last_statement_attempt = (
            self.db.query(func.max(ImportStatementDraft.attempt_number))
            .filter(ImportStatementDraft.import_session_id == session_id)
            .scalar()
        )
        existing_artifact_attempts = self.artifacts.existing_attempt_numbers(str(session_id))
        meta_attempt_count = 0
        try:
            meta_payload = self.artifacts.read_meta(str(session_id))
        except Exception:
            logger.warning("Failed to read import meta for session %s when computing attempt number", session_id)
            meta_payload = {}

        raw_meta_attempt_count = meta_payload.get("attempt_count")
        if (
            isinstance(raw_meta_attempt_count, int)
            and (
                bool(last_issue_attempt)
                or bool(last_statement_attempt)
                or bool(existing_artifact_attempts)
                or meta_payload.get("state") == ImportSessionStatus.FAILED.value
            )
        ):
            meta_attempt_count = raw_meta_attempt_count
        return max(
            last_issue_attempt or 0,
            last_statement_attempt or 0,
            meta_attempt_count,
            *(existing_artifact_attempts or [0]),
        ) + 1

    def _latest_attempt_number(self, session_id: int) -> int:
        payload = self.artifacts.read_meta(str(session_id))
        attempt_count = payload.get("attempt_count")
        if isinstance(attempt_count, int):
            return attempt_count
        return self._next_attempt_number(session_id) - 1

    def _persist_issues(self, session_id: int, attempt_number: int, result: ExtractionResult) -> None:
        for issue in result.issues:
            self.db.add(
                ImportIssueModel(
                    import_session_id=session_id,
                    attempt_number=attempt_number,
                    severity="error" if issue.blocking else "warning",
                    blocking=issue.blocking,
                    issue_code=issue.code,
                    issue_message=issue.message,
                    transaction_ref=issue.transaction_ref,
                )
            )

    def _persist_statement_draft(
        self,
        session_id: int,
        attempt_number: int,
        result: ExtractionResult,
    ) -> ImportStatementDraft:
        metadata = result.statement_metadata
        statement_draft = ImportStatementDraft(
            import_session_id=session_id,
            attempt_number=attempt_number,
            statement_period_start=self._parse_iso_date(metadata.get("statement_period_start")),
            statement_period_end=self._parse_iso_date(metadata.get("statement_period_end")),
            transaction_count=len(result.transactions),
            account_number_hint=metadata.get("account_number_hint"),
            card_number_hint=metadata.get("card_number_hint"),
            currency=metadata.get("currency"),
            overall_confidence=result.overall_confidence,
            review_status="awaiting_review",
        )
        self.db.add(statement_draft)
        self.db.flush()

        for transaction in result.transactions:
            self.db.add(
                ImportTransactionDraft(
                    import_statement_draft_id=statement_draft.id,
                    transaction_date=self._parse_iso_date(transaction.transaction_date),
                    source_description=transaction.source_description,
                    canonical_description_en=transaction.canonical_description_en,
                    signed_amount=transaction.signed_amount,
                    currency=transaction.currency,
                    debit_credit=transaction.debit_credit,
                    source_locator=transaction.source_locator,
                    inferred_category=transaction.inferred_category,
                    category_source=transaction.category_source,
                    proposed_transaction_type=transaction.proposed_transaction_type,
                    proposed_expense_category=transaction.proposed_expense_category,
                    proposed_income_category=transaction.proposed_income_category,
                    proposed_transfer_category=transaction.proposed_transfer_category,
                    classification_source=transaction.classification_source,
                    recurrence_pattern_id=transaction.recurrence_pattern_id,
                    confidence=self._transaction_confidence(transaction, result),
                    field_confidence=json.dumps(transaction.confidence, sort_keys=True),
                    raw_fields=json.dumps(transaction.model_dump(mode="json"), sort_keys=True),
                    edit_source=transaction.edit_source,
                )
            )
        self.db.flush()
        return statement_draft

    def _latest_statement_draft(self, session_id: int, attempt_number: int) -> ImportStatementDraft | None:
        return (
            self.db.query(ImportStatementDraft)
            .filter(
                ImportStatementDraft.import_session_id == session_id,
                ImportStatementDraft.attempt_number == attempt_number,
            )
            .order_by(ImportStatementDraft.id.desc())
            .first()
        )

    def _statement_transactions(self, statement_draft_id: int) -> list[ImportTransactionDraft]:
        return (
            self.db.query(ImportTransactionDraft)
            .filter(ImportTransactionDraft.import_statement_draft_id == statement_draft_id)
            .order_by(ImportTransactionDraft.id.asc())
            .all()
        )

    def _issues_for_attempt(self, session_id: int, attempt_number: int) -> list[ImportIssueModel]:
        return (
            self.db.query(ImportIssueModel)
            .filter(
                ImportIssueModel.import_session_id == session_id,
                ImportIssueModel.attempt_number == attempt_number,
            )
            .order_by(ImportIssueModel.id.asc())
            .all()
        )

    def _build_committed_transaction(
        self,
        import_session_id: int,
        statement: ImportStatementDraft,
        draft: ImportTransactionDraft,
    ) -> Transaction:
        if draft.transaction_date is None:
            raise ImportSessionStateError(
                f"Import session {import_session_id} cannot approve a transaction draft without a transaction_date."
            )

        proposed_type = self._validated_transaction_type(draft)
        transaction_payload = TransactionCreate(
            account_number=self._statement_account_number(statement),
            transaction_date=draft.transaction_date,
            amount=draft.signed_amount,
            currency=draft.currency,
            description=draft.source_description,
            counterparty_name=None,
            counterparty_account=None,
            transaction_type=proposed_type.value if proposed_type is not None else None,
            expense_category=draft.proposed_expense_category,
            income_category=draft.proposed_income_category,
            transfer_category=draft.proposed_transfer_category,
            classification_source=draft.classification_source,
            recurrence_pattern_id=draft.recurrence_pattern_id,
            source_bank=self._source_bank_name(statement),
        )
        payload = transaction_payload.model_dump()
        payload["import_session_id"] = import_session_id
        payload["import_source_locator"] = draft.source_locator
        payload["import_source_description"] = draft.source_description
        payload["canonical_description_en"] = draft.canonical_description_en
        return Transaction(**payload)

    def _find_duplicate_transactions(
        self,
        statement: ImportStatementDraft,
        drafts: list[ImportTransactionDraft],
    ) -> list[dict]:
        duplicates: list[dict] = []

        for draft in drafts:
            existing_transactions = (
                self.db.query(Transaction)
                .filter(
                    Transaction.account_number == self._statement_account_number(statement),
                    Transaction.transaction_date == draft.transaction_date,
                    Transaction.amount == draft.signed_amount,
                    Transaction.currency == draft.currency,
                    Transaction.source_bank == self._source_bank_name(statement),
                )
                .all()
            )

            normalized_draft_description = self._normalize_description(draft.source_description)
            for transaction in existing_transactions:
                existing_description = transaction.import_source_description or transaction.description or ""
                if self._normalize_description(existing_description) == normalized_draft_description:
                    duplicates.append(
                        {
                            "transaction_id": transaction.id,
                            "source_description": draft.source_description,
                            "transaction_date": draft.transaction_date.isoformat()
                            if draft.transaction_date is not None
                            else None,
                            "signed_amount": draft.signed_amount,
                            "currency": draft.currency,
                        }
                    )
                    break

        return duplicates

    def _read_raw_evidence(self, session_id: int, attempt_number: int) -> dict | None:
        if attempt_number <= 0:
            return None

        path = self.artifacts.session_dir(str(session_id)) / "attempts" / str(attempt_number) / "evidence" / "raw.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _serialize_session(self, session: ImportSession) -> dict:
        return {
            "id": session.id,
            "file_name": session.file_name,
            "mime_type": session.mime_type,
            "status": session.status,
            "strategy_key": session.strategy_key,
            "provider_hint": session.provider_hint,
            "language_hint": session.language_hint,
            "charset_hint": session.charset_hint,
            "extractor_id": session.extractor_id,
            "raw_artifact_ref": session.raw_artifact_ref,
            "error_stage": session.error_stage,
            "error_message": session.error_message,
            "attempt_count": self._latest_attempt_number(session.id),
            "created_at": session.created_at,
            "updated_at": session.updated_at,
        }

    @staticmethod
    def _serialize_statement(statement: ImportStatementDraft) -> dict:
        return {
            "id": statement.id,
            "attempt_number": statement.attempt_number,
            "statement_period_start": statement.statement_period_start,
            "statement_period_end": statement.statement_period_end,
            "transaction_count": statement.transaction_count,
            "account_number_hint": statement.account_number_hint,
            "card_number_hint": statement.card_number_hint,
            "currency": statement.currency,
            "overall_confidence": statement.overall_confidence,
            "review_status": statement.review_status,
        }

    @staticmethod
    def _serialize_transaction_draft(
        transaction: ImportTransactionDraft,
        *,
        conversion_service: CurrencyConversionService,
        reporting_currency: str,
    ) -> dict:
        if transaction.transaction_date is None:
            display_money = DisplayMoney.unavailable(
                display_currency=reporting_currency,
                reason="missing_transaction_date",
            )
        else:
            display_money = conversion_service.convert(
                raw_amount=transaction.signed_amount,
                raw_currency=transaction.currency,
                reporting_currency=reporting_currency,
                transaction_date=transaction.transaction_date,
            )
        payload = build_import_transaction_draft_response_payload(transaction, display_money)
        payload["field_confidence"] = json.loads(transaction.field_confidence) if transaction.field_confidence else None
        payload["raw_fields"] = json.loads(transaction.raw_fields) if transaction.raw_fields else None
        return payload

    @staticmethod
    def _serialize_issue(issue: ImportIssueModel) -> dict:
        return {
            "id": issue.id,
            "attempt_number": issue.attempt_number,
            "severity": issue.severity,
            "blocking": issue.blocking,
            "issue_code": issue.issue_code,
            "issue_message": issue.issue_message,
            "transaction_ref": issue.transaction_ref,
        }

    def _sync_meta_state(self, session_id: str, state: str) -> None:
        payload = self.artifacts.read_meta(session_id)
        stage_timestamps = dict(payload.get("stage_timestamps", {}))
        stage_timestamps[state] = self._stage_timestamp()
        payload["state"] = state
        payload["stage_timestamps"] = stage_timestamps
        self.artifacts.write_meta(session_id, payload)

    def _commit_session_state(self, session: ImportSession, meta_state: str | None = None) -> ImportSession:
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        self.db.refresh(session)
        if meta_state is not None:
            try:
                self._sync_meta_state(str(session.id), meta_state)
            except Exception:
                logger.warning("Failed to sync meta state for import session %s", session.id, exc_info=True)
        return session

    def _refresh_statistics_in_transaction(self, affected_dates: set[date]) -> None:
        for transaction_date in sorted(affected_dates):
            self._refresh_statistics_for_date(transaction_date)

    @staticmethod
    def _sync_category_suggestion_index(committed_transactions: list[Transaction]) -> None:
        for transaction in committed_transactions:
            if transaction.transaction_type not in {TransactionType.EXPENSE, TransactionType.INCOME}:
                continue
            if not transaction.expense_category and not transaction.income_category:
                continue
            try:
                category_suggestion_service.add_transaction(transaction)
            except Exception:
                logger.warning(
                    "Failed to update suggestion index for transaction %s",
                    transaction.id,
                    exc_info=True,
                )

    def _run_anomaly_detection(self, committed_transactions: list[Transaction]) -> None:
        transaction_ids = [transaction.id for transaction in committed_transactions if transaction.id is not None]
        if not transaction_ids:
            return
        try:
            AnomalyDetectionService.detect_anomalies(
                db=self.db,
                transaction_ids=transaction_ids,
                force_redetection=False,
            )
        except Exception:
            logger.warning("Anomaly detection failed for committed import transactions", exc_info=True)

    def _refresh_statistics_for_date(self, transaction_date: date) -> None:
        monthly_date = transaction_date.replace(day=monthrange(transaction_date.year, transaction_date.month)[1])
        yearly_date = date(transaction_date.year, 12, 31)

        monthly_stats = (
            self.db.query(FinancialStatistics)
            .filter(
                FinancialStatistics.period == StatisticsPeriod.MONTHLY,
                FinancialStatistics.date == monthly_date,
            )
            .with_for_update()
            .first()
        )
        if monthly_stats is None:
            monthly_stats = FinancialStatistics(period=StatisticsPeriod.MONTHLY, date=monthly_date)
            self.db.add(monthly_stats)
            self.db.flush()

        yearly_stats = (
            self.db.query(FinancialStatistics)
            .filter(
                FinancialStatistics.period == StatisticsPeriod.YEARLY,
                FinancialStatistics.date == yearly_date,
            )
            .with_for_update()
            .first()
        )
        if yearly_stats is None:
            yearly_stats = FinancialStatistics(period=StatisticsPeriod.YEARLY, date=yearly_date)
            self.db.add(yearly_stats)
            self.db.flush()

        all_time_stats = (
            self.db.query(FinancialStatistics)
            .filter(FinancialStatistics.period == StatisticsPeriod.ALL_TIME)
            .with_for_update()
            .first()
        )
        if all_time_stats is None:
            all_time_stats = FinancialStatistics(period=StatisticsPeriod.ALL_TIME)
            self.db.add(all_time_stats)
            self.db.flush()

        for stats_obj, stats_data in (
            (monthly_stats, StatisticsService.calculate_statistics(self.db, StatisticsPeriod.MONTHLY, transaction_date)),
            (yearly_stats, StatisticsService.calculate_statistics(self.db, StatisticsPeriod.YEARLY, transaction_date)),
            (all_time_stats, StatisticsService.calculate_statistics(self.db, StatisticsPeriod.ALL_TIME)),
        ):
            for key, value in stats_data.items():
                setattr(stats_obj, key, value)

        self._refresh_category_statistics_for_date(transaction_date)
        self.db.flush()

    def _refresh_category_statistics_for_date(self, transaction_date: date) -> None:
        monthly_date = transaction_date.replace(day=monthrange(transaction_date.year, transaction_date.month)[1])
        yearly_date = date(transaction_date.year, 12, 31)

        self.db.query(CategoryStatistics).filter(
            CategoryStatistics.period == StatisticsPeriod.MONTHLY,
            CategoryStatistics.date == monthly_date,
        ).delete()
        self.db.query(CategoryStatistics).filter(
            CategoryStatistics.period == StatisticsPeriod.YEARLY,
            CategoryStatistics.date == yearly_date,
        ).delete()
        self.db.query(CategoryStatistics).filter(
            CategoryStatistics.period == StatisticsPeriod.ALL_TIME
        ).delete()

        for period, period_date, categories in (
            (
                StatisticsPeriod.MONTHLY,
                monthly_date,
                StatisticsService.calculate_category_statistics(self.db, StatisticsPeriod.MONTHLY, transaction_date),
            ),
            (
                StatisticsPeriod.YEARLY,
                yearly_date,
                StatisticsService.calculate_category_statistics(self.db, StatisticsPeriod.YEARLY, transaction_date),
            ),
            (
                StatisticsPeriod.ALL_TIME,
                None,
                StatisticsService.calculate_category_statistics(self.db, StatisticsPeriod.ALL_TIME),
            ),
        ):
            for category_data in categories:
                if category_data["period_transaction_count"] <= 0:
                    continue
                self.db.add(
                    CategoryStatistics(
                        period=period,
                        date=period_date,
                        **category_data,
                    )
                )

    @staticmethod
    def _normalize_description(value: str) -> str:
        collapsed = re.sub(r"[^0-9a-z]+", " ", value.casefold())
        return " ".join(collapsed.split())

    @staticmethod
    def _statement_account_number(statement: ImportStatementDraft) -> str:
        return statement.account_number_hint or statement.card_number_hint or ""

    def _source_bank_name(self, statement: ImportStatementDraft) -> str:
        session_bank_name = self._session_bank_name(statement.import_session_id)
        if session_bank_name != "Unknown":
            return session_bank_name
        if statement.account_number_hint:
            return "Belfius"
        if statement.card_number_hint:
            return "Beobank"
        return "Unknown"

    def _session_bank_name(self, session_id: int) -> str:
        session = self.db.get(ImportSession, session_id)
        provider_hint = (session.provider_hint if session is not None else None) or ""
        normalized = provider_hint.casefold()
        if normalized == "belfius":
            return "Belfius"
        if normalized == "beobank":
            return "Beobank"
        return provider_hint.title() if provider_hint else "Unknown"

    def _enrich_csv_drafts_before_review(self, session: ImportSession, statement: ImportStatementDraft) -> None:
        if session.strategy_key not in {
            ImportStrategyKey.BELFIUS_CSV.value,
            ImportStrategyKey.BEOBANK_CSV.value,
            ImportStrategyKey.NEXO_CSV.value,
        }:
            return

        source_bank = self._source_bank_name(statement)
        for draft in self._statement_transactions(statement.id):
            enrich_draft_proposals(
                self.db,
                draft=draft,
                source_bank=source_bank,
            )

    def _get_session(self, session_id: int) -> ImportSession:
        session = self.db.get(ImportSession, session_id)
        if session is None:
            raise ImportSessionNotFoundError(f"Import session {session_id} does not exist.")
        return session

    def fail_session(self, session_id: int, *, stage: str, message: str) -> ImportSession:
        session = self._get_session(session_id)
        if session.status == ImportSessionStatus.DETECTED.value:
            assert_transition_allowed(ImportSessionStatus.DETECTED, ImportSessionStatus.FAILED)
            session.status = ImportSessionStatus.FAILED.value
        session.error_stage = stage
        session.error_message = message
        return self._commit_session_state(session, meta_state=session.status)

    @staticmethod
    def _advance_to_awaiting_review(session: ImportSession) -> None:
        current = ImportSessionStatus(session.status)
        for target in (
            ImportSessionStatus.EXTRACTED,
            ImportSessionStatus.NORMALIZED,
            ImportSessionStatus.VALIDATED,
            ImportSessionStatus.AWAITING_REVIEW,
        ):
            assert_transition_allowed(current, target)
            session.status = target.value
            current = target

    @staticmethod
    def _failure_message(result: ExtractionResult) -> str:
        blocking_issues = [issue.message for issue in result.issues if issue.blocking]
        if blocking_issues:
            return "; ".join(blocking_issues)
        return "Extraction failed with non-reviewable output."

    @staticmethod
    def _transaction_confidence(transaction: ExtractedTransaction, result: ExtractionResult) -> float | None:
        if transaction.confidence:
            return sum(transaction.confidence.values()) / len(transaction.confidence)
        return result.overall_confidence

    @staticmethod
    def _parse_iso_date(value: str | None) -> date | None:
        if not value:
            return None
        return date.fromisoformat(value)

    @staticmethod
    def _validated_transaction_type(draft: ImportTransactionDraft) -> TransactionType | None:
        proposed_type = TransactionType(draft.proposed_transaction_type) if draft.proposed_transaction_type else None
        if proposed_type is None:
            if draft.proposed_expense_category or draft.proposed_income_category or draft.proposed_transfer_category:
                raise ImportSessionStateError(
                    "Draft contains category proposals without a proposed_transaction_type."
                )
            return None

        if proposed_type == TransactionType.EXPENSE:
            if draft.proposed_income_category or draft.proposed_transfer_category:
                raise ImportSessionStateError("Expense draft cannot carry income or transfer category proposals.")
            return proposed_type
        if proposed_type == TransactionType.INCOME:
            if draft.proposed_expense_category or draft.proposed_transfer_category:
                raise ImportSessionStateError("Income draft cannot carry expense or transfer category proposals.")
            return proposed_type
        if draft.proposed_expense_category or draft.proposed_income_category:
            raise ImportSessionStateError("Transfer draft cannot carry expense or income category proposals.")
        return proposed_type

    def _extractor_for_strategy(self, strategy_key: str | None):
        strategy_map = {
            ImportStrategyKey.PDF_STATEMENT.value: self.pdf_statement_extractor,
            ImportStrategyKey.BELFIUS_CSV.value: self.belfius_csv_extractor,
            ImportStrategyKey.BEOBANK_CSV.value: self.beobank_csv_extractor,
            ImportStrategyKey.NEXO_CSV.value: self.nexo_csv_extractor,
        }
        return strategy_map.get(strategy_key)

    def _write_workflow_meta(
        self,
        *,
        session_id: str,
        attempt_number: int,
        state: str,
        extraction_succeeded: bool,
    ) -> None:
        payload = self.artifacts.read_meta(session_id)
        stage_timestamps = dict(payload.get("stage_timestamps", {}))
        now = self._stage_timestamp()
        stage_timestamps["extraction_started"] = stage_timestamps.get("extraction_started", now)
        if extraction_succeeded:
            stage_timestamps["extracted"] = now
        if state == ImportSessionStatus.AWAITING_REVIEW.value:
            stage_timestamps["normalized"] = now
            stage_timestamps["validated"] = now
            stage_timestamps["awaiting_review"] = now
        if state == ImportSessionStatus.FAILED.value:
            stage_timestamps["failed"] = now

        payload["state"] = state
        payload["attempt_count"] = attempt_number
        payload["stage_timestamps"] = stage_timestamps
        self.artifacts.write_meta(session_id, payload)

    @staticmethod
    def _stage_timestamp() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
