import { 
  Transaction, 
  ExpenseCategory, 
  IncomeCategory, 
  TransferCategory,
  ClassificationStatusFilter,
  TransactionType,
  SortParams
} from '../types/transaction';
import { apiClient } from './apiClient';

export const transactionService = {
  uploadCSV: async (file: File): Promise<Transaction[]> => {
    const formData = new FormData();
    formData.append('file', file);
    
    const response = await apiClient.post('/transactions/upload/', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    return response.data;
  },

  getTransactions: async (
    page: number, 
    pageSize: number,
    sortParams: SortParams,
    filters: {
      search?: string;
      category?: string;
      classification_status?: ClassificationStatusFilter;
      start_date?: string;
      end_date?: string;
    } = {}
  ): Promise<{
    items: Transaction[];
    total: number;
    page: number;
    page_size: number;
    total_pages: number;
  }> => {
    const params: Record<string, any> = {
      page,
      page_size: pageSize,
      sort_field: sortParams.field,
      sort_direction: sortParams.direction,
      ...filters
    };
    const response = await apiClient.get('/transactions/', { params });
    return response.data;
  },

  updateCategory: async (
    transactionId: number,
    category: ExpenseCategory | IncomeCategory | TransferCategory,
    transactionType: TransactionType
  ): Promise<Transaction> => {
    const response = await apiClient.patch(
      `/transactions/${transactionId}/category`,
      null,
      {
        params: {
          category,
          transaction_type: transactionType
        }
      }
    );
    return response.data;
  },

  async deleteTransaction(transactionId: number): Promise<void> {
    const response = await apiClient.delete(`/transactions/${transactionId}`);

    if (!response.data) {
      throw new Error('Failed to delete transaction');
    }
  },
  
  async restoreTransaction(transaction: Transaction): Promise<Transaction> {
    const response = await apiClient.post(
      '/transactions/restore',
      transaction
    );
    
    if (!response.data) {
      throw new Error('Failed to restore transaction');
    }
    
    return response.data;
  }
};
