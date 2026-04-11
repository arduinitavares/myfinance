from datetime import datetime
import enum

from sqlalchemy import Boolean, Column, DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import relationship

from ..database import Base
from .transaction import TransactionType


def _enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    return [member.value for member in enum_cls]


class ClassificationSessionStatus(enum.Enum):
    OPEN = "open"
    ACCEPTED = "accepted"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class ClassificationSession(Base):
    __tablename__ = "classification_sessions"
    __table_args__ = (
        Index(
            "uq_open_classification_session_per_transaction",
            "transaction_id",
            unique=True,
            sqlite_where=text("status = 'open'"),
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=False, index=True)
    status = Column(
        Enum(
            ClassificationSessionStatus,
            native_enum=False,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=ClassificationSessionStatus.OPEN,
        index=True,
    )
    provider_name = Column(String(100), nullable=False)
    model_name = Column(String(200), nullable=False)
    final_transaction_type = Column(Enum(TransactionType), nullable=True)
    final_category = Column(String(100), nullable=True)
    final_recurrence_frequency = Column(String(50), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    transaction = relationship("Transaction", back_populates="classification_sessions")
    turns = relationship(
        "ClassificationTurn",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ClassificationTurn.turn_index",
    )
    recurrence_patterns = relationship(
        "RecurrencePattern",
        back_populates="source_session",
        foreign_keys="RecurrencePattern.source_session_id",
    )


class ClassificationTurn(Base):
    __tablename__ = "classification_turns"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("classification_sessions.id"), nullable=False, index=True)
    turn_index = Column(Integer, nullable=False)
    proposal_transaction_type = Column(String(50), nullable=False)
    proposal_category = Column(String(100), nullable=False)
    proposal_confidence = Column(Float, nullable=False)
    proposal_recurrence_frequency = Column(String(50), nullable=True)
    proposal_rationale = Column(Text, nullable=True)
    follow_up_question = Column(Text, nullable=True)
    feedback_tag = Column(String(100), nullable=True)
    feedback_note = Column(Text, nullable=True)
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    session = relationship("ClassificationSession", back_populates="turns")


class RecurrencePattern(Base):
    __tablename__ = "recurrence_patterns"

    id = Column(Integer, primary_key=True, index=True)
    source_session_id = Column(Integer, ForeignKey("classification_sessions.id"), nullable=False, index=True)
    seed_transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=False, index=True)
    normalized_description_key = Column(String(500), nullable=False, index=True)
    source_bank = Column(String(10), nullable=False, index=True)
    currency = Column(String(3), nullable=False)
    transaction_type = Column(Enum(TransactionType), nullable=False)
    category = Column(String(100), nullable=False)
    frequency = Column(String(50), nullable=False)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    source_session = relationship(
        "ClassificationSession",
        back_populates="recurrence_patterns",
        foreign_keys=[source_session_id],
    )
    seed_transaction = relationship(
        "Transaction",
        back_populates="seeded_recurrence_patterns",
        foreign_keys=[seed_transaction_id],
    )
