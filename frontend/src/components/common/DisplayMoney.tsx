import React from 'react';

import { resolveDisplayMoney } from '../../utils/currency';

interface DisplayMoneyProps {
  rawAmount: number;
  rawCurrency: string;
  displayAmount?: number | null;
  displayCurrency?: string | null;
  absolute?: boolean;
  showRawWhenConverted?: boolean;
  formatOptions?: Intl.NumberFormatOptions;
  primaryClassName?: string;
  unavailableClassName?: string;
  secondaryClassName?: string;
}

export const DisplayMoney: React.FC<DisplayMoneyProps> = ({
  rawAmount,
  rawCurrency,
  displayAmount,
  displayCurrency,
  absolute = false,
  showRawWhenConverted = false,
  formatOptions,
  primaryClassName,
  unavailableClassName,
  secondaryClassName,
}) => {
  const resolvedMoney = resolveDisplayMoney({
    rawAmount,
    rawCurrency,
    displayAmount,
    displayCurrency,
    absolute,
    showRawWhenConverted,
    formatOptions,
  });

  return (
    <div className="space-y-1">
      <div className={resolvedMoney.isAvailable ? primaryClassName : (unavailableClassName ?? primaryClassName)}>
        {resolvedMoney.primaryText}
      </div>
      {resolvedMoney.secondaryText ? (
        <div className={secondaryClassName}>{resolvedMoney.secondaryText}</div>
      ) : null}
    </div>
  );
};
