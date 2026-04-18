import { useCallback, useEffect, useState } from 'react';
import { statisticService } from '../services/statisticService';
import type {
  ConversionSummary,
  ExpenseTypeStatisticsItem,
} from '../types/statistics';
import { useReportingCurrency } from '../contexts/ReportingCurrencyContext';

type StatisticsPeriod = 'monthly' | 'yearly' | 'all_time';

export const useExpenseTypeStatistics = (initialPeriod: StatisticsPeriod = 'monthly', initialDate?: string) => {
  const { reportingCurrency: selectedReportingCurrency } = useReportingCurrency();
  const [expenseTypeStats, setExpenseTypeStats] = useState<ExpenseTypeStatisticsItem[]>([]);
  const [reportingCurrency, setReportingCurrency] = useState<string | null>(null);
  const [conversionSummary, setConversionSummary] = useState<ConversionSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [period, setPeriod] = useState<StatisticsPeriod>(initialPeriod);
  const [date, setDate] = useState<string | undefined>(initialDate);

  const fetchExpenseTypeStatistics = useCallback(
    async (
      fetchPeriod: StatisticsPeriod = period,
      fetchDate?: string
    ) => {
      setLoading(true);
      try {
        const data = await statisticService.getExpenseTypeStatistics(fetchPeriod, fetchDate);
        setReportingCurrency(data.reporting_currency);
        setConversionSummary(data.conversion_summary);
        setExpenseTypeStats(
          data.items.map((item) => ({
            ...item,
            date: item.date ?? null,
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
            categories: item.categories.map((category) => ({
              ...category,
              period_amount: Number(category.period_amount) || 0,
              period_transaction_count: Number(category.period_transaction_count) || 0,
              period_percentage: Number(category.period_percentage) || 0,
            })),
          }))
        );
        setError(null);
      } catch (err) {
        setError('Failed to fetch expense type statistics');
        console.error(err);
      } finally {
        setLoading(false);
      }
    },
    [period]
  );

  useEffect(() => {
    void fetchExpenseTypeStatistics(period, date);
  }, [date, fetchExpenseTypeStatistics, period, selectedReportingCurrency]);

  // Helper functions to extract and process the data
  const getEssentialExpenses = () => {
    return expenseTypeStats.find(stat => stat.expense_type === 'Fixed Essential') || null;
  };

  const getDiscretionaryExpenses = () => {
    return expenseTypeStats.find(stat => stat.expense_type === 'Discretionary') || null;
  };

  const getTotalExpenses = () => {
    return expenseTypeStats
      .filter(
        (stat) =>
          stat.expense_type === 'Fixed Essential' ||
          stat.expense_type === 'Discretionary'
      )
      .reduce(
      (total, stat) => total + stat.period_amount,
      0
    );
  };

  const getEssentialPercentage = () => {
    const essential = getEssentialExpenses();
    const total = getTotalExpenses();
    return total > 0 && essential ? (essential.period_amount / total) * 100 : 0;
  };

  const getDiscretionaryPercentage = () => {
    const discretionary = getDiscretionaryExpenses();
    const total = getTotalExpenses();
    return total > 0 && discretionary ? (discretionary.period_amount / total) * 100 : 0;
  };

  // Get top categories for each expense type
  const getTopEssentialCategories = (limit: number = 3) => {
    const essential = getEssentialExpenses();
    if (!essential) return [];
    
    return [...essential.categories]
      .sort((a, b) => b.period_amount - a.period_amount)
      .slice(0, limit);
  };

  const getTopDiscretionaryCategories = (limit: number = 3) => {
    const discretionary = getDiscretionaryExpenses();
    if (!discretionary) return [];
    
    return [...discretionary.categories]
      .sort((a, b) => b.period_amount - a.period_amount)
      .slice(0, limit);
  };

  return {
    expenseTypeStats,
    reportingCurrency,
    conversionSummary,
    period,
    date,
    setPeriod,
    setDate,
    essentialExpenses: getEssentialExpenses(),
    discretionaryExpenses: getDiscretionaryExpenses(),
    totalExpenses: getTotalExpenses(),
    essentialPercentage: getEssentialPercentage(),
    discretionaryPercentage: getDiscretionaryPercentage(),
    topEssentialCategories: getTopEssentialCategories(),
    topDiscretionaryCategories: getTopDiscretionaryCategories(),
    loading,
    error,
    refreshExpenseTypeStatistics: fetchExpenseTypeStatistics
  };
};
