export interface ResolveDisplayMoneyOptions {
  rawAmount: number;
  rawCurrency: string;
  displayAmount?: number | null;
  displayCurrency?: string | null;
  displayIsAvailable?: boolean | null;
  displayUnavailableReason?: string | null;
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
): string => {
  try {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
      ...options,
    }).format(amount);
  } catch (error) {
    if (!(error instanceof RangeError)) {
      throw error;
    }

    const { currency: _currency, style: _style, ...numericOptions } = options;
    const formattedAmount = new Intl.NumberFormat('en-US', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
      ...numericOptions,
    }).format(Math.abs(amount));
    const sign = amount < 0 ? '-' : '';

    return `${sign}${currency}\u00a0${formattedAmount}`;
  }
};

export const resolveDisplayMoney = ({
  rawAmount,
  rawCurrency,
  displayAmount,
  displayCurrency,
  displayIsAvailable,
  absolute = false,
  showRawWhenConverted = false,
  formatOptions = {},
}: ResolveDisplayMoneyOptions): ResolvedDisplayMoney => {
  const normalizeAmount = (amount: number) => (absolute ? Math.abs(amount) : amount);
  const rawText = formatMoney(normalizeAmount(rawAmount), rawCurrency, formatOptions);

  if (displayIsAvailable === false) {
    return {
      isAvailable: false,
      primaryText: 'FX unavailable',
      secondaryText: `Raw ${rawText}`,
    };
  }

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
