export function formatDate(dateStr: string): string {
  const date = new Date(dateStr)
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  const minutes = Math.floor(diff / 60000)
  const hours = Math.floor(diff / 3600000)
  const days = Math.floor(diff / 86400000)

  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes}分钟前`
  if (hours < 24) return `${hours}小时前`
  if (days < 7) return `${days}天前`

  const month = date.getMonth() + 1
  const day = date.getDate()
  return `${month}月${day}日`
}

export function formatConfidence(confidence: number): string {
  return `${Math.round(confidence * 100)}%`
}

export function getWanghongLabel(score: string): { text: string; color: string } {
  switch (score) {
    case 'definitely_local':
      return { text: '本地认证', color: 'bg-emerald-100 text-emerald-700' }
    case 'likely_local':
      return { text: '可能本地', color: 'bg-green-100 text-green-700' }
    case 'unknown':
      return { text: '待验证', color: 'bg-gray-100 text-gray-600' }
    case 'likely_wanghong':
      return { text: '疑似网红', color: 'bg-orange-100 text-orange-700' }
    case 'definitely_wanghong':
      return { text: '网红店', color: 'bg-red-100 text-red-700' }
    default:
      return { text: '未知', color: 'bg-gray-100 text-gray-600' }
  }
}
