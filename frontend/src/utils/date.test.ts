import { formatDisplayDate } from './date';

describe('formatDisplayDate', () => {
  test('formats date-only and timestamp strings as dd/MM/yyyy', () => {
    expect(formatDisplayDate('2026-01-16')).toBe('16/01/2026');
    expect(formatDisplayDate('2026-03-27T10:15:00Z')).toBe('27/03/2026');
  });

  test('falls back to original value when date cannot be parsed', () => {
    expect(formatDisplayDate('not-a-date')).toBe('not-a-date');
  });
});
