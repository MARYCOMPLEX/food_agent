import { cn } from '../../utils/cn'

interface WanghongBadgeProps {
  score: string
  size?: 'sm' | 'md'
}

const BADGE_CONFIG: Record<string, { text: string; bg: string; border: string; dot: string }> = {
  definitely_local: {
    text: '本地认证',
    bg: 'bg-emerald-50 text-emerald-800',
    border: 'border-emerald-300',
    dot: 'bg-emerald-500',
  },
  likely_local: {
    text: '可能本地',
    bg: 'bg-green-50 text-green-700',
    border: 'border-green-200',
    dot: 'bg-green-400',
  },
  unknown: {
    text: '待验证',
    bg: 'bg-stone-100 text-stone-600',
    border: 'border-stone-200',
    dot: 'bg-stone-400',
  },
  likely_wanghong: {
    text: '疑似网红',
    bg: 'bg-orange-50 text-orange-700',
    border: 'border-orange-200',
    dot: 'bg-orange-400',
  },
  definitely_wanghong: {
    text: '网红店',
    bg: 'bg-red-50 text-red-700',
    border: 'border-red-200',
    dot: 'bg-red-500',
  },
}

export function WanghongBadge({ score, size = 'sm' }: WanghongBadgeProps) {
  const config = BADGE_CONFIG[score] || BADGE_CONFIG.unknown

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 border font-medium rounded-full',
        config.bg,
        config.border,
        size === 'sm' ? 'px-2 py-0.5 text-[10px]' : 'px-2.5 py-1 text-xs'
      )}
    >
      <span className={cn('w-1.5 h-1.5 rounded-full', config.dot)} />
      {config.text}
    </span>
  )
}
