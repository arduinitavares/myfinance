import React from 'react';
import { render, screen } from '@testing-library/react';

import { DisplayMoney } from './DisplayMoney';

describe('DisplayMoney', () => {
  test('shows raw context when the backend marks FX as unavailable', () => {
    render(
      <DisplayMoney
        rawAmount={-42}
        rawCurrency="NEXO"
        displayAmount={null}
        displayCurrency="USD"
        displayIsAvailable={false}
        displayUnavailableReason="unsupported_currency"
      />
    );

    expect(screen.getByText('FX unavailable')).toBeInTheDocument();
    expect(screen.getByText(/Raw -NEXO\s42\.00/)).toBeInTheDocument();
  });
});
