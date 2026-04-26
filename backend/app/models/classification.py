"""Module for backend app models classification."""

import enum
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from .transaction import TransactionType

if TYPE_CHECKING:
    from .transaction import Transaction


def _enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    return [member.value for member in enum_cls]


def utc_now() -> datetime:
    """Return the current UTC datetime."""
    return datetime.now(UTC)


class ClassificationSessionStatus(enum.Enum):
    """Represent classification session status."""

    OPEN = "open"
    ACCEPTED = "accepted"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class ClassificationSession(Base):
    """Represent classification session."""

    __tablename__ = "classification_sessions"
    __table_args__ = (
        Index(
            "uq_open_classification_session_per_transaction",
            "transaction_id",
            unique=True,
            sqlite_where=text("status = 'open'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    transaction_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("transactions.id"), nullable=False, index=True
    )
    status: Mapped[ClassificationSessionStatus] = mapped_column(
        Enum(
            ClassificationSessionStatus,
            native_enum=False,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=ClassificationSessionStatus.OPEN,
        index=True,
    )
    provider_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    final_transaction_type: Mapped[TransactionType | None] = mapped_column(
        Enum(TransactionType), nullable=True
    )
    final_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    final_recurrence_frequency: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now, onupdate=utc_now
    )

    transaction: Mapped["Transaction"] = relationship(
        "Transaction", back_populates="classification_sessions"
    )
    turns: Mapped[list["ClassificationTurn"]] = relationship(
        "ClassificationTurn",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ClassificationTurn.turn_index",
    )
    recurrence_patterns: Mapped[list["RecurrencePattern"]] = relationship(
        "RecurrencePattern",
        back_populates="source_session",
        foreign_keys="RecurrencePattern.source_session_id",
    )


class ClassificationTurn(Base):
    """Represent classification turn."""

    __tablename__ = "classification_turns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("classification_sessions.id"), nullable=False, index=True
    )
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    proposal_transaction_type: Mapped[str] = mapped_column(String(50), nullable=False)
    proposal_category: Mapped[str] = mapped_column(String(100), nullable=False)
    proposal_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    proposal_recurrence_frequency: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    proposal_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    follow_up_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback_tag: Mapped[str | None] = mapped_column(String(100), nullable=True)
    feedback_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now
    )

    session: Mapped["ClassificationSession"] = relationship(
        "ClassificationSession", back_populates="turns"
    )


class RecurrencePattern(Base):
    """Represent recurrence pattern."""

    __tablename__ = "recurrence_patterns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    source_session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("classification_sessions.id"), nullable=False, index=True
    )
    seed_transaction_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("transactions.id"), nullable=False, index=True
    )
    normalized_description_key: Mapped[str] = mapped_column(
        String(500), nullable=False, index=True
    )
    source_bank: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    transaction_type: Mapped[TransactionType] = mapped_column(
        Enum(TransactionType), nullable=False
    )
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    frequency: Mapped[str] = mapped_column(String(50), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now
    )

    source_session: Mapped["ClassificationSession"] = relationship(
        "ClassificationSession",
        back_populates="recurrence_patterns",
        foreign_keys=[source_session_id],
    )
    seed_transaction: Mapped["Transaction"] = relationship(
        "Transaction",
        back_populates="seeded_recurrence_patterns",
        foreign_keys=[seed_transaction_id],
    )
