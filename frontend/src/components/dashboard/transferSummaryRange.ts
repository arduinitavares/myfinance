import { endOfMonth, format, parse, parseISO, startOfMonth, startOfYear as getStartOfYear, subMonths } from 'date-fns';

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

export const buildTransferSummaryRange = (
  preset: Exclude<TransferSummaryPreset, 'specific_month'>,
  anchorDate: string
): TransferSummaryRange => {
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

  const startOfYear = getStartOfYear(anchor);

  return {
    startDate: toIsoDate(startOfYear),
    endDate: toIsoDate(anchor),
  };
};

export const buildSpecificMonthRange = (monthValue: string): TransferSummaryRange | null => {
  const match = /^(\d{4})-(\d{2})$/.exec(monthValue);

  if (!match) {
    return null;
  }

  const monthNumber = Number(match[2]);

  if (monthNumber < 1 || monthNumber > 12) {
    return null;
  }

  const monthDate = parse(`${monthValue}-01`, 'yyyy-MM-dd', new Date());

  return {
    startDate: toIsoDate(startOfMonth(monthDate)),
    endDate: toIsoDate(endOfMonth(monthDate)),
  };
};
