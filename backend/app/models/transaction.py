from sqlalchemy import Column, Integer, String, Float, Date, Enum, ForeignKey
from sqlalchemy.orm import relationship
from ..database import Base
import enum

class TransactionType(enum.Enum):
    INCOME = "Income"
    EXPENSE = "Expense"
    TRANSFER = "Transfer"  # New type for movements between own accounts (avoids double counting)

class ExpenseType(enum.Enum):
    FIXED_ESSENTIAL = "Fixed Essential"       # Ramit's "Fixed Costs" (50-60%)
    GUILT_FREE_DISCRETIONARY = "Discretionary" # Ramit's "Guilt-Free Spending" (20-35%)
    SAVINGS_INVESTMENT = "Savings & Investment" # Ramit's "Investments" & "Savings" (10-20%)
    NEUTRAL = "Neutral"                       # For non-spending operational categories

class ExpenseCategory(enum.Enum):
    # --- 1. Fixed Essentials (Survival & Obligations) ---
    HOUSING = "Housing"                # Rent, Mortgage
    UTILITIES = "Utilities"            # Energy, Water, Internet
    GROCERIES = "Groceries"            # Supermarket food
    TRANSPORTATION = "Transportation"  # Public transport, Car insurance, Gas
    INSURANCE = "Insurance"            # Mandatory insurance (Zorgpremie, Family)
    HEALTH = "Health"                  # Doctor, Pharmacy (Essential medical)
    
    # --- 2. Debt & Financial Obligations (Essential) ---
    LOAN_REPAYMENT = "Loan Repayment"  # Fixed loan payments (e.g., Ivan)
    CREDIT_PAYMENT = "Credit Payment"  # Repaying credit card/line (e.g., Belfius debt)
    DEBT = "Debt"                      # General debt repayment
    FINANCIAL_FEES = "Financial Fees"  # Bank fees, late fees
    
    # --- 3. Savings & Investments (Future Wealth) ---
    INVESTMENTS = "Investments"        # ETFs, Crypto, Stocks
    SAVINGS = "Savings"                # Emergency Fund, specific saving goals

    # --- 4. Guilt-Free Discretionary (Lifestyle) ---
    EATING_OUT = "Eating Out"          # Restaurants, UberEats
    PERSONAL = "Personal"              # Gym (Stadium), Haircuts, Cosmetics
    SHOPPING = "Shopping"              # Clothes, Gadgets (Non-essential)
    GIFTS = "Gifts"
    DONATIONS = "Donations"
    EDUCATION = "Education"            # Courses, Books (Self-improvement)
    TRAVEL = "Travel"
    ENTERTAINMENT = "Entertainment"    # Movies, Netflix, Events
    
    # --- 5. Neutral/Operational ---
    OTHERS = "Others"

    @property
    def expense_type(self):
        """
        Classify expense categories according to Ramit Sethi's 'Conscious Spending Plan'.
        """
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
            ExpenseCategory.FINANCIAL_FEES
        ]
        
        # 10-20% of Income
        savings_investments = [
            ExpenseCategory.INVESTMENTS,
            ExpenseCategory.SAVINGS
        ]
        
        if self in fixed_essential:
            return ExpenseType.FIXED_ESSENTIAL
        elif self in savings_investments:
            return ExpenseType.SAVINGS_INVESTMENT
        else:
            # All remaining are Guilt-Free Discretionary (20-35%)
            return ExpenseType.GUILT_FREE_DISCRETIONARY
    
    @property
    def is_essential(self):
        return self.expense_type == ExpenseType.FIXED_ESSENTIAL
    
    @property
    def is_discretionary(self):
        return self.expense_type == ExpenseType.GUILT_FREE_DISCRETIONARY

    @classmethod
    def get_essential_categories(cls):
        return [category for category in cls if category.is_essential]
    
    @classmethod
    def get_discretionary_categories(cls):
        return [category for category in cls if category.is_discretionary]

class IncomeCategory(enum.Enum):
    SALARY = "Salary"
    INVESTMENTS = "Investment Income"
    BUSINESS = "Business Income"
    RENTAL = "Rental Income"
    FREELANCE = "Freelance Income"
    PENSION = "Pension"
    BENEFITS = "Benefits"             # Unemployment, Child benefits
    GIFTS = "Gifts Received"
    REFUNDS = "Refunds"               # Tax returns, shop refunds
    LOAN_DISBURSEMENT = "Loan Disbursement" # Incoming money from Credit Line/Loans (NOT EARNINGS)
    OTHER = "Other Income"

class TransferCategory(enum.Enum):
    INTERNAL_TRANSFER = "Internal Transfer"
    CREDIT_CARD_SETTLEMENT = "Credit Card Settlement"
    LOAN_TO_PERSON = "Loan to Person"
    LOAN_REPAYMENT_RECEIVED = "Loan Repayment Received"
    LOAN_FROM_PERSON = "Loan from Person"
    DEBT_REPAYMENT_SENT = "Debt Repayment Sent"

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    import_session_id = Column(Integer, ForeignKey("import_sessions.id"), index=True, nullable=True)
    import_source_locator = Column(String(255), nullable=True)
    import_source_description = Column(String(500), nullable=True)
    canonical_description_en = Column(String(500), nullable=True)
    account_number = Column(String(50), index=True)
    transaction_date = Column(Date, index=True)
    amount = Column(Float)
    currency = Column(String(3))
    description = Column(String(500))
    counterparty_name = Column(String(200), nullable=True)
    counterparty_account = Column(String(50), nullable=True)
    
    # Updated Enum columns
    transaction_type = Column(Enum(TransactionType))
    expense_category = Column(Enum(ExpenseCategory), nullable=True)
    income_category = Column(Enum(IncomeCategory), nullable=True)
    transfer_category = Column(Enum(TransferCategory), nullable=True)
    classification_source = Column(String(50), nullable=True)
    recurrence_pattern_id = Column(
        Integer,
        ForeignKey(
            "recurrence_patterns.id",
            name="fk_transactions_recurrence_pattern_id",
            use_alter=True,
        ),
        nullable=True,
        index=True,
    )
    
    source_bank = Column(String(10))

    classification_sessions = relationship(
        "ClassificationSession",
        back_populates="transaction",
        cascade="all, delete-orphan",
    )
    recurrence_pattern = relationship("RecurrencePattern", foreign_keys=[recurrence_pattern_id], post_update=True)
    seeded_recurrence_patterns = relationship(
        "RecurrencePattern",
        foreign_keys="RecurrencePattern.seed_transaction_id",
        back_populates="seed_transaction",
        cascade="all, delete-orphan",
    )
