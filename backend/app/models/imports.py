from datetime import datetime

from sqlalchemy import Boolean, Column, Date, DateTime, Enum, Float, ForeignKey, Integer, String, Text

from ..database import Base
from .transaction import ExpenseCategory, IncomeCategory, TransactionType, TransferCategory


class ImportSession(Base):
    __tablename__ = "import_sessions"

    id = Column(Integer, primary_key=True, index=True)
    file_name = Column(String(255), nullable=False)
    file_hash = Column(String(128), nullable=False, index=True)
    mime_type = Column(String(100), nullable=False)
    status = Column(String(50), nullable=False, index=True)
    strategy_key = Column(String(50), nullable=True)
    provider_hint = Column(String(50), nullable=True)
    language_hint = Column(String(20), nullable=True)
    charset_hint = Column(String(50), nullable=True)
    extractor_id = Column(String(100), nullable=True)
    raw_artifact_ref = Column(String(255), nullable=True)
    error_stage = Column(String(50), nullable=True)
    error_message = Column(Text, nullable=True)
    approved_by = Column(String(100), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class ImportStatementDraft(Base):
    __tablename__ = "import_statement_drafts"

    id = Column(Integer, primary_key=True, index=True)
    import_session_id = Column(Integer, ForeignKey("import_sessions.id"), nullable=False, index=True)
    attempt_number = Column(Integer, nullable=False, default=1)
    statement_period_start = Column(Date, nullable=True)
    statement_period_end = Column(Date, nullable=True)
    summary_text = Column(Text, nullable=True)
    opening_balance = Column(Float, nullable=True)
    closing_balance = Column(Float, nullable=True)
    available_balance = Column(Float, nullable=True)
    total_debit = Column(Float, nullable=True)
    total_credit = Column(Float, nullable=True)
    transaction_count = Column(Integer, nullable=True)
    account_number_hint = Column(String(100), nullable=True)
    card_number_hint = Column(String(100), nullable=True)
    currency = Column(String(10), nullable=True)
    overall_confidence = Column(Float, nullable=False, default=0.0)
    review_status = Column(String(50), nullable=False, default="draft")


class ImportTransactionDraft(Base):
    __tablename__ = "import_transaction_drafts"

    id = Column(Integer, primary_key=True, index=True)
    import_statement_draft_id = Column(
        Integer,
        ForeignKey("import_statement_drafts.id"),
        nullable=False,
        index=True,
    )
    transaction_date = Column(Date, nullable=True)
    source_description = Column(Text, nullable=False)
    canonical_description_en = Column(Text, nullable=True)
    signed_amount = Column(Float, nullable=False)
    currency = Column(String(10), nullable=False)
    debit_credit = Column(String(10), nullable=True)
    source_locator = Column(String(255), nullable=False)
    inferred_category = Column(String(100), nullable=True)
    category_source = Column(String(50), nullable=True)
    proposed_transaction_type = Column(Enum(TransactionType), nullable=True)
    proposed_expense_category = Column(Enum(ExpenseCategory), nullable=True)
    proposed_income_category = Column(Enum(IncomeCategory), nullable=True)
    proposed_transfer_category = Column(Enum(TransferCategory), nullable=True)
    proposal_source = Column(String(50), nullable=True)
    confidence = Column(Float, nullable=True)
    field_confidence = Column(Text, nullable=True)
    raw_fields = Column(Text, nullable=True)
    edit_source = Column(String(50), nullable=False, default="ai_extracted")


class ImportIssue(Base):
    __tablename__ = "import_issues"

    id = Column(Integer, primary_key=True, index=True)
    import_session_id = Column(Integer, ForeignKey("import_sessions.id"), nullable=False, index=True)
    attempt_number = Column(Integer, nullable=False, default=1)
    severity = Column(String(20), nullable=False)
    blocking = Column(Boolean, nullable=False, default=True)
    issue_code = Column(String(100), nullable=False)
    issue_message = Column(Text, nullable=False)
    transaction_ref = Column(String(255), nullable=True)


class ImportBatchRun(Base):
    __tablename__ = "import_batch_runs"

    id = Column(Integer, primary_key=True, index=True)
    folder_path = Column(String(255), nullable=False)
    status = Column(String(50), nullable=False, index=True)
    message = Column(Text, nullable=True)
    total_files = Column(Integer, nullable=False, default=0)
    processed_count = Column(Integer, nullable=False, default=0)
    skipped_existing_count = Column(Integer, nullable=False, default=0)
    unsupported_count = Column(Integer, nullable=False, default=0)
    failed_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class ImportBatchItem(Base):
    __tablename__ = "import_batch_items"

    id = Column(Integer, primary_key=True, index=True)
    batch_run_id = Column(Integer, ForeignKey("import_batch_runs.id"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    file_hash = Column(String(128), nullable=True)
    status = Column(String(50), nullable=False, index=True)
    message = Column(Text, nullable=True)
    session_id = Column(Integer, ForeignKey("import_sessions.id"), nullable=True, index=True)
    session_status = Column(String(50), nullable=True)
    existing_session_id = Column(Integer, ForeignKey("import_sessions.id"), nullable=True, index=True)
    existing_session_status = Column(String(50), nullable=True)
    strategy_key = Column(String(50), nullable=True)
    extractor_id = Column(String(100), nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
