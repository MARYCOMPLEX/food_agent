export function formatTrustScore(score?: number): string {
  if (score === undefined || score === null)
    return 'N/A'
  return Number(score).toFixed(1)
}

export function formatPrice(price?: string): string {
  if (!price)
    return '¥¥'
  return price
}

export function truncateText(text: string, maxLength = 60): string {
  if (!text)
    return ''
  if (text.length <= maxLength)
    return text
  return `${text.slice(0, maxLength)}...`
}

export function formatDuration(ms: number): string {
  if (ms < 1000)
    return `${ms}ms`
  const sec = (ms / 1000).toFixed(1)
  return `${sec}s`
}
