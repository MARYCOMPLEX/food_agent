import { format, formatDistanceToNow, parseISO } from 'date-fns'
import { zhCN } from 'date-fns/locale'

export function formatRelativeTime(dateStr?: string | null): string {
  if (!dateStr)
    return '刚刚'
  try {
    const date = typeof dateStr === 'string' ? parseISO(dateStr) : new Date(dateStr)
    return formatDistanceToNow(date, { addSuffix: true, locale: zhCN })
  }
  catch {
    return dateStr
  }
}

export function formatDateTime(dateStr?: string | null, pattern = 'yyyy-MM-dd HH:mm'): string {
  if (!dateStr)
    return '-'
  try {
    const date = typeof dateStr === 'string' ? parseISO(dateStr) : new Date(dateStr)
    return format(date, pattern, { locale: zhCN })
  }
  catch {
    return dateStr
  }
}
