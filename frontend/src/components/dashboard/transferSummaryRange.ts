import { endOfMonth, format, isValid, parse, parseISO, startOfMonth, subMonths } from 'date-fns';

export type TransferSummaryPreset =
  | 'this_month'
  | 'last_month'
  | 'last_3_months'
  | 'year_to_date'
  | 'specific_month';

export interface TransferSummaryRange {
  startDate: string;
  endDate: string;
}

export const DEFAULT_TRANSFER_SUMMARY_PRESET: Exclude<TransferSummaryPreset, 'specific_month'> =
  'this_month';

const toIsoDate = (value: Date): string => format(value, 'yyyy-MM-dd');

const isValidIsoDate = (value: string): boolean => {
  const parsed = parseISO(value);
  return isValid(parsed);
};

export const buildTransferSummaryRange = (
  preset: Exclude<TransferSummaryPreset, 'specific_month'>,
  anchorDate: string
): TransferSummaryRange => {
  if (!isValidIsoDate(anchorDate)) {
    throw new Error(`Invalid anchor date: ${anchorDate}`);
  }

  const anchor = parseISO(anchorDate);

  if (preset === 'this_month') {
    return {
      startDate: toIsoDate(startOfMonth(anchor)),
      endDate: toIsoDate(anchor),
    };
  }

  if (preset === 'last_month') {
    const previousMonth = subMonths(anchor, 1);
    return {
      startDate: toIsoDate(startOfMonth(previousMonth)),
      endDate: toIsoDate(endOfMonth(previousMonth)),
    };
  }

  if (preset === 'last_3_months') {
    return {
      startDate: toIsoDate(startOfMonth(subMonths(anchor, 2))),
      endDate: toIsoDate(anchor),
    };
  }

  return {
    startDate: `${anchor.getFullYear()}-01-01`,
    endDate: toIsoDate(anchor),
  };
};

export const buildSpecificMonthRange = (monthValue: string): TransferSummaryRange | null => {
  if (!/^\d{4}-\d{2}$/.test(monthValue)) {
    return null;
  }

  const monthDate = parse(`${monthValue}-01`, 'yyyy-MM-dd', new Date());

  if (!isValid(monthDate)) {
    return null;
  }

  return {
    startDate: toIsoDate(startOfMonth(monthDate)),
    endDate: toIsoDate(endOfMonth(monthDate)),
  };
};
