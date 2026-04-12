import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

import { TransactionFilters } from './TransactionFilters';

jest.mock('@radix-ui/react-select', () => {
  const React = require('react') as typeof import('react');

  const SelectContext = React.createContext<{
    value: string;
    onValueChange: (value: string) => void;
  } | null>(null);

  const Root = ({ value, onValueChange, children }: {
    value: string;
    onValueChange: (value: string) => void;
    children: React.ReactNode;
  }) => (
    <SelectContext.Provider value={{ value, onValueChange }}>
      <div>{children}</div>
    </SelectContext.Provider>
  );

  const Trigger = ({ children }: { children: React.ReactNode }) => <button type="button">{children}</button>;
  const Value = ({ placeholder }: { placeholder?: string }) => {
    const context = React.useContext(SelectContext);
    return <span>{context?.value || placeholder}</span>;
  };
  const Portal = ({ children }: { children: React.ReactNode }) => <>{children}</>;
  const Content = ({ children, ...props }: React.SelectHTMLAttributes<HTMLSelectElement>) => {
    const context = React.useContext(SelectContext);
    return (
      <select
        aria-label={props['aria-label']}
        value={context?.value ?? ''}
        onChange={(event) => context?.onValueChange(event.target.value)}
      >
        {children}
      </select>
    );
  };
  const Viewport = ({ children }: { children: React.ReactNode }) => <>{children}</>;
  const Group = ({ children }: { children: React.ReactNode }) => <>{children}</>;
  const Label = ({ children }: { children: React.ReactNode }) => <>{children}</>;
  const Item = ({ children, value }: { children: React.ReactNode; value: string }) => (
    <option value={value}>{children}</option>
  );
  const ItemText = ({ children }: { children: React.ReactNode }) => <>{children}</>;

  return {
    Root,
    Trigger,
    Value,
    Portal,
    Content,
    Viewport,
    Group,
    Label,
    Item,
    ItemText,
  };
});

describe('TransactionFilters', () => {
  test('lets user filter classified vs unclassified transactions', () => {
    const onClassificationStatusFilter = jest.fn();

    render(
      <TransactionFilters
        searchTerm=""
        categoryFilter="all"
        classificationStatus="all"
        dateRange={{ start: '', end: '' }}
        onSearchChange={() => {}}
        onCategoryFilter={() => {}}
        onClassificationStatusFilter={onClassificationStatusFilter}
        onDateRangeChange={() => {}}
        onClearFilters={() => {}}
      />
    );

    fireEvent.change(screen.getByLabelText('classification-status-filter'), {
      target: { value: 'unclassified' },
    });

    expect(onClassificationStatusFilter).toHaveBeenCalledWith('unclassified');
    expect(screen.getByText(/unclassified only/i)).toBeInTheDocument();
  });
});
