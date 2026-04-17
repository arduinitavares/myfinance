import {
  DEFAULT_TRANSFER_SUMMARY_PRESET,
  buildSpecificMonthRange,
  buildTransferSummaryRange,
} from './transferSummaryRange';

describe('transferSummaryRange', () => {
  test('uses the backend anchor date for open-ended presets', () => {
    expect(DEFAULT_TRANSFER_SUMMARY_PRESET).toBe('this_month');

    expect(buildTransferSummaryRange('this_month', '2026-04-10')).toEqual({
      startDate: '2026-04-01',
      endDate: '2026-04-10',
    });

    expect(buildTransferSummaryRange('last_month', '2026-04-10')).toEqual({
      startDate: '2026-03-01',
      endDate: '2026-03-31',
    });

    expect(buildTransferSummaryRange('last_3_months', '2026-04-10')).toEqual({
      startDate: '2026-02-01',
      endDate: '2026-04-10',
    });

    expect(buildTransferSummaryRange('year_to_date', '2026-04-10')).toEqual({
      startDate: '2026-01-01',
      endDate: '2026-04-10',
    });
  });

  test('builds a full calendar month for specific month selection', () => {
    expect(buildSpecificMonthRange('2026-02')).toEqual({
      startDate: '2026-02-01',
      endDate: '2026-02-28',
    });
  });

  test('builds leap-year February for specific month selection', () => {
    expect(buildSpecificMonthRange('2024-02')).toEqual({
      startDate: '2024-02-01',
      endDate: '2024-02-29',
    });
  });

  test('builds last month across year boundary', () => {
    expect(buildTransferSummaryRange('last_month', '2026-01-15')).toEqual({
      startDate: '2025-12-01',
      endDate: '2025-12-31',
    });
  });

  test('returns null for missing or invalid specific month input', () => {
    expect(buildSpecificMonthRange('')).toBeNull();
    expect(buildSpecificMonthRange('2026-2')).toBeNull();
    expect(buildSpecificMonthRange('2026-00')).toBeNull();
    expect(buildSpecificMonthRange('2026-13')).toBeNull();
    expect(buildSpecificMonthRange('wat')).toBeNull();
  });
});
