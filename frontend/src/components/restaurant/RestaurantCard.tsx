import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  MapPin, Phone, Clock as ClockIcon, Star, ChevronDown,
  ThumbsUp, ThumbsDown, Sparkles, Ban, ExternalLink,
} from 'lucide-react'
import type { Restaurant } from '@/types/restaurant'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { WanghongBadge } from './WanghongBadge'
import { StatsBar } from './StatsBar'

export function RestaurantCard({ restaurant: r, index = 0 }: { restaurant: Restaurant; index?: number }) {
  const [open, setOpen] = useState(false)

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.07, duration: 0.35, ease: 'easeOut' }}
    >
      <Card className="overflow-hidden hover:shadow-md transition-shadow">
        <button className="w-full text-left p-4 pb-3" onClick={() => setOpen(!open)}>
          {/* Title row */}
          <div className="flex items-start justify-between gap-2 mb-2">
            <div className="min-w-0">
              <h3 className="font-display text-base font-semibold text-foreground leading-snug truncate">{r.name}</h3>
              {r.location && (
                <p className="flex items-center gap-1 text-xs text-muted-foreground mt-0.5">
                  <MapPin size={12} /> {r.location}
                </p>
              )}
            </div>
            {r.wanghong_analysis && <WanghongBadge score={r.wanghong_analysis.score} />}
          </div>

          {/* Confidence */}
          <div className="flex items-center gap-2 mb-2.5">
            <Progress
              value={r.confidence * 100}
              className="h-1.5 flex-1"
              indicatorClassName={r.confidence > 0.7 ? 'bg-emerald-500' : r.confidence > 0.4 ? 'bg-amber-500' : 'bg-stone-400'}
            />
            <span className="text-[11px] font-mono text-muted-foreground w-8 text-right">
              {Math.round(r.confidence * 100)}%
            </span>
          </div>

          {/* Tags */}
          {r.tags.length > 0 && (
            <div className="flex flex-wrap gap-1 mb-2">
              {r.tags.slice(0, 5).map(t => (
                <Badge key={t} variant="secondary" className="text-[10px] font-normal px-1.5 py-0">{t}</Badge>
              ))}
            </div>
          )}

          {/* Features preview */}
          {r.features.length > 0 && (
            <p className="text-xs text-muted-foreground line-clamp-2 leading-relaxed">{r.features.join(' · ')}</p>
          )}

          {/* Quick pros preview when collapsed */}
          {!open && r.pros.length > 0 && (
            <div className="flex items-center gap-1.5 mt-2 text-xs text-emerald-700">
              <ThumbsUp size={12} />
              <span className="truncate">{r.pros.slice(0, 2).join('，')}</span>
            </div>
          )}

          <div className="flex justify-center pt-2">
            <ChevronDown size={16} className={`text-muted-foreground/40 transition-transform duration-200 ${open ? 'rotate-180' : ''}`} />
          </div>
        </button>

        {/* Expanded details */}
        <AnimatePresence>
          {open && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.25 }}
              className="overflow-hidden"
            >
              <div className="px-4 pb-4 pt-1 space-y-4 border-t">
                <ProsConsSection pros={r.pros} cons={r.cons} />
                <MustTrySection items={r.mustTry} />
                <BlackListSection items={r.blackList} />
                <StatsBar stats={r.stats} />
                <POISection poi={r.poi_details} />
                {r.source_notes.length > 0 && (
                  <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground pt-1">
                    <ExternalLink size={11} />
                    <span>来源: {r.source_notes.length} 篇小红书笔记</span>
                  </div>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </Card>
    </motion.div>
  )
}

function ProsConsSection({ pros, cons }: { pros: string[]; cons: string[] }) {
  if (!pros.length && !cons.length) return null
  return (
    <div className="grid grid-cols-2 gap-3">
      {pros.length > 0 && (
        <div>
          <div className="flex items-center gap-1 text-xs font-medium text-emerald-700 mb-1.5">
            <ThumbsUp size={12} /> 优点
          </div>
          {pros.map((p, i) => <p key={i} className="text-[11px] text-muted-foreground leading-relaxed">· {p}</p>)}
        </div>
      )}
      {cons.length > 0 && (
        <div>
          <div className="flex items-center gap-1 text-xs font-medium text-destructive mb-1.5">
            <ThumbsDown size={12} /> 不足
          </div>
          {cons.map((c, i) => <p key={i} className="text-[11px] text-muted-foreground leading-relaxed">· {c}</p>)}
        </div>
      )}
    </div>
  )
}

function MustTrySection({ items }: { items: Restaurant['mustTry'] }) {
  if (!items.length) return null
  return (
    <div>
      <div className="flex items-center gap-1 text-xs font-medium text-emerald-700 mb-1.5">
        <Sparkles size={12} /> 必点推荐
      </div>
      <div className="flex flex-wrap gap-1.5">
        {items.map(m => (
          <Badge key={m.name} variant="local" className="font-normal gap-1">
            {m.name}{m.reason && <span className="text-emerald-600/70">· {m.reason}</span>}
          </Badge>
        ))}
      </div>
    </div>
  )
}

function BlackListSection({ items }: { items: Restaurant['blackList'] }) {
  if (!items.length) return null
  return (
    <div>
      <div className="flex items-center gap-1 text-xs font-medium text-destructive mb-1.5">
        <Ban size={12} /> 避雷菜品
      </div>
      <div className="flex flex-wrap gap-1.5">
        {items.map(b => (
          <Badge key={b.name} variant="wanghong" className="font-normal gap-1">
            {b.name}{b.reason && <span className="text-red-500/70">· {b.reason}</span>}
          </Badge>
        ))}
      </div>
    </div>
  )
}

function POISection({ poi }: { poi: Restaurant['poi_details'] }) {
  if (!poi) return null
  const items = [
    { icon: MapPin, text: poi.address },
    { icon: Phone, text: poi.tel },
    { icon: ClockIcon, text: poi.opentime },
    { icon: Star, text: poi.rating ? `评分 ${poi.rating}` : undefined },
  ].filter(i => i.text)

  if (!items.length) return null
  return (
    <div className="rounded-lg bg-muted/50 p-3 space-y-1.5">
      {items.map(({ icon: Icon, text }, i) => (
        <p key={i} className="flex items-center gap-2 text-[11px] text-muted-foreground">
          <Icon size={12} className="shrink-0" /> {text}
        </p>
      ))}
    </div>
  )
}
