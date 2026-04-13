import { Flame, Coins, Timer, Armchair } from 'lucide-react'
import type { ShopStats } from '@/types/restaurant'
import { Progress } from '@/components/ui/progress'

const STATS = [
  { key: 'flavor' as const, label: '口味', icon: Flame, color: 'bg-orange-500' },
  { key: 'cost' as const, label: '性价比', icon: Coins, color: 'bg-emerald-500' },
  { key: 'wait' as const, label: '等候', icon: Timer, color: 'bg-amber-500' },
  { key: 'env' as const, label: '环境', icon: Armchair, color: 'bg-sky-500' },
] as const

function toPercent(v: string): number {
  const s = v.toUpperCase()
  if (s === 'A' || s === '$' || s.includes('5MIN') || s === 'QUIET') return 90
  if (s === 'B' || s === '$$' || s.includes('15MIN') || s === 'CASUAL') return 60
  if (s === 'C' || s === '$$$' || s.includes('30MIN') || s === 'NOISY') return 35
  return 50
}

export function StatsBar({ stats }: { stats: ShopStats }) {
  const hasAny = Object.values(stats).some(Boolean)
  if (!hasAny) return null

  return (
    <div className="space-y-2.5">
      {STATS.map(({ key, label, icon: Icon, color }) => {
        const value = stats[key]
        if (!value) return null
        return (
          <div key={key} className="flex items-center gap-2.5 text-xs">
            <Icon size={14} className="text-muted-foreground shrink-0" />
            <span className="w-12 text-muted-foreground shrink-0">{label}</span>
            <Progress value={toPercent(value)} className="flex-1 h-1.5" indicatorClassName={color} />
            <span className="w-12 text-right text-muted-foreground font-mono text-[11px]">{value}</span>
          </div>
        )
      })}
    </div>
  )
}
