export enum TransactionType {
  INCOME = "Income",
  EXPENSE = "Expense",
  TRANSFER = "Transfer"
}

export enum TransferCategory {
  INTERNAL_TRANSFER = "Internal Transfer",
  CREDIT_CARD_SETTLEMENT = "Credit Card Settlement",
  LOAN_TO_PERSON = "Loan to Person",
  LOAN_REPAYMENT_RECEIVED = "Loan Repayment Received",
  LOAN_FROM_PERSON = "Loan from Person",
  DEBT_REPAYMENT_SENT = "Debt Repayment Sent"
}

export enum ExpenseType {
  FIXED_ESSENTIAL = "Fixed Essential",
  GUILT_FREE_DISCRETIONARY = "Discretionary",
  SAVINGS_INVESTMENT = "Savings & Investment",
  NEUTRAL = "Neutral"
}

export enum ExpenseCategory {
  // Fixed Essentials (Survival & Obligations)
  HOUSING = "Housing",
  UTILITIES = "Utilities",
  GROCERIES = "Groceries",
  TRANSPORTATION = "Transportation",
  INSURANCE = "Insurance",
  HEALTH = "Health",
  
  // Debt & Financial Obligations (Essential)
  LOAN_REPAYMENT = "Loan Repayment",
  CREDIT_PAYMENT = "Credit Payment",
  DEBT = "Debt",
  FINANCIAL_FEES = "Financial Fees",
  
  // Savings & Investments (Future Wealth)
  INVESTMENTS = "Investments",
  SAVINGS = "Savings",
  
  // Guilt-Free Discretionary (Lifestyle)
  EATING_OUT = "Eating Out",
  PERSONAL = "Personal",
  SHOPPING = "Shopping",
  GIFTS = "Gifts",
  DONATIONS = "Donations",
  EDUCATION = "Education",
  TRAVEL = "Travel",
  ENTERTAINMENT = "Entertainment",
  
  OTHERS = "Others"
}

export enum IncomeCategory {
  SALARY = "Salary",
  INVESTMENTS = "Investment Income",
  BUSINESS = "Business Income",
  RENTAL = "Rental Income",
  FREELANCE = "Freelance Income",
  PENSION = "Pension",
  BENEFITS = "Benefits",
  GIFTS = "Gifts Received",
  REFUNDS = "Refunds",
  LOAN_DISBURSEMENT = "Loan Disbursement",
  OTHER = "Other Income"
}

export interface DisplayMoneyFields {
  display_amount?: number | null;
  display_currency?: string | null;
  display_fx_rate?: number | null;
  display_rate_date?: string | null;
  display_is_available?: boolean | null;
  display_unavailable_reason?: string | null;
}

export interface Transaction extends DisplayMoneyFields {
  id: number;
  account_number: string;
  transaction_date: string;
  amount: number;
  currency: string;
  description: string;
  counterparty_name?: string;
  counterparty_account?: string;
  transaction_type: TransactionType;
  expense_category?: ExpenseCategory;
  income_category?: IncomeCategory;
  transfer_category?: TransferCategory;
  classification_source?:
    | 'manual'
    | 'assistant'
    | 'assistant_batch'
    | 'upload_suggester'
    | 'recurrence_pattern'
    | null;
  recurrence_pattern_id?: number | null;
  source_bank: string;
}

export interface CategoryStatistics {
  category: string;
  transaction_type: TransactionType;
  period?: string;
  date?: string;
  
  // For backward compatibility
  total_amount: number;
  transaction_count: number;
  
  // Period-specific metrics
  period_amount?: number;
  period_transaction_count?: number;
  period_percentage?: number;
  
  // Cumulative metrics
  total_amount_cumulative?: number;
  total_transaction_count?: number;
  
  // Averages
  average_transaction_amount?: number;
  
  // Yearly metrics
  yearly_amount?: number;
  yearly_transaction_count?: number;
}

export interface CategorySuggestion {
  category: string;
  confidence: number;
}

export interface SuggestCategoryResponse {
  suggestions: CategorySuggestion[];
}

export interface SortParams {
  field: 'date' | 'description' | 'amount' | 'type';
  direction: 'asc' | 'desc';
}

export type ClassificationStatusFilter = 'all' | 'classified' | 'unclassified';

export enum ActionType {
  DELETE_TRANSACTION = 'DELETE_TRANSACTION',
  UPDATE_CATEGORY = 'UPDATE_CATEGORY'
}

export enum TimePeriod {
  THREE_MONTHS = "3M",
  SIX_MONTHS = "6M",
  YEAR_TO_DATE = "YTD",
  ONE_YEAR = "1Y",
  TWO_YEARS = "2Y",
  ALL_TIME = "ALL_TIME"
}

export interface DeleteTransactionAction {
  type: ActionType.DELETE_TRANSACTION;
  transaction: Transaction;
}

export interface UpdateCategoryAction {
  type: ActionType.UPDATE_CATEGORY;
  transactionId: number;
  oldCategory: ExpenseCategory | IncomeCategory | TransferCategory | undefined;
  newCategory: ExpenseCategory | IncomeCategory | TransferCategory;
  oldTransactionType: TransactionType;
  newTransactionType: TransactionType;
}

export type UndoableAction = DeleteTransactionAction | UpdateCategoryAction;

export interface WeekdayStats {
  count: number;
  total: number;
  average: number;
  median: number;
  min: number;
  max: number;
}

export interface WeekdayTypeStats {
  expense: WeekdayStats;
  income: WeekdayStats;
}

export interface WeekdayDistribution {
  weekdays: {
    [key: string]: WeekdayTypeStats;
  };
  transaction_count: number;
}

// Financial Health Types
export interface FinancialHealthScore {
  id: number;
  date: string;
  overall_score: number;
  savings_rate_score: number;
  expense_ratio_score: number;
  budget_adherence_score: number;
  debt_to_income_score: number;
  emergency_fund_score: number;
  spending_stability_score: number;
  investment_rate_score: number;
  
  // Raw metrics
  savings_rate: number;
  expense_ratio: number;
  budget_adherence: number;
  debt_to_income: number;
  emergency_fund_months: number;
  spending_stability: number;
  investment_rate: number;
  
  // Recommendations
  recommendations?: RecommendationData[];
}

export interface FinancialHealthHistory {
  dates: string[];
  overall_scores: number[];
  savings_rate_scores: number[];
  expense_ratio_scores: number[];
  budget_adherence_scores: number[];
  debt_to_income_scores: number[];
  emergency_fund_scores: number[];
  spending_stability_scores: number[];
  investment_rate_scores: number[];
}

export interface RecommendationData {
  title: string;
  description: string;
  category: string;
  impact_area: string;
  priority: number;
  estimated_score_improvement: number;
}

export interface Recommendation {
  id: number;
  title: string;
  description: string;
  category: string;
  impact_area: string;
  priority: number;
  estimated_score_improvement: number;
  is_completed: boolean;
  date_completed: string | null;
  date_created: string;
}
