from datetime import date

from app.models.classification import (
    ClassificationSession,
    ClassificationSessionStatus,
    RecurrencePattern,
)
from app.models.imports import ImportSession
from app.models.statistics import FinancialStatistics, StatisticsPeriod
from app.models.transaction import ExpenseCategory, Transaction, TransactionType, TransferCategory

from app.migrations.migrate_europe_iban_reclassification import (
    migrate_europe_iban_reclassification,
)


def _create_import_session(db_session, *, extractor_id: str | None = None, suffix: str) -> ImportSession:
    session = ImportSession(
        file_name=f"statement-{suffix}.pdf",
        file_hash=f"hash-{suffix}",
        mime_type="application/pdf",
        status="committed",
        extractor_id=extractor_id,
    )
    db_session.add(session)
    db_session.flush()
    return session


def _create_transaction(
    db_session,
    *,
    account_number: str,
    description: str,
    amount: float,
    transaction_type: TransactionType,
    expense_category: ExpenseCategory | None = None,
    transfer_category: TransferCategory | None = None,
    counterparty_account: str | None = None,
    import_source_description: str | None = None,
    import_session_id: int | None = None,
) -> Transaction:
    transaction = Transaction(
        account_number=account_number,
        transaction_date=date(2025, 1, 15),
        amount=amount,
        currency="EUR",
        description=description,
        counterparty_name="Counterparty",
        counterparty_account=counterparty_account,
        import_source_description=import_source_description,
        import_session_id=import_session_id,
        transaction_type=transaction_type,
        expense_category=expense_category,
        transfer_category=transfer_category,
        source_bank="europe",
    )
    db_session.add(transaction)
    db_session.flush()
    return transaction


def _attach_active_legacy_recurrence(
    db_session,
    *,
    transaction: Transaction,
    category: str,
) -> RecurrencePattern:
    session = ClassificationSession(
        transaction_id=transaction.id,
        status=ClassificationSessionStatus.ACCEPTED,
        provider_name="manual",
        model_name="manual",
        final_transaction_type=TransactionType.EXPENSE,
        final_category=category,
    )
    db_session.add(session)
    db_session.flush()

    pattern = RecurrencePattern(
        source_session_id=session.id,
        seed_transaction_id=transaction.id,
        normalized_description_key=transaction.description.lower(),
        source_bank=transaction.source_bank,
        currency=transaction.currency,
        transaction_type=TransactionType.EXPENSE,
        category=category,
        frequency="monthly",
        active=True,
    )
    db_session.add(pattern)
    db_session.flush()

    transaction.recurrence_pattern_id = pattern.id
    db_session.flush()
    return pattern


