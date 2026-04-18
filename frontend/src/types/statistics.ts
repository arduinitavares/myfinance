import type { CategoryStatistics } from './transaction';

export interface ConversionSummary {
  converted_transaction_count: number;
  unavailable_transaction_count: number;
  unavailable_currencies: string[];
}

export interface StatisticsItemsResponse<TItem> {
  reporting_currency: string;
  conversion_summary: ConversionSummary;
  items: TItem[];
}

export interface StatisticsOverviewItem {
  period: string;
  date: string | null;
  reporting_currency: string;
  conversion_summary: ConversionSummary;
  period_income: number;
  period_expenses: number;
  period_net_savings: number;
  savings_rate: number;
  total_income: number;
  total_expenses: number;
  total_net_savings: number;
  income_count: number;
  expense_count: number;
  average_income: number;
  average_expense: number;
  yearly_income: number;
  yearly_expenses: number;
}

export interface StatisticsOverviewResponse {
  current_month: StatisticsOverviewItem;
  last_month: StatisticsOverviewItem;
  previous_year_last_month: StatisticsOverviewItem | null;
  all_time: StatisticsOverviewItem;
}

export interface FinancialStatisticsTimeseriesItem {
  period: string;
  date: string | null;
  period_income: number;
  period_expenses: number;
  period_net_savings: number;
  savings_rate: number;
  total_income: number;
  total_expenses: number;
  total_net_savings: number;
  income_count: number;
  expense_count: number;
  average_income: number;
  average_expense: number;
  yearly_income: number;
  yearly_expenses: number;
}

export type FinancialStatisticsTimeseriesResponse = StatisticsItemsResponse<FinancialStatisticsTimeseriesItem>;

export type CategoryStatisticsItem = Omit<CategoryStatistics, 'date'> & {
  category_name?: string | null;
  period: string;
  date: string | null;
  expense_type: string | null;
};

export type CategoryStatisticsListResponse = StatisticsItemsResponse<CategoryStatisticsItem>;
export type CategoryTimeseriesResponse = StatisticsItemsResponse<CategoryStatisticsItem>;

export interface ExpenseTypeStatisticsCategoryItem {
  category: string;
  period_amount: number;
  period_transaction_count: number;
  period_percentage: number;
}

export interface ExpenseTypeStatisticsItem {
  expense_type: string;
  period: string;
  date: string | null;
  period_amount: number;
  period_transaction_count: number;
  period_percentage: number;
  total_amount: number;
  transaction_count: number;
  total_amount_cumulative: number;
  total_transaction_count: number;
  average_transaction_amount: number;
  yearly_amount: number;
  yearly_transaction_count: number;
  categories: ExpenseTypeStatisticsCategoryItem[];
}

export type ExpenseTypeStatisticsResponse = StatisticsItemsResponse<ExpenseTypeStatisticsItem>;

export interface ExpenseTypeTimeseriesItem {
  date: string;
  expense_type: string;
  period_amount: number;
  period_transaction_count: number;
  period_percentage?: number;
}

export type ExpenseTypeTimeseriesResponse = StatisticsItemsResponse<ExpenseTypeTimeseriesItem>;

export interface CategoryAverageItem {
  category_name: string;
  transaction_type: string;
  expense_type: string | null;
  average_amount: number;
  total_amount: number;
  transaction_count: number;
  average_transaction_amount: number;
  percentage: number;
}

export interface CategoryAveragesResponse {
  reporting_currency: string;
  conversion_summary: ConversionSummary;
  start_date: string;
  end_date: string;
  months_count: number;
  categories: CategoryAverageItem[];
}
