"""Module for backend app models transaction."""

import enum
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, Enum, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base

if TYPE_CHECKING:
    from .classification import ClassificationSession, RecurrencePattern


class TransactionType(enum.Enum):
    """Represent transaction type."""

    INCOME = "Income"
    EXPENSE = "Expense"
    # Movements between owned accounts; excluded from income/expense totals.
    TRANSFER = "Transfer"


class ExpenseType(enum.Enum):
    """Represent expense type."""

    FIXED_ESSENTIAL = "Fixed Essential"  # Ramit's "Fixed Costs" (50-60%)
    GUILT_FREE_DISCRETIONARY = "Discretionary"  # Ramit's "Guilt-Free Spending" (20-35%)
    SAVINGS_INVESTMENT = (
        "Savings & Investment"  # Ramit's "Investments" & "Savings" (10-20%)
    )
    NEUTRAL = "Neutral"  # For non-spending operational categories


class ExpenseCategory(enum.Enum):
    """Represent expense category."""

    # --- 1. Fixed Essentials (Survival & Obligations) ---
    HOUSING = "Housing"  # Rent, Mortgage
    UTILITIES = "Utilities"  # Energy, Water, Internet
    GROCERIES = "Groceries"  # Supermarket food
    TRANSPORTATION = "Transportation"  # Public transport, Car insurance, Gas
    INSURANCE = "Insurance"  # Mandatory insurance (Zorgpremie, Family)
    HEALTH = "Health"  # Doctor, Pharmacy (Essential medical)

    # --- 2. Debt & Financial Obligations (Essential) ---
    LOAN_REPAYMENT = "Loan Repayment"  # Fixed loan payments (e.g., Ivan)
    CREDIT_PAYMENT = "Credit Payment"  # Repaying credit card/line (e.g., Belfius debt)
    DEBT = "Debt"  # General debt repayment
    FINANCIAL_FEES = "Financial Fees"  # Bank fees, late fees

    # --- 3. Savings & Investments (Future Wealth) ---
    INVESTMENTS = "Investments"  # ETFs, Crypto, Stocks
    SAVINGS = "Savings"  # Emergency Fund, specific saving goals

    # --- 4. Guilt-Free Discretionary (Lifestyle) ---
    EATING_OUT = "Eating Out"  # Restaurants, UberEats
    PERSONAL = "Personal"  # Gym (Stadium), Haircuts, Cosmetics
    SHOPPING = "Shopping"  # Clothes, Gadgets (Non-essential)
    GIFTS = "Gifts"
    DONATIONS = "Donations"
    EDUCATION = "Education"  # Courses, Books (Self-improvement)
    TRAVEL = "Travel"
    ENTERTAINMENT = "Entertainment"  # Movies, Netflix, Events

    # --- 5. Neutral/Operational ---
    OTHERS = "Others"

    @property
    def expense_type(self) -> ExpenseType:
        """Classify expense categories according to the spending plan."""
        # 50-60% of Income
        fixed_essential = [
            ExpenseCategory.HOUSING,
            ExpenseCategory.UTILITIES,
            ExpenseCategory.GROCERIES,
            ExpenseCategory.TRANSPORTATION,
            ExpenseCategory.INSURANCE,
            ExpenseCategory.HEALTH,
            ExpenseCategory.LOAN_REPAYMENT,
            ExpenseCategory.CREDIT_PAYMENT,
            ExpenseCategory.DEBT,
            ExpenseCategory.FINANCIAL_FEES,
        ]

        # 10-20% of Income
        savings_investments = [ExpenseCategory.INVESTMENTS, ExpenseCategory.SAVINGS]

        if self in fixed_essential:
            return ExpenseType.FIXED_ESSENTIAL
        if self in savings_investments:
            return ExpenseType.SAVINGS_INVESTMENT
        # All remaining are Guilt-Free Discretionary (20-35%)
        return ExpenseType.GUILT_FREE_DISCRETIONARY

    @property
    def is_essential(self) -> bool:
        """Handle is essential."""
        return self.expense_type == ExpenseType.FIXED_ESSENTIAL

    @property
    def is_discretionary(self) -> bool:
        """Handle is discretionary."""
        return self.expense_type == ExpenseType.GUILT_FREE_DISCRETIONARY

    @classmethod
    def get_essential_categories(cls) -> list["ExpenseCategory"]:
        """Return essential categories."""
        return [category for category in cls if category.is_essential]

    @classmethod
    def get_discretionary_categories(cls) -> list["ExpenseCategory"]:
        """Return discretionary categories."""
        return [category for category in cls if category.is_discretionary]


class IncomeCategory(enum.Enum):
    """Represent income category."""

    SALARY = "Salary"
    INVESTMENTS = "Investment Income"
    BUSINESS = "Business Income"
    RENTAL = "Rental Income"
    FREELANCE = "Freelance Income"
    PENSION = "Pension"
    BENEFITS = "Benefits"  # Unemployment, Child benefits
    GIFTS = "Gifts Received"
    REFUNDS = "Refunds"  # Tax returns, shop refunds
    LOAN_DISBURSEMENT = (
        "Loan Disbursement"  # Incoming money from Credit Line/Loans (NOT EARNINGS)
    )
    OTHER = "Other Income"


class TransferCategory(enum.Enum):
    """Represent transfer category."""

    INTERNAL_TRANSFER = "Internal Transfer"
    CREDIT_CARD_SETTLEMENT = "Credit Card Settlement"
    LOAN_TO_PERSON = "Loan to Person"
    LOAN_REPAYMENT_RECEIVED = "Loan Repayment Received"
    LOAN_FROM_PERSON = "Loan from Person"
    DEBT_REPAYMENT_SENT = "Debt Repayment Sent"


class Transaction(Base):
    """Represent transaction."""

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    import_session_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("import_sessions.id"), index=True, nullable=True
    )
    import_source_locator: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    import_source_description: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    canonical_description_en: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    account_number: Mapped[str] = mapped_column(String(50), index=True, nullable=True)
    transaction_date: Mapped[date] = mapped_column(Date, index=True, nullable=True)
    amount: Mapped[float] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=True)
    description: Mapped[str] = mapped_column(String(500), nullable=True)
    counterparty_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    counterparty_account: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Updated Enum columns
    transaction_type: Mapped[TransactionType] = mapped_column(
        Enum(TransactionType), nullable=True
    )
    expense_category: Mapped[ExpenseCategory | None] = mapped_column(
        Enum(ExpenseCategory), nullable=True
    )
    income_category: Mapped[IncomeCategory | None] = mapped_column(
        Enum(IncomeCategory), nullable=True
    )
    transfer_category: Mapped[TransferCategory | None] = mapped_column(
        Enum(TransferCategory), nullable=True
    )
    classification_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    recurrence_pattern_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "recurrence_patterns.id",
            name="fk_transactions_recurrence_pattern_id",
            use_alter=True,
        ),
        nullable=True,
        index=True,
    )

    source_bank: Mapped[str] = mapped_column(String(10), nullable=True)

    classification_sessions: Mapped[list["ClassificationSession"]] = relationship(
        "ClassificationSession",
        back_populates="transaction",
        cascade="all, delete-orphan",
    )
    recurrence_pattern: Mapped["RecurrencePattern | None"] = relationship(
        "RecurrencePattern", foreign_keys=[recurrence_pattern_id], post_update=True
    )
    seeded_recurrence_patterns: Mapped[list["RecurrencePattern"]] = relationship(
        "RecurrencePattern",
        foreign_keys="RecurrencePattern.seed_transaction_id",
        back_populates="seed_transaction",
        cascade="all, delete-orphan",
    )