def test_migrate_europe_iban_reclassification_rewrites_only_deterministic_rows(db_session):
    mastercard_session = _create_import_session(
        db_session,
        extractor_id="beobank_mastercard_pdf_v1",
        suffix="mastercard",
    )
    parser_session = _create_import_session(
        db_session,
        extractor_id="beobank_mastercard_pdf_v1",
        suffix="parser-artifact",
    )

    belfius_settlement = _create_transaction(
        db_session,
        account_number="BE46063651946836",
        description="Monthly reimbursement to Belfius card",
        amount=-240.0,
        transaction_type=TransactionType.EXPENSE,
        expense_category=ExpenseCategory.CREDIT_PAYMENT,
        counterparty_account="BE36950263030181",
    )
    recurrence_pattern = _attach_active_legacy_recurrence(
        db_session,
        transaction=belfius_settlement,
        category=ExpenseCategory.CREDIT_PAYMENT.value,
    )

    europe_loan_payment = _create_transaction(
        db_session,
        account_number="BE11950212984548",
        description="Europe payment to loan account",
        amount=-175.0,
        transaction_type=TransactionType.EXPENSE,
        expense_category=ExpenseCategory.DEBT,
        counterparty_account="BE74950226230607",
    )
    internal_transfer = _create_transaction(
        db_session,
        account_number="BE11950212984548",
        description="Transfer between Europe cash accounts",
        amount=-90.0,
        transaction_type=TransactionType.TRANSFER,
        transfer_category=TransferCategory.INTERNAL_TRANSFER,
        counterparty_account="BE46063651946836",
    )
    mastercard_payment = _create_transaction(
        db_session,
        account_number="****1234",
        description="BETALING CARD PAYMENT IBAN BE11950212984548",
        amount=240.0,
        transaction_type=TransactionType.EXPENSE,
        expense_category=ExpenseCategory.CREDIT_PAYMENT,
        import_session_id=mastercard_session.id,
    )
    wise_row = _create_transaction(
        db_session,
        account_number="BE46063651946836",
        description="Wise transfer to shared wallet",
        amount=-65.0,
        transaction_type=TransactionType.EXPENSE,
        expense_category=ExpenseCategory.CREDIT_PAYMENT,
        counterparty_account="BE36950263030181",
    )
    parser_artifact = _create_transaction(
        db_session,
        account_number="****5678",
        description="BETALING -2 IBAN BE11950212984548",
        amount=85.0,
        transaction_type=TransactionType.EXPENSE,
        expense_category=ExpenseCategory.CREDIT_PAYMENT,
        import_session_id=parser_session.id,
    )

    db_session.add(
        FinancialStatistics(
            period=StatisticsPeriod.MONTHLY,
            date=date(2025, 1, 31),
            period_income=0.0,
            period_expenses=565.0,
            period_net_savings=-565.0,
            savings_rate=0.0,
            total_income=0.0,
            total_expenses=565.0,
            total_net_savings=-565.0,
            income_count=0,
            expense_count=4,
            average_income=0.0,
            average_expense=141.25,
            yearly_income=0.0,
            yearly_expenses=565.0,
        )
    )
    db_session.add(
        FinancialStatistics(
            period=StatisticsPeriod.ALL_TIME,
            date=None,
            period_income=0.0,
            period_expenses=565.0,
            period_net_savings=-565.0,
            savings_rate=0.0,
            total_income=0.0,
            total_expenses=565.0,
            total_net_savings=-565.0,
            income_count=0,
            expense_count=4,
            average_income=0.0,
            average_expense=141.25,
            yearly_income=0.0,
            yearly_expenses=565.0,
        )
    )
    db_session.commit()

    summary = migrate_europe_iban_reclassification(db_session)
    db_session.expire_all()

    refreshed_settlement = db_session.get(Transaction, belfius_settlement.id)
    assert refreshed_settlement is not None
    assert refreshed_settlement.transaction_type == TransactionType.TRANSFER
    assert refreshed_settlement.transfer_category == TransferCategory.CREDIT_CARD_SETTLEMENT
    assert refreshed_settlement.expense_category is None
    assert refreshed_settlement.income_category is None
    assert refreshed_settlement.recurrence_pattern_id is None

    refreshed_pattern = db_session.get(RecurrencePattern, recurrence_pattern.id)
    assert refreshed_pattern is not None
    assert refreshed_pattern.active is False

    refreshed_loan_payment = db_session.get(Transaction, europe_loan_payment.id)
    assert refreshed_loan_payment is not None
    assert refreshed_loan_payment.transaction_type == TransactionType.TRANSFER
    assert refreshed_loan_payment.transfer_category == TransferCategory.DEBT_REPAYMENT_SENT

    refreshed_internal_transfer = db_session.get(Transaction, internal_transfer.id)
    assert refreshed_internal_transfer is not None
    assert refreshed_internal_transfer.transaction_type == TransactionType.TRANSFER
    assert refreshed_internal_transfer.transfer_category == TransferCategory.INTERNAL_TRANSFER

    refreshed_mastercard_payment = db_session.get(Transaction, mastercard_payment.id)
    assert refreshed_mastercard_payment is not None
    assert refreshed_mastercard_payment.transaction_type == TransactionType.TRANSFER
    assert refreshed_mastercard_payment.transfer_category == TransferCategory.CREDIT_CARD_SETTLEMENT

    refreshed_wise = db_session.get(Transaction, wise_row.id)
    assert refreshed_wise is not None
    assert refreshed_wise.transaction_type == TransactionType.EXPENSE
    assert refreshed_wise.transfer_category is None

    refreshed_parser_artifact = db_session.get(Transaction, parser_artifact.id)
    assert refreshed_parser_artifact is not None
    assert refreshed_parser_artifact.description.endswith("-2 IBAN BE11950212984548")
    assert refreshed_parser_artifact.transaction_type == TransactionType.EXPENSE
    assert refreshed_parser_artifact.transfer_category is None

    active_pattern_links = (
        db_session.query(Transaction)
        .join(RecurrencePattern, Transaction.recurrence_pattern_id == RecurrencePattern.id)
        .filter(
            Transaction.id.in_([belfius_settlement.id, europe_loan_payment.id, mastercard_payment.id]),
            RecurrencePattern.active.is_(True),
        )
        .count()
    )
    assert active_pattern_links == 0

    monthly_stats = (
        db_session.query(FinancialStatistics)
        .filter(
            FinancialStatistics.period == StatisticsPeriod.MONTHLY,
            FinancialStatistics.date == date(2025, 1, 31),
        )
        .one()
    )
    all_time_stats = (
        db_session.query(FinancialStatistics)
        .filter(FinancialStatistics.period == StatisticsPeriod.ALL_TIME)
        .one()
    )
    assert monthly_stats.period_expenses == 150.0
    assert monthly_stats.total_expenses == 150.0
    assert monthly_stats.expense_count == 2
    assert all_time_stats.period_expenses == 150.0
    assert all_time_stats.total_expenses == 150.0

    assert summary == {
        "updated_transactions": 3,
        "skipped_wise": 1,
        "skipped_ambiguous": 0,
        "skipped_parser_artifact": 1,
        "deactivated_patterns": 1,
        "detached_transactions": 1,
        "recomputed_aggregates": 1,
    }


