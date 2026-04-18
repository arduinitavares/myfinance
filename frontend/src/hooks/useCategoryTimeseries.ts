import { useState, useEffect, useCallback } from 'react';
import { statisticService } from '../services/statisticService';
import { TransactionType, TimePeriod } from '../types/transaction';
import type { CategoryStatisticsItem, ConversionSummary } from '../types/statistics';
import { useReportingCurrency } from '../contexts/ReportingCurrencyContext';

export interface CategoryTimeseriesData extends CategoryStatisticsItem {
  category_name: string;
  date: string;
}

export const useCategoryTimeseries = (
  transaction_type?: TransactionType,
  category_name?: string,
  start_date?: string, 
  end_date?: string,
  time_period?: TimePeriod
) => {
  const { reportingCurrency: selectedReportingCurrency } = useReportingCurrency();
  const [timeseriesData, setTimeseriesData] = useState<CategoryTimeseriesData[]>([]);
  const [reportingCurrency, setReportingCurrency] = useState<string | null>(null);
  const [conversionSummary, setConversionSummary] = useState<ConversionSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchTimeseriesData = useCallback(async () => {
    setLoading(true);
    try {
      const data = await statisticService.getCategoryStatisticsTimeseries(
        transaction_type,
        category_name,
        start_date, 
        end_date,
        time_period
      );
      setReportingCurrency(data.reporting_currency);
      setConversionSummary(data.conversion_summary);
      
      // Transform data to ensure numeric values
      const transformedData = data.items.map((item) => ({
        ...item,
        category: item.category ?? item.category_name ?? 'Uncategorized',
        category_name: item.category_name ?? item.category ?? 'Uncategorized',
        date: item.date ?? '',
        expense_type: item.expense_type ?? null,
        period_amount: Number(item.period_amount) || 0,
        period_transaction_count: Number(item.period_transaction_count) || 0,
        period_percentage: Number(item.period_percentage) || 0,
        total_amount: Number(item.total_amount) || 0,
        transaction_count: Number(item.transaction_count) || 0,
        total_amount_cumulative: Number(item.total_amount_cumulative) || 0,
        total_transaction_count: Number(item.total_transaction_count) || 0,
        average_transaction_amount: Number(item.average_transaction_amount) || 0,
        yearly_amount: Number(item.yearly_amount) || 0,
        yearly_transaction_count: Number(item.yearly_transaction_count) || 0,
      }));
      
      setTimeseriesData(transformedData);
      setError(null);
    } catch (err) {
      setError('Failed to fetch category timeseries data');
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [category_name, end_date, start_date, time_period, transaction_type]);

  useEffect(() => {
    void fetchTimeseriesData();
  }, [fetchTimeseriesData, selectedReportingCurrency]);

  return {
    timeseriesData,
    reportingCurrency,
    conversionSummary,
    loading,
    error,
    refreshData: fetchTimeseriesData
  };
};
