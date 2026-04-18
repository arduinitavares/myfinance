import { 
  TransactionType,
  WeekdayDistribution,
  SuggestCategoryResponse,
  TimePeriod
} from '../types/transaction';
import { apiClient, type ReportingCurrency } from './apiClient';

export interface TransferSummaryItem {
  subtype: string;
  transaction_count: number;
  total_outgoing: number;
  total_incoming: number;
}

export interface TransferSummaryResponse {
  start_date: string;
  end_date: string;
  reporting_currency: ReportingCurrency;
  items: TransferSummaryItem[];
}

export const statisticService = {
  getCategoryStatistics: async (
    period: 'monthly' | 'yearly' | 'all_time' = 'monthly',
    date?: string
  ) => {
    const params: Record<string, string> = { period };
    if (date) {
      params.date = date;
    }
    
    const response = await apiClient.get('/statistics/by-category', {
      params
    });
    return response.data;
  },

  getExpenseTypeStatistics: async (
    period: 'monthly' | 'yearly' | 'all_time' = 'monthly',
    date?: string
  ) => {
    const params: Record<string, string> = { period };
    if (date) {
      params.date = date;
    }
    
    const response = await apiClient.get('/statistics/by-expense-type', {
      params
    });
    return response.data;
  },

  getStatisticsOverview: async () => {
    const response = await apiClient.get('/statistics/overview');
    return response.data;
  },

  getTransferSummary: async (start_date?: string, end_date?: string): Promise<TransferSummaryResponse> => {
    const params: Record<string, string> = {};
    if (start_date) params.start_date = start_date;
    if (end_date) params.end_date = end_date;

    const response = await apiClient.get('/statistics/transfers/summary', { params });
    return response.data;
  },

  initializeStatistics: async () => {
    const response = await apiClient.post('/statistics/initialize');
    return response.data;
  },

  getStatisticsTimeseries: async (start_date?: string, end_date?: string, time_period?: string) => {
    const params: Record<string, string> = {};
    if (start_date) params.start_date = start_date;
    if (end_date) params.end_date = end_date;
    if (time_period) params.time_period = time_period;
    const response = await apiClient.get('/statistics/timeseries', { params });
    return response.data;
  },

  getCategoryStatisticsTimeseries: async (
    transaction_type?: TransactionType,
    category_name?: string,
    start_date?: string, 
    end_date?: string,
    time_period?: TimePeriod
  ) => {
    const params: Record<string, string> = {};
    if (transaction_type) params.transaction_type = transaction_type;
    if (category_name) params.category_name = category_name;
    if (start_date) params.start_date = start_date;
    if (end_date) params.end_date = end_date;
    if (time_period) params.time_period = time_period;
    const response = await apiClient.get('/statistics/category/timeseries', { params });
    return response.data;
  },

  getExpenseTypeStatisticsTimeseries: async (
    expense_type?: string,
    start_date?: string, 
    end_date?: string,
    time_period?: TimePeriod
  ) => {
    const params: Record<string, string> = {};
    if (expense_type) params.expense_type = expense_type;
    if (start_date) params.start_date = start_date;
    if (end_date) params.end_date = end_date;
    if (time_period) params.time_period = time_period;
    const response = await apiClient.get('/statistics/expense-type/timeseries', { params });
    return response.data;
  },

  suggestCategory: async (
    description: string,
    amount: number,
    transactionType: TransactionType
  ): Promise<SuggestCategoryResponse> => {
    const response = await apiClient.post('/suggestions/category', {
      description,
      amount,
      transaction_type: transactionType
    });
    return response.data;
  },

  getWeekdayDistribution: async (
    transactionType?: TransactionType,
    startDate?: string,
    endDate?: string
  ): Promise<WeekdayDistribution> => {
    const params: Record<string, string> = {};
    if (transactionType) params.transaction_type = transactionType;
    if (startDate) params.start_date = startDate;
    if (endDate) params.end_date = endDate;
    
    const response = await apiClient.get('/statistics/weekday-distribution', { params });
    return response.data;
  },

  getCategoryAverages: async (
    transactionType?: TransactionType,
    startDate?: string,
    endDate?: string,
    timePeriod?: TimePeriod
  ) => {
    const params: Record<string, string> = {};
    if (transactionType) params.transaction_type = transactionType;
    if (startDate) params.start_date = startDate;
    if (endDate) params.end_date = endDate;
    if (timePeriod) params.time_period = timePeriod;
    
    const response = await apiClient.get('/statistics/category/averages', { params });
    return response.data;
  },
};
