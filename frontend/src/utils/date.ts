import { format, parseISO } from 'date-fns';

export const formatDisplayDate = (value?: string | Date | null): string => {
  if (!value) {
    return '';
  }

  const parsedDate = value instanceof Date ? value : parseISO(value);

  if (Number.isNaN(parsedDate.getTime())) {
    return typeof value === 'string' ? value : '';
  }

  return format(parsedDate, 'dd/MM/yyyy');
};
