from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String, Text

from ..database import Base


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


class ImportStatementDraft(Base):
    __tablename__ = "import_statement_drafts"

    id = Column(Integer, primary_key=True, index=True)
    import_session_id = Column(Integer, ForeignKey("import_sessions.id"), nullable=False, index=True)
    attempt_number = Column(Integer, nullable=False, default=1)
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
    source_description = Column(Text, nullable=False)
    canonical_description_en = Column(Text, nullable=True)
    signed_amount = Column(Float, nullable=False)
    currency = Column(String(10), nullable=False)
    source_locator = Column(String(255), nullable=False)
    inferred_category = Column(String(100), nullable=True)
    category_source = Column(String(50), nullable=True)
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