def test_migrate_europe_iban_reclassification_skips_recompute_when_nothing_changes(db_session):
    already_correct = _create_transaction(
        db_session,
        account_number="BE11950212984548",
        description="Savings shuffle",
        amount=-120.0,
        transaction_type=TransactionType.TRANSFER,
        transfer_category=TransferCategory.INTERNAL_TRANSFER,
        counterparty_account="BE46063651946836",
    )
    db_session.commit()

    summary = migrate_europe_iban_reclassification(db_session)
    db_session.expire_all()

    refreshed = db_session.get(Transaction, already_correct.id)
    assert refreshed is not None
    assert refreshed.transaction_type == TransactionType.TRANSFER
    assert refreshed.transfer_category == TransferCategory.INTERNAL_TRANSFER
    assert db_session.query(FinancialStatistics).count() == 0
    assert summary == {
        "updated_transactions": 0,
        "skipped_wise": 0,
        "skipped_ambiguous": 0,
        "skipped_parser_artifact": 0,
        "deactivated_patterns": 0,
        "detached_transactions": 0,
        "recomputed_aggregates": 0,
    }


def test_migrate_europe_iban_reclassification_skips_conflicting_known_account_signals(db_session):
    conflicting = _create_transaction(
        db_session,
        account_number="BE11950212984548",
        description="Statement note mentions IBAN BE74950226230607",
        amount=-210.0,
        transaction_type=TransactionType.EXPENSE,
        expense_category=ExpenseCategory.CREDIT_PAYMENT,
        counterparty_account="BE36950263030181",
        import_source_description="Imported text also mentions IBAN BE36950263030181",
    )
    db_session.commit()

    summary = migrate_europe_iban_reclassification(db_session)
    db_session.expire_all()

    refreshed = db_session.get(Transaction, conflicting.id)
    assert refreshed is not None
    assert refreshed.transaction_type == TransactionType.EXPENSE
    assert refreshed.transfer_category is None
    assert refreshed.expense_category == ExpenseCategory.CREDIT_PAYMENT
    assert db_session.query(FinancialStatistics).count() == 0
    assert summary == {
        "updated_transactions": 0,
        "skipped_wise": 0,
        "skipped_ambiguous": 1,
        "skipped_parser_artifact": 0,
        "deactivated_patterns": 0,
        "detached_transactions": 0,
        "recomputed_aggregates": 0,
    }
