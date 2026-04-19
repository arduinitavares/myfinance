from datetime import datetime, timedelta
import logging
import os

from fastapi import HTTPException
from openai import APIConnectionError, APIError, APITimeoutError, RateLimitError
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..imports.providers import ProviderRegistry
from ..models.classification import (
    ClassificationSession,
    ClassificationSessionStatus,
    ClassificationTurn,
    RecurrencePattern,
)
from ..models.transaction import ExpenseCategory, IncomeCategory, Transaction, TransactionType, TransferCategory
from ..schemas.classification import (
    ApplyBatchRequest,
    ApplyBatchResponse,
    AcceptClassificationRequest,
    AcceptClassificationResponse,
    ClassificationSessionResponse,
    ClassificationProposalResponse,
    SimilarPreviewResponse,
    SimilarTransactionMatchResponse,
    SubmitFeedbackRequest,
)
from ..schemas.transaction import (
    Transaction as TransactionSchema,
    build_transaction_response_payload_for_reporting_currency,
)
from ..routers.suggestions import category_suggestion_service
from ..services.classifier_providers import OpenAICompatibleClassifierProvider, StubClassifierProvider
from ..services.currency_conversion import CurrencyConversionService
from .classification_similarity import (
    SIMILARITY_PREVIEW_LIMIT,
    SIMILARITY_THRESHOLD,
    has_conflicting_family,
    shares_source_bank,
)
from ..utils.text_normalization import normalize_for_matching
from .classification_commit_service import commit_category_change, normalized_category_for


logger = logging.getLogger(__name__)

SESSION_TTL = timedelta(hours=24)
REMOTE_PROVIDER_ERRORS = (RuntimeError, APIError, APIConnectionError, APITimeoutError, RateLimitError)


def _same_sign(left: Transaction, right: Transaction) -> bool:
    return (left.amount < 0) == (right.amount < 0)


def _compatible_candidate_family(seed: Transaction, candidate: Transaction) -> bool:
    if seed.transaction_type == TransactionType.TRANSFER:
        return candidate.transaction_type in {
            TransactionType.EXPENSE,
            TransactionType.INCOME,
            TransactionType.TRANSFER,
        }
    return candidate.transaction_type == seed.transaction_type


def recurrence_pattern_matches_transaction(pattern: RecurrencePattern, transaction: Transaction) -> bool:
    if pattern.normalized_description_key != normalize_for_matching(transaction.description):
        return False
    if pattern.currency != transaction.currency:
        return False
    if not _same_sign(pattern.seed_transaction, transaction):
        return False

    if pattern.transaction_type == TransactionType.TRANSFER:
        return True
    return transaction.transaction_type == pattern.transaction_type


