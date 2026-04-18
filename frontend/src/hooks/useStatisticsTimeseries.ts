import { useState, useEffect, useCallback } from 'react';
import { statisticService } from '../services/statisticService';
import { TimePeriod } from '../types/transaction';
import type {
    ConversionSummary,
    FinancialStatisticsTimeseriesItem,
} from '../types/statistics';
import { useReportingCurrency } from '../contexts/ReportingCurrencyContext';

export const useStatisticsTimeseries = (start_date?: string, end_date?: string, time_period?: TimePeriod) => {
    const { reportingCurrency: selectedReportingCurrency } = useReportingCurrency();
    const [timeseriesData, setTimeseriesData] = useState<FinancialStatisticsTimeseriesItem[]>([]);
    const [reportingCurrency, setReportingCurrency] = useState<string | null>(null);
    const [conversionSummary, setConversionSummary] = useState<ConversionSummary | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const fetchTimeseriesData = useCallback(async () => {
        setLoading(true);
        try {
            const data = await statisticService.getStatisticsTimeseries(start_date, end_date, time_period);
            setReportingCurrency(data.reporting_currency);
            setConversionSummary(data.conversion_summary);
            const transformedData = data.items.map((item) => ({
                date: item.date,
                period_income: Number(item.period_income) || 0,
                period_expenses: Number(item.period_expenses) || 0,
                period_net_savings: Number(item.period_net_savings) || 0,
                savings_rate: Number(item.savings_rate) || 0,
                total_income: Number(item.total_income) || 0,
                total_expenses: Number(item.total_expenses) || 0,
                total_net_savings: Number(item.total_net_savings) || 0,
                income_count: Number(item.income_count) || 0,
                expense_count: Number(item.expense_count) || 0,
                average_income: Number(item.average_income) || 0,
                average_expense: Number(item.average_expense) || 0,
                yearly_income: Number(item.yearly_income) || 0,
                yearly_expenses: Number(item.yearly_expenses) || 0,
                period: item.period,
            }));
            setTimeseriesData(transformedData);
            setError(null);
        } catch (err) {
            setError('Failed to fetch timeseries data');
            console.error(err);
        } finally {
            setLoading(false);
        }
    }, [end_date, start_date, time_period]);

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
