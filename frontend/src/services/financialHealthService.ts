import { 
  FinancialHealthScore,
  FinancialHealthHistory,
  Recommendation
} from '../types/transaction';
import { apiClient } from './apiClient';

export const financialHealthService = {
  getFinancialHealthScore: async (targetDate?: string, signal?: AbortSignal): Promise<FinancialHealthScore> => {
    const params: Record<string, string> = {};
    if (targetDate) params.target_date = targetDate;
    const response = await apiClient.get('/financial-health/score', { params, signal });
    return response.data;
  },

  getFinancialHealthHistory: async (months: number = 12, signal?: AbortSignal): Promise<FinancialHealthHistory> => {
    const params = { months };
    const response = await apiClient.get('/financial-health/history', { params, signal });
    return response.data;
  },

  getRecommendations: async (activeOnly: boolean = true, signal?: AbortSignal): Promise<Recommendation[]> => {
    const params = { active_only: activeOnly };
    const response = await apiClient.get('/financial-health/recommendations', { params, signal });
    return response.data;
  },

  updateRecommendation: async (recommendationId: number, isCompleted: boolean): Promise<Recommendation> => {
    const response = await apiClient.patch(
      `/financial-health/recommendations/${recommendationId}`,
      {
        is_completed: isCompleted,
        date_completed: isCompleted ? new Date().toISOString().split('T')[0] : null
      }
    );
    return response.data;
  },

  recalculateHealthScore: async (targetDate?: string): Promise<FinancialHealthScore> => {
    const params: Record<string, string> = {};
    if (targetDate) params.target_date = targetDate;
    
    const response = await apiClient.post('/financial-health/recalculate', null, { params });
    return response.data;
  },
};
