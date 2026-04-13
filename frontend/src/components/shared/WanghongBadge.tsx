import { ShieldCheck, ShieldAlert, ShieldQuestion, AlertTriangle, XCircle } from 'lucide-react'
import { Badge } from '@/components/ui/badge'

const CONFIG: Record<string, { text: string; variant: 'local' | 'wanghong' | 'warning' | 'muted'; icon: typeof ShieldCheck }> = {
  definitely_local: { text: '本地认证', variant: 'local', icon: ShieldCheck },
  likely_local: { text: '可能本地', variant: 'local', icon: ShieldCheck },
  unknown: { text: '待验证', variant: 'muted', icon: ShieldQuestion },
  likely_wanghong: { text: '疑似网红', variant: 'warning', icon: AlertTriangle },
  definitely_wanghong: { text: '网红店', variant: 'wanghong', icon: XCircle },
}

export function WanghongBadge({ score }: { score: string }) {
  const config = CONFIG[score] ?? CONFIG.unknown
  const Icon = config.icon

  return (
    <Badge variant={config.variant} className="gap-1">
      <Icon size={12} />
      {config.text}
    </Badge>
  )
}