class ClassificationSessionService:
    @classmethod
    def create_or_resume_session(cls, db: Session, transaction_id: int) -> ClassificationSession:
        cls._expire_old_open_sessions(db)
        transaction = cls._require_transaction(db, transaction_id)
        existing = (
            db.query(ClassificationSession)
            .filter(
                ClassificationSession.transaction_id == transaction.id,
                ClassificationSession.status == ClassificationSessionStatus.OPEN,
            )
            .first()
        )
        if existing:
            if cls._provider_is_available_in_current_config(existing.provider_name):
                return existing

            logger.info(
                "Classification session %s uses unavailable provider %s; cancelling and recreating",
                existing.id,
                existing.provider_name,
            )
            existing.status = ClassificationSessionStatus.CANCELLED
            existing.updated_at = datetime.utcnow()
            db.add(existing)
            db.flush()

        provider = cls._build_provider()
        session = ClassificationSession(
            transaction_id=transaction.id,
            status=ClassificationSessionStatus.OPEN,
            provider_name=provider.name,
            model_name=provider.model_name,
        )
        db.add(session)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            existing = (
                db.query(ClassificationSession)
                .filter(
                    ClassificationSession.transaction_id == transaction.id,
                    ClassificationSession.status == ClassificationSessionStatus.OPEN,
                )
                .first()
            )
            if existing:
                return existing
            raise
        db.refresh(session)
        return session

    @classmethod
    def propose(cls, db: Session, session_id: int) -> ClassificationProposalResponse:
        session = cls._require_open_session(db, session_id)
        transaction = cls._require_transaction(db, session.transaction_id)
        proposal = cls._generate_proposal(
            db=db,
            session=session,
            transaction=transaction,
            feedback_tag=None,
            feedback_note=None,
        )
        turn = ClassificationTurn(
            session_id=session.id,
            turn_index=cls._next_turn_index(db, session.id),
            proposal_transaction_type=proposal.transaction_type,
            proposal_category=proposal.category,
            proposal_confidence=proposal.confidence,
            proposal_recurrence_frequency=proposal.recurrence_frequency,
            proposal_rationale=proposal.rationale,
            follow_up_question=proposal.follow_up_question,
            prompt_tokens=proposal.prompt_tokens,
            completion_tokens=proposal.completion_tokens,
        )
        session.updated_at = datetime.utcnow()
        db.add(turn)
        db.commit()
        db.refresh(turn)
        return cls._proposal_response(turn)

    @classmethod
    def record_feedback(
        cls,
        db: Session,
        session_id: int,
        request: SubmitFeedbackRequest,
    ) -> ClassificationProposalResponse:
        session = cls._require_open_session(db, session_id)
        transaction = cls._require_transaction(db, session.transaction_id)
        proposal = cls._generate_proposal(
            db=db,
            session=session,
            transaction=transaction,
            feedback_tag=request.feedback_tag,
            feedback_note=request.feedback_note,
        )
        turn = ClassificationTurn(
            session_id=session.id,
            turn_index=cls._next_turn_index(db, session.id),
            proposal_transaction_type=proposal.transaction_type,
            proposal_category=proposal.category,
            proposal_confidence=proposal.confidence,
            proposal_recurrence_frequency=proposal.recurrence_frequency,
            proposal_rationale=proposal.rationale,
            follow_up_question=proposal.follow_up_question,
            feedback_tag=request.feedback_tag,
            feedback_note=request.feedback_note,
            prompt_tokens=proposal.prompt_tokens,
            completion_tokens=proposal.completion_tokens,
        )
        session.updated_at = datetime.utcnow()
        db.add(turn)
        db.commit()
        db.refresh(turn)
        return cls._proposal_response(turn)

    @classmethod
    def accept(
        cls,
        db: Session,
        session_id: int,
        request: AcceptClassificationRequest,
        *,
        reporting_currency: str,
    ) -> AcceptClassificationResponse:
        session = cls._require_open_session(db, session_id)
        transaction = cls._require_transaction(db, session.transaction_id)

        if request.transaction_type != transaction.transaction_type and not request.confirm_type_change:
            raise HTTPException(status_code=400, detail="Type change requires confirmation")

        normalized_category = normalized_category_for(
            transaction_type=request.transaction_type,
            category=request.category,
            amount=transaction.amount,
        )
        recurrence_pattern = None
        recurrence_frequency = None
        if request.recurrence.is_recurrent:
            recurrence_frequency = request.recurrence.frequency or cls._latest_recurrence_frequency(session)
            if recurrence_frequency is None:
                recurrence_frequency = "monthly"
            recurrence_pattern = RecurrencePattern(
                source_session_id=session.id,
                seed_transaction_id=transaction.id,
                normalized_description_key=normalize_for_matching(transaction.description),
                source_bank=transaction.source_bank,
                currency=transaction.currency,
                transaction_type=request.transaction_type,
                category=normalized_category,
                frequency=recurrence_frequency,
                active=True,
            )
            db.add(recurrence_pattern)
            db.flush()

        session.status = ClassificationSessionStatus.ACCEPTED
        session.final_transaction_type = request.transaction_type
        session.final_category = normalized_category
        session.final_recurrence_frequency = recurrence_frequency
        session.updated_at = datetime.utcnow()

        try:
            updated_transaction = commit_category_change(
                db=db,
                transaction=transaction,
                transaction_type=request.transaction_type,
                category=normalized_category,
                classification_source=request.classification_source,
                recurrence_pattern_id=recurrence_pattern.id if recurrence_pattern else None,
            )
        except ValueError as exc:
            db.rollback()
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        db.refresh(session)
        conversion_service = CurrencyConversionService(db)
        transaction_payload = build_transaction_response_payload_for_reporting_currency(
            updated_transaction,
            conversion_service=conversion_service,
            reporting_currency=reporting_currency,
        )
        return AcceptClassificationResponse(
            session=ClassificationSessionResponse.model_validate(session, from_attributes=True),
            transaction=TransactionSchema.model_validate(transaction_payload),
            recurrence_pattern_id=recurrence_pattern.id if recurrence_pattern else None,
        )

    @classmethod
    def preview_similar(cls, db: Session, session_id: int) -> SimilarPreviewResponse:
        session = cls._require_accepted_session(db, session_id)
        seed_transaction = cls._require_transaction(db, session.transaction_id)
        candidates = cls._similar_candidates(db, seed_transaction)
        matches = [
            SimilarTransactionMatchResponse(
                transaction_id=transaction.id,
                description=transaction.description,
                amount=transaction.amount,
                currency=transaction.currency,
                score=score,
            )
            for transaction, score in candidates
        ]
        return SimilarPreviewResponse(
            session=ClassificationSessionResponse.model_validate(session, from_attributes=True),
            seed_transaction_id=seed_transaction.id,
            matches=matches,
        )

    @classmethod
    def apply_batch(cls, db: Session, session_id: int, request: ApplyBatchRequest) -> ApplyBatchResponse:
        session = cls._require_accepted_session(db, session_id)
        seed_transaction = cls._require_transaction(db, session.transaction_id)

        if session.final_transaction_type is None or session.final_category is None:
            raise HTTPException(status_code=409, detail="Session has no accepted classification")

        allowed_transaction_ids = {
            transaction.id for transaction, _ in cls._similar_candidates(db, seed_transaction)
        }
        requested_ids = list(dict.fromkeys(request.transaction_ids))
        candidates = {
            candidate.id: candidate
            for candidate in db.query(Transaction).filter(Transaction.id.in_(requested_ids)).all()
        }
        applied_transaction_ids: list[int] = []
        skipped_transaction_ids: list[int] = []

        for transaction_id in requested_ids:
            candidate = candidates.get(transaction_id)
            if candidate is None:
                skipped_transaction_ids.append(transaction_id)
                continue
            if transaction_id not in allowed_transaction_ids:
                skipped_transaction_ids.append(transaction_id)
                continue
            if (
                candidate.expense_category is not None
                or candidate.income_category is not None
                or candidate.transfer_category is not None
            ):
                skipped_transaction_ids.append(transaction_id)
                continue

            try:
                updated_transaction = commit_category_change(
                    db=db,
                    transaction=candidate,
                    transaction_type=session.final_transaction_type,
                    category=session.final_category,
                    classification_source="assistant_batch",
                    recurrence_pattern_id=None,
                )
            except ValueError as exc:
                db.rollback()
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            applied_transaction_ids.append(updated_transaction.id)

        return ApplyBatchResponse(
            session=ClassificationSessionResponse.model_validate(session, from_attributes=True),
            applied_transaction_ids=applied_transaction_ids,
            skipped_transaction_ids=skipped_transaction_ids,
        )

    @staticmethod
    def _require_transaction(db: Session, transaction_id: int) -> Transaction:
        transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
        if transaction is None:
            raise HTTPException(status_code=404, detail="Transaction not found")
        return transaction

    @classmethod
    def _require_open_session(cls, db: Session, session_id: int) -> ClassificationSession:
        cls._expire_old_open_sessions(db)
        session = db.query(ClassificationSession).filter(ClassificationSession.id == session_id).first()
        if session is None:
            raise HTTPException(status_code=404, detail="Classification session not found")
        if session.status != ClassificationSessionStatus.OPEN:
            if session.status == ClassificationSessionStatus.EXPIRED:
                raise HTTPException(status_code=409, detail="Session expired")
            raise HTTPException(status_code=409, detail="Session is not open")
        return session

    @classmethod
    def _require_accepted_session(cls, db: Session, session_id: int) -> ClassificationSession:
        session = db.query(ClassificationSession).filter(ClassificationSession.id == session_id).first()
        if session is None:
            raise HTTPException(status_code=404, detail="Classification session not found")
        if session.status == ClassificationSessionStatus.EXPIRED:
            raise HTTPException(status_code=409, detail="Session expired")
        if session.status != ClassificationSessionStatus.ACCEPTED:
            raise HTTPException(status_code=409, detail="Session is not accepted")
        return session

    @staticmethod
    def _next_turn_index(db: Session, session_id: int) -> int:
        current_max = (
            db.query(func.max(ClassificationTurn.turn_index))
            .filter(ClassificationTurn.session_id == session_id)
            .scalar()
        )
        if current_max is None:
            return 0
        return int(current_max) + 1

    @classmethod
    def _expire_old_open_sessions(cls, db: Session) -> None:
        cutoff = datetime.utcnow() - SESSION_TTL
        stale_sessions = (
            db.query(ClassificationSession)
            .filter(
                ClassificationSession.status == ClassificationSessionStatus.OPEN,
                ClassificationSession.updated_at < cutoff,
            )
            .all()
        )
        changed = False
        for session in stale_sessions:
            session.status = ClassificationSessionStatus.EXPIRED
            session.updated_at = datetime.utcnow()
            changed = True
        if changed:
            db.commit()

    @staticmethod
    def _allowed_options_by_type(transaction_type: TransactionType) -> dict[str, list[str]]:
        transfer_categories = [category.value for category in TransferCategory]
        if transaction_type == TransactionType.EXPENSE:
            return {
                TransactionType.EXPENSE.value: [category.value for category in ExpenseCategory],
                TransactionType.TRANSFER.value: transfer_categories,
            }
        if transaction_type == TransactionType.INCOME:
            return {
                TransactionType.INCOME.value: [category.value for category in IncomeCategory],
                TransactionType.TRANSFER.value: transfer_categories,
            }
        return {TransactionType.TRANSFER.value: transfer_categories}

    @staticmethod
    def _proposal_response(turn: ClassificationTurn) -> ClassificationProposalResponse:
        return ClassificationProposalResponse(
            id=turn.id,
            session_id=turn.session_id,
            turn_index=turn.turn_index,
            transaction_type=turn.proposal_transaction_type,
            category=turn.proposal_category,
            confidence=turn.proposal_confidence,
            recurrence_frequency=turn.proposal_recurrence_frequency,
            rationale=turn.proposal_rationale,
            follow_up_question=turn.follow_up_question,
            feedback_tag=turn.feedback_tag,
            feedback_note=turn.feedback_note,
            prompt_tokens=turn.prompt_tokens,
            completion_tokens=turn.completion_tokens,
            created_at=turn.created_at,
        )

    @staticmethod
    def _latest_recurrence_frequency(session: ClassificationSession) -> str | None:
        if not session.turns:
            return None
        latest_turn = session.turns[-1]
        return latest_turn.proposal_recurrence_frequency

    @classmethod
    def _conversation_history(cls, db: Session, session_id: int) -> list[ClassificationTurn]:
        return (
            db.query(ClassificationTurn)
            .filter(ClassificationTurn.session_id == session_id)
            .order_by(ClassificationTurn.turn_index)
            .all()
        )

    @classmethod
    def _fallback_suggestions(cls, transaction: Transaction) -> list[dict[str, float | str]]:
        if transaction.transaction_type not in {TransactionType.EXPENSE, TransactionType.INCOME}:
            return []
        suggestions = category_suggestion_service.suggest_category(
            description=transaction.description,
            amount=transaction.amount,
            transaction_type=transaction.transaction_type,
        )
        return [
            {"category": category, "confidence": float(confidence)}
            for category, confidence in suggestions
        ]

    @classmethod
    def _generate_proposal(
        cls,
        *,
        db: Session,
        session: ClassificationSession,
        transaction: Transaction,
        feedback_tag: str | None,
        feedback_note: str | None,
    ):
        allowed_options_by_type = cls._allowed_options_by_type(transaction.transaction_type)
        conversation_history = cls._conversation_history(db, session.id)
        providers_to_try = [(session.provider_name, session.model_name)] + [
            (provider_name, None)
            for provider_name in cls._fallback_provider_names(session.provider_name)
        ]
        last_error = None

        for provider_name, model_name in providers_to_try:
            try:
                provider = cls._build_provider(provider_name, model_name)
            except HTTPException as exc:
                if exc.status_code == 503:
                    last_error = exc
                    logger.info(
                        "Skipping unavailable configured classification provider %s",
                        provider_name,
                    )
                    continue
                raise
            try:
                proposal = provider.propose(
                    transaction=transaction,
                    allowed_options_by_type=allowed_options_by_type,
                    conversation_history=conversation_history,
                    feedback_tag=feedback_tag,
                    feedback_note=feedback_note,
                )
                if session.provider_name != provider.name or session.model_name != provider.model_name:
                    logger.info(
                        "Classification session switching provider from %s to %s",
                        session.provider_name,
                        provider.name,
                    )
                    session.provider_name = provider.name
                    session.model_name = provider.model_name
                return proposal
            except REMOTE_PROVIDER_ERRORS as exc:
                last_error = exc
                logger.warning(
                    "Classification provider %s unavailable, trying next fallback if configured",
                    provider_name,
                    exc_info=exc,
                )

        logger.warning(
            "Classification provider unavailable; returning degraded suggestions",
            exc_info=last_error,
        )
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Classification provider unavailable",
                "suggestions": cls._fallback_suggestions(transaction),
            },
        ) from last_error

    @classmethod
    def _similar_candidates(cls, db: Session, seed_transaction: Transaction) -> list[tuple[Transaction, float]]:
        if seed_transaction.amount == 0:
            return []

        query = (
            db.query(Transaction)
            .filter(
                Transaction.id != seed_transaction.id,
                Transaction.currency == seed_transaction.currency,
                Transaction.expense_category.is_(None),
                Transaction.income_category.is_(None),
                Transaction.transfer_category.is_(None),
            )
        )
        if seed_transaction.amount < 0:
            query = query.filter(Transaction.amount < 0)
        else:
            query = query.filter(Transaction.amount > 0)

        surviving: list[Transaction] = []
        for transaction in query.all():
            if not _compatible_candidate_family(seed_transaction, transaction):
                continue
            if not shares_source_bank(seed_transaction, transaction):
                continue
            if has_conflicting_family(seed_transaction, transaction):
                continue
            surviving.append(transaction)

        if not surviving:
            return []

        scores = category_suggestion_service.similarity_scores(
            seed_transaction.description.lower(),
            [transaction.description.lower() for transaction in surviving],
        )

        candidates = [
            (transaction, score)
            for transaction, score in zip(surviving, scores)
            if score >= SIMILARITY_THRESHOLD
        ]
        candidates.sort(key=lambda item: (-item[1], item[0].id))
        return candidates[:SIMILARITY_PREVIEW_LIMIT]

    @classmethod
    def _build_provider(cls, provider_name: str | None = None, model_name: str | None = None):
        resolved_provider_name, resolved_model_name = cls._resolve_provider_selection(
            provider_name=provider_name,
            model_name=model_name,
        )
        registry = ProviderRegistry.from_path(settings.provider_config_path)
        provider_config = registry.family("classification_assistant").providers.get(resolved_provider_name)

        if resolved_provider_name == "stub":
            return StubClassifierProvider(name=resolved_provider_name, model_name=resolved_model_name)
        if provider_config and provider_config.kind in {"openai", "openai_compatible"}:
            if not provider_config.api_key_env:
                raise HTTPException(status_code=503, detail="No classification assistant provider configured")
            api_key = os.environ.get(provider_config.api_key_env)
            if not api_key:
                raise HTTPException(status_code=503, detail="No classification assistant provider configured")
            return OpenAICompatibleClassifierProvider(
                name=resolved_provider_name,
                model_name=resolved_model_name,
                api_key=api_key,
                base_url=provider_config.base_url or "https://api.openai.com/v1",
            )
        raise HTTPException(status_code=503, detail="Unsupported classification provider configured")

    @classmethod
    def _fallback_provider_names(cls, provider_name: str | None) -> list[str]:
        registry = ProviderRegistry.from_path(settings.provider_config_path)
        report = registry.validate().get("classification_assistant", {})
        family = registry.family("classification_assistant")
        fallback_names: list[str] = []
        passed_current = provider_name is None or provider_name not in family.order

        for candidate_name in family.order:
            if not passed_current:
                if candidate_name == provider_name:
                    passed_current = True
                continue
            if candidate_name == provider_name:
                continue
            provider_report = report.get(candidate_name, {})
            if provider_report.get("available"):
                fallback_names.append(candidate_name)

        return fallback_names

    @classmethod
    def _provider_is_available_in_current_config(cls, provider_name: str) -> bool:
        registry = ProviderRegistry.from_path(settings.provider_config_path)
        report = registry.validate().get("classification_assistant", {})
        provider_report = report.get(provider_name, {})
        return bool(provider_report.get("available"))

    @classmethod
    def _resolve_provider_selection(
        cls,
        provider_name: str | None = None,
        model_name: str | None = None,
    ) -> tuple[str, str]:
        registry = ProviderRegistry.from_path(settings.provider_config_path)
        report = registry.validate().get("classification_assistant", {})

        if provider_name:
            provider_report = report.get(provider_name)
            provider_config = registry.family("classification_assistant").providers.get(provider_name)
            if provider_report and provider_report.get("available") and provider_config:
                return provider_name, model_name or provider_config.model or provider_name
            raise HTTPException(status_code=503, detail="No classification assistant provider configured")

        family_report = report.get("__family__", {})
        if family_report.get("chain_available"):
            selected_provider_name = family_report["selected_provider"]
            provider_config = registry.family("classification_assistant").providers[selected_provider_name]
            return selected_provider_name, provider_config.model or selected_provider_name

        raise HTTPException(status_code=503, detail="No classification assistant provider configured")
