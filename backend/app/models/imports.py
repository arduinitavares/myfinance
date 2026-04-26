"""Module for backend app models imports."""

from datetime import UTC, date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


def utc_now() -> datetime:
    """Return the current UTC datetime."""
    return datetime.now(UTC)


class ImportSession(Base):
    """Represent import session."""

    __tablename__ = "import_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    strategy_key: Mapped[str | None] = mapped_column(String(50), nullable=True)
    provider_hint: Mapped[str | None] = mapped_column(String(50), nullable=True)
    language_hint: Mapped[str | None] = mapped_column(String(20), nullable=True)
    charset_hint: Mapped[str | None] = mapped_column(String(50), nullable=True)
    extractor_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    raw_artifact_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_stage: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now, onupdate=utc_now
    )


class ImportStatementDraft(Base):
    """Represent import statement draft."""

    __tablename__ = "import_statement_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    import_session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("import_sessions.id"), nullable=False, index=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    statement_period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    statement_period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    opening_balance: Mapped[float | None] = mapped_column(Float, nullable=True)
    closing_balance: Mapped[float | None] = mapped_column(Float, nullable=True)
    available_balance: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_debit: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_credit: Mapped[float | None] = mapped_column(Float, nullable=True)
    transaction_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    account_number_hint: Mapped[str | None] = mapped_column(String(100), nullable=True)
    card_number_hint: Mapped[str | None] = mapped_column(String(100), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    overall_confidence: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    review_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="draft"
    )


class ImportTransactionDraft(Base):
    """Represent import transaction draft."""

    __tablename__ = "import_transaction_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    import_statement_draft_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("import_statement_drafts.id"),
        nullable=False,
        index=True,
    )
    transaction_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_description: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_description_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    signed_amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    debit_credit: Mapped[str | None] = mapped_column(String(10), nullable=True)
    source_locator: Mapped[str] = mapped_column(String(255), nullable=False)
    inferred_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    category_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    proposed_transaction_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    proposed_expense_category: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    proposed_income_category: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    proposed_transfer_category: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    classification_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    recurrence_pattern_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    field_confidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_fields: Mapped[str | None] = mapped_column(Text, nullable=True)
    edit_source: Mapped[str] = mapped_column(
        String(50), nullable=False, default="ai_extracted"
    )


class ImportIssue(Base):
    """Represent import issue."""

    __tablename__ = "import_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    import_session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("import_sessions.id"), nullable=False, index=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    blocking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    issue_code: Mapped[str] = mapped_column(String(100), nullable=False)
    issue_message: Mapped[str] = mapped_column(Text, nullable=False)
    transaction_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)


class ImportBatchRun(Base):
    """Represent import batch run."""

    __tablename__ = "import_batch_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    folder_path: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_existing_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    unsupported_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ImportBatchItem(Base):
    """Represent import batch item."""

    __tablename__ = "import_batch_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    batch_run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("import_batch_runs.id"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("import_sessions.id"), nullable=True, index=True
    )
    session_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    existing_session_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("import_sessions.id"), nullable=True, index=True
    )
    existing_session_status: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    strategy_key: Mapped[str | None] = mapped_column(String(50), nullable=True)
    extractor_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
