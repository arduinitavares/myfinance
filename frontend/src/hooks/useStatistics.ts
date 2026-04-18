import { useState, useEffect, useCallback } from 'react';
import { statisticService } from '../services/statisticService';
import { useReportingCurrency } from '../contexts/ReportingCurrencyContext';
import type { StatisticsOverviewResponse } from '../types/statistics';

export const useStatistics = () => {
  const { reportingCurrency } = useReportingCurrency();
  const [statistics, setStatistics] = useState<StatisticsOverviewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchStatistics = useCallback(async () => {
    setLoading(true);
    try {
      const data = await statisticService.getStatisticsOverview();
      setStatistics(data);
      setError(null);
    } catch (err) {
      setError('Failed to fetch statistics');
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchStatistics();
  }, [fetchStatistics, reportingCurrency]);

  return {
    statistics,
    loading,
    error,
    refreshStatistics: fetchStatistics
  };
};
