import type {
  ResearchEvidenceItemV1,
  ResearchGapViewV1,
  ResearchJsonValue,
  ResearchPlanStepViewV1,
  ResearchRunStatusV1,
} from '../../../../shared/contracts/research'

export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined) return '0'
  return new Intl.NumberFormat('zh-CN', { notation: value > 9999 ? 'compact' : 'standard', maximumFractionDigits: 1 }).format(value)
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return '时间未知'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '时间未知'
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

export function statusLabel(status: ResearchRunStatusV1 | undefined | null): string {
  const labels: Record<ResearchRunStatusV1, string> = {
    queued: '排队中',
    running: '调查中',
    succeeded: '已完成',
    partial: '部分完成',
    failed: '失败',
    cancelled: '已取消',
    blocked: '等待补充',
  }
  return status ? labels[status] : '等待数据'
}

export function stepStatusLabel(status: ResearchPlanStepViewV1['status']): string {
  const labels: Record<NonNullable<ResearchPlanStepViewV1['status']>, string> = {
    pending: '待执行',
    running: '执行中',
    succeeded: '已完成',
    partial: '部分完成',
    failed: '失败',
    skipped: '已跳过',
  }
  return status ? labels[status] : '待执行'
}

export function gapSeverityLabel(severity: ResearchGapViewV1['severity']): string {
  return severity === 'error' ? '高影响' : severity === 'warning' ? '需关注' : '提示'
}

export function sourceLabel(source: string | undefined | null): string {
  if (!source) return '未知来源'
  const labels: Record<string, string> = {
    xhs: '小红书',
    xhs_pc: '小红书',
    dianping: '大众点评',
    agent: 'Agent 判断',
    synthesis: '综合研判',
  }
  return labels[source.toLowerCase()] ?? source
}

export function imageUrl(value: ResearchJsonValue | undefined): string | null {
  if (typeof value === 'string') return value
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const record = value as Record<string, ResearchJsonValue>
  const candidate = record.url ?? record.imageUrl ?? record.src
  return typeof candidate === 'string' ? candidate : null
}

export function dishLabel(value: ResearchJsonValue | undefined): string | null {
  if (typeof value === 'string') return value
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const record = value as Record<string, ResearchJsonValue>
  const candidate = record.name ?? record.title ?? record.dishName
  return typeof candidate === 'string' ? candidate : null
}

export function evidenceSource(evidence: ResearchEvidenceItemV1): string {
  return evidence.provenance?.[0]?.source || evidence.source || '未知来源'
}

export function gapActionLabel(gap: ResearchGapViewV1): string {
  if (gap.status === 'retrying') return '重试中'
  if (gap.status === 'resolved') return '已补齐'
  if (gap.retryable) return '重试'
  return '查看缺口'
}
