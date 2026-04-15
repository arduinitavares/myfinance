import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { TransferSummary } from './TransferSummary';
import { statisticService } from '../../services/statisticService';

jest.mock('../../services/statisticService', () => ({
  statisticService: {
    getTransferSummary: jest.fn(),
  },
}));

const mockedGetTransferSummary = statisticService.getTransferSummary as jest.MockedFunction<
  typeof statisticService.getTransferSummary
>;

describe('TransferSummary', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('shows loading state while transfer summary is being fetched', async () => {
    mockedGetTransferSummary.mockResolvedValueOnce({
      start_date: '2026-03-01',
      end_date: '2026-03-31',
      items: [
        {
          subtype: 'Internal Transfer',
          transaction_count: 3,
          total_outgoing_eur: 1200,
          total_incoming_eur: 950,
        },
      ],
    });

    render(<TransferSummary />);

    expect(screen.getByText(/loading\.\.\./i)).toBeInTheDocument();

    expect(await screen.findByText('Transfers & Settlements')).toBeInTheDocument();
  });

  test('renders transfer summary rows', async () => {
    mockedGetTransferSummary.mockResolvedValueOnce({
      start_date: '2026-03-01',
      end_date: '2026-03-31',
      items: [
        {
          subtype: 'Internal Transfer',
          transaction_count: 3,
          total_outgoing_eur: 1200,
          total_incoming_eur: 950,
        },
        {
          subtype: 'Credit Card Settlement',
          transaction_count: 2,
          total_outgoing_eur: 500,
          total_incoming_eur: 0,
        },
      ],
    });

    render(<TransferSummary />);

    expect(await screen.findByText('Transfers & Settlements')).toBeInTheDocument();
    expect(screen.getByText('Internal Transfer')).toBeInTheDocument();
    expect(screen.getByText('Credit Card Settlement')).toBeInTheDocument();
    expect(screen.getByText('€1,200')).toBeInTheDocument();
    expect(screen.getByText('€950')).toBeInTheDocument();
    expect(screen.getByText('€500')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
  });

  test('shows an empty state when no transfer rows are returned', async () => {
    mockedGetTransferSummary.mockResolvedValueOnce({
      start_date: '2026-03-01',
      end_date: '2026-03-31',
      items: [],
    });

    render(<TransferSummary />);

    expect(await screen.findByText(/no transfer summary data available/i)).toBeInTheDocument();
  });

  test('shows an error state when the fetch fails', async () => {
    const consoleSpy = jest.spyOn(console, 'error').mockImplementation(() => undefined);
    mockedGetTransferSummary.mockRejectedValueOnce(new Error('network failed'));

    render(<TransferSummary />);

    expect(await screen.findByText(/failed to load transfer summary/i)).toBeInTheDocument();
    await waitFor(() => expect(mockedGetTransferSummary).toHaveBeenCalledTimes(1));

    consoleSpy.mockRestore();
  });

  test('boots with backend defaults, then requests last month with explicit dates', async () => {
    mockedGetTransferSummary
      .mockResolvedValueOnce({
        start_date: '2026-04-01',
        end_date: '2026-04-10',
        items: [],
      })
      .mockResolvedValueOnce({
        start_date: '2026-03-01',
        end_date: '2026-03-31',
        items: [],
      });

    render(<TransferSummary />);

    const presetSelect = await screen.findByLabelText(/transfer summary preset/i);
    expect(presetSelect).toHaveValue('this_month');
    expect(mockedGetTransferSummary).toHaveBeenNthCalledWith(1);

    fireEvent.change(presetSelect, { target: { value: 'last_month' } });

    await waitFor(() => {
      expect(mockedGetTransferSummary).toHaveBeenNthCalledWith(2, '2026-03-01', '2026-03-31');
    });
  });

  test('shows the month picker for specific month and waits for a valid month before fetching', async () => {
    mockedGetTransferSummary
      .mockResolvedValueOnce({
        start_date: '2026-04-01',
        end_date: '2026-04-10',
        items: [],
      })
      .mockResolvedValueOnce({
        start_date: '2026-02-01',
        end_date: '2026-02-28',
        items: [],
      });

    render(<TransferSummary />);

    const presetSelect = await screen.findByLabelText(/transfer summary preset/i);
    fireEvent.change(presetSelect, { target: { value: 'specific_month' } });

    expect(screen.getByLabelText(/transfer summary month/i)).toBeInTheDocument();
    expect(mockedGetTransferSummary).toHaveBeenCalledTimes(1);

    fireEvent.change(screen.getByLabelText(/transfer summary month/i), {
      target: { value: '2026-02' },
    });

    await waitFor(() => {
      expect(mockedGetTransferSummary).toHaveBeenNthCalledWith(2, '2026-02-01', '2026-02-28');
    });
  });
});
