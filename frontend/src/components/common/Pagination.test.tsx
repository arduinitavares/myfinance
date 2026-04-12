import { fireEvent, render, screen } from '@testing-library/react';

import { Pagination } from './Pagination';

describe('Pagination', () => {
  test('simple mode shows only back and next controls', () => {
    const onPageChange = jest.fn();

    render(
      <Pagination
        currentPage={6}
        totalPages={11}
        onPageChange={onPageChange}
        mode="simple"
      />
    );

    expect(screen.getByText(/page/i)).toHaveTextContent('Page 6 of 11');
    expect(screen.getByRole('button', { name: /back/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /next/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '1' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '11' })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /back/i }));
    fireEvent.click(screen.getByRole('button', { name: /next/i }));

    expect(onPageChange).toHaveBeenNthCalledWith(1, 5);
    expect(onPageChange).toHaveBeenNthCalledWith(2, 7);
  });
});
