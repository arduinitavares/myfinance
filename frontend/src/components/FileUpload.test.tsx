import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { FileUpload } from './FileUpload';
import { importService } from '../services/importService';

let mockIsAxiosError = false;

jest.mock('axios', () => ({
  __esModule: true,
  default: {
    isAxiosError: () => mockIsAxiosError,
  },
}), { virtual: true });

const mockNavigate = jest.fn();

jest.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
}), { virtual: true });

jest.mock('../services/importService', () => ({
  importService: {
    uploadFile: jest.fn(),
    startBatchFolderImport: jest.fn(),
    getBatchRun: jest.fn(),
    getLatestBatchRun: jest.fn(),
    getReview: jest.fn(),
    approve: jest.fn(),
    reject: jest.fn(),
    retry: jest.fn(),
  },
}));

jest.mock('@radix-ui/react-dialog', () => {
  const React = require('react') as typeof import('react');

  return {
    Root: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
    Trigger: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    Portal: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    Overlay: () => null,
    Content: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
    Title: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2>,
    Close: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  };
});

jest.mock('@radix-ui/react-progress', () => ({
  Root: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Indicator: () => <div />,
}));

jest.mock('@radix-ui/react-toast', () => ({
  Provider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  Root: ({ children, open }: { children: React.ReactNode; open?: boolean }) => (open ? <div>{children}</div> : null),
  Title: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Description: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Viewport: () => null,
}));

const mockedImportService = importService as jest.Mocked<typeof importService>;

describe('FileUpload', () => {
  beforeEach(() => {
    jest.resetAllMocks();
    mockIsAxiosError = false;
  });

  test('uploads pdf statements through import service and navigates to review page', async () => {
    mockedImportService.uploadFile.mockResolvedValue({
      id: 12,
      status: 'awaiting_review',
    } as never);

    render(<FileUpload onUploadSuccess={jest.fn()} />);

    fireEvent.change(screen.getByLabelText(/upload transaction file/i), {
      target: {
        files: [new File(['%PDF-1.7'], 'statement.pdf', { type: 'application/pdf' })],
      },
    });

    await waitFor(() => {
      expect(mockedImportService.uploadFile).toHaveBeenCalledTimes(1);
    });
    expect(mockedImportService.uploadFile).toHaveBeenCalledWith(expect.any(File));
    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/imports/12/review');
    });
  });

  test('allows pdf uploads with application/octet-stream when the filename is .pdf', async () => {
    mockedImportService.uploadFile.mockResolvedValue({
      id: 22,
      status: 'awaiting_review',
    } as never);

    render(<FileUpload onUploadSuccess={jest.fn()} />);

    fireEvent.change(screen.getByLabelText(/upload transaction file/i), {
      target: {
        files: [new File(['%PDF-1.7'], 'statement.pdf', { type: 'application/octet-stream' })],
      },
    });

    await waitFor(() => {
      expect(mockedImportService.uploadFile).toHaveBeenCalledTimes(1);
    });
    expect(screen.queryByText(/unsupported file type/i)).not.toBeInTheDocument();
  });

  test('routes csv uploads into import review', async () => {
    const onUploadSuccess = jest.fn();
    mockedImportService.uploadFile.mockResolvedValue({
      id: 31,
      status: 'awaiting_review',
    } as never);

    render(<FileUpload onUploadSuccess={onUploadSuccess} />);

    fireEvent.change(screen.getByLabelText(/upload transaction file/i), {
      target: {
        files: [new File(['date,description\n'], 'transactions.csv', { type: 'text/csv' })],
      },
    });

    await waitFor(() => {
      expect(mockedImportService.uploadFile).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      expect(onUploadSuccess).toHaveBeenCalledTimes(1);
      expect(mockNavigate).toHaveBeenCalledWith('/imports/31/review');
    });
  });

  test('shows pdf-specific upload errors for pdf failures', async () => {
    mockIsAxiosError = true;
    mockedImportService.uploadFile.mockRejectedValue({
      response: {
        status: 415,
        data: {
          detail: 'Unsupported media type.',
        },
      },
    } as never);

    render(<FileUpload onUploadSuccess={jest.fn()} />);

    fireEvent.change(screen.getByLabelText(/upload transaction file/i), {
      target: {
        files: [new File(['%PDF-1.7'], 'statement.pdf', { type: 'application/pdf' })],
      },
    });

    expect(await screen.findByText(/please upload a pdf statement/i)).toBeInTheDocument();
    expect(screen.queryByText(/please upload a csv file/i)).not.toBeInTheDocument();
  });

  test('keeps selected filename visible after a pdf upload error', async () => {
    mockedImportService.uploadFile.mockRejectedValue(new Error('network down') as never);

    render(<FileUpload onUploadSuccess={jest.fn()} />);

    fireEvent.change(screen.getByLabelText(/upload transaction file/i), {
      target: {
        files: [new File(['%PDF-1.7'], 'beobank-statement.pdf', { type: 'application/pdf' })],
      },
    });

    expect(await screen.findByText(/network down/i)).toBeInTheDocument();
    expect(screen.getByText(/selected file: beobank-statement\.pdf/i)).toBeInTheDocument();
  });

  test('starts bank_files import and navigates to batch results', async () => {
    mockedImportService.startBatchFolderImport.mockResolvedValue({
      id: 5,
      status: 'completed',
    } as never);

    render(<FileUpload onUploadSuccess={jest.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: /import bank_files/i }));

    await waitFor(() => {
      expect(mockedImportService.startBatchFolderImport).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/imports/batches/5');
    });
  });

  test('offers open existing when pdf upload returns a duplicate session conflict', async () => {
    mockIsAxiosError = true;
    mockedImportService.uploadFile.mockRejectedValue({
      response: {
        status: 409,
        data: {
          message: 'Import session with this file hash already exists.',
          file_hash: 'abc123',
          existing_session: {
            id: 14,
          },
        },
      },
    } as never);

    render(<FileUpload onUploadSuccess={jest.fn()} />);

    fireEvent.change(screen.getByLabelText(/upload transaction file/i), {
      target: {
        files: [new File(['%PDF-1.7'], 'statement.pdf', { type: 'application/pdf' })],
      },
    });

    expect(await screen.findByRole('button', { name: /open existing/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /open existing/i }));
    expect(mockNavigate).toHaveBeenCalledWith('/imports/14/review');
  });
});
