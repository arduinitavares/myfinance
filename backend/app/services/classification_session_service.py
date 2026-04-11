from datetime import datetime, timedelta
import logging

from fastapi import HTTPException
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
from ..models.transaction import ExpenseCategory, IncomeCategory, Transaction, TransactionType
from ..schemas.classification import (
    AcceptClassificationRequest,
    AcceptClassificationResponse,
    ClassificationSessionResponse,
    ClassificationProposalResponse,
    SubmitFeedbackRequest,
)
from ..schemas.transaction import Transaction as TransactionSchema
from ..services.classifier_providers import StubClassifierProvider
from ..utils.text_normalization import normalize_for_matching
from .classification_commit_service import commit_category_change, normalized_category_for


logger = logging.getLogger(__name__)

SESSION_TTL = timedelta(hours=24)


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
            return existing

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
        provider = cls._build_provider(session.provider_name, session.model_name)
        proposal = provider.propose(
            transaction=transaction,
            allowed_categories=cls._allowed_categories(transaction.transaction_type),
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
        provider = cls._build_provider(session.provider_name, session.model_name)
        proposal = provider.propose(
            transaction=transaction,
            allowed_categories=cls._allowed_categories(transaction.transaction_type),
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
        return AcceptClassificationResponse(
            session=ClassificationSessionResponse.model_validate(session, from_attributes=True),
            transaction=TransactionSchema.model_validate(updated_transaction, from_attributes=True),
            recurrence_pattern_id=recurrence_pattern.id if recurrence_pattern else None,
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
    def _allowed_categories(transaction_type: TransactionType) -> list[str]:
        if transaction_type == TransactionType.EXPENSE:
            return [category.value for category in ExpenseCategory]
        if transaction_type == TransactionType.INCOME:
            return [category.value for category in IncomeCategory]
        return [ExpenseCategory.INTERNAL_TRANSFER.value]

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
    def _build_provider(cls, provider_name: str | None = None, model_name: str | None = None):
        resolved_provider_name, resolved_model_name = cls._resolve_provider_selection(
            provider_name=provider_name,
            model_name=model_name,
        )
        if resolved_provider_name == "stub":
            return StubClassifierProvider(name=resolved_provider_name, model_name=resolved_model_name)
        raise HTTPException(status_code=503, detail="Unsupported classification provider configured")

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
