import type { ShopStats } from '../../types/restaurant'
import { cn } from '../../utils/cn'

const STAT_CONFIG = [
  { key: 'flavor' as const, label: '口味', icon: '🔥', color: 'bg-orange-400' },
  { key: 'cost' as const, label: '性价比', icon: '💰', color: 'bg-emerald-400' },
  { key: 'wait' as const, label: '等候', icon: '⏱', color: 'bg-amber-400' },
  { key: 'env' as const, label: '环境', icon: '🏠', color: 'bg-sky-400' },
]

function getBarWidth(value: string): number {
  if (!value) return 0
  const v = value.toUpperCase()
  if (v === 'A' || v === '$' || v.includes('5MIN') || v === 'QUIET') return 95
  if (v === 'B' || v === '$$' || v.includes('15MIN') || v === 'CASUAL') return 65
  if (v === 'C' || v === '$$$' || v.includes('30MIN') || v === 'NOISY') return 35
  return 50
}

export function StatsBar({ stats }: { stats: ShopStats }) {
  const hasAny = Object.values(stats).some(v => v)
  if (!hasAny) return null

  return (
    <div className="space-y-2">
      {STAT_CONFIG.map(({ key, label, icon, color }) => {
        const value = stats[key]
        if (!value) return null
        const width = getBarWidth(value)

        return (
          <div key={key} className="flex items-center gap-2 text-xs">
            <span className="w-4 text-center">{icon}</span>
            <span className="w-10 text-muted shrink-0">{label}</span>
            <div className="flex-1 h-2 bg-stone-100 rounded-full overflow-hidden">
              <div
                className={cn('h-full rounded-full transition-all duration-700', color)}
                style={{ width: `${width}%` }}
              />
            </div>
            <span className="w-12 text-right text-muted font-mono text-[10px]">{value}</span>
          </div>
        )
      })}
    </div>
  )
}
