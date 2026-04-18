export interface ResolveDisplayMoneyOptions {
  rawAmount: number;
  rawCurrency: string;
  displayAmount?: number | null;
  displayCurrency?: string | null;
  absolute?: boolean;
  showRawWhenConverted?: boolean;
  formatOptions?: Intl.NumberFormatOptions;
}

export interface ResolvedDisplayMoney {
  isAvailable: boolean;
  primaryText: string;
  secondaryText?: string;
}

// Persisted dashboard aggregates are stored in EUR until those endpoints become reporting-currency aware.
export const PERSISTED_STATISTICS_CURRENCY = 'EUR';

export const formatMoney = (
  amount: number,
  currency: string,
  options: Intl.NumberFormatOptions = {}
): string =>
  new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
    ...options,
  }).format(amount);

export const resolveDisplayMoney = ({
  rawAmount,
  rawCurrency,
  displayAmount,
  displayCurrency,
  absolute = false,
  showRawWhenConverted = false,
  formatOptions = {},
}: ResolveDisplayMoneyOptions): ResolvedDisplayMoney => {
  const normalizeAmount = (amount: number) => (absolute ? Math.abs(amount) : amount);
  const rawText = formatMoney(normalizeAmount(rawAmount), rawCurrency, formatOptions);

  if (displayAmount === null || displayAmount === undefined || !displayCurrency) {
    return {
      isAvailable: false,
      primaryText: 'FX unavailable',
      secondaryText: `Raw ${rawText}`,
    };
  }

  const displayText = formatMoney(normalizeAmount(displayAmount), displayCurrency, formatOptions);
  const shouldShowRaw = showRawWhenConverted && rawCurrency !== displayCurrency;

  return {
    isAvailable: true,
    primaryText: displayText,
    secondaryText: shouldShowRaw ? `Raw ${rawText}` : undefined,
  };
};
