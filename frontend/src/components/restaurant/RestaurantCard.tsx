import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import type { Restaurant } from '../../types/restaurant'
import { WanghongBadge } from './WanghongBadge'
import { StatsBar } from './StatsBar'
import { cn } from '../../utils/cn'

interface RestaurantCardProps {
  restaurant: Restaurant
  index?: number
}

export function RestaurantCard({ restaurant: r, index = 0 }: RestaurantCardProps) {
  const [expanded, setExpanded] = useState(false)

  return (
    <motion.div
      initial={{ opacity: 0, y: 24 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.08, duration: 0.4, ease: [0.25, 0.46, 0.45, 0.94] }}
      className="bg-white rounded-2xl border border-border shadow-sm overflow-hidden"
    >
      {/* Header */}
      <div
        className="px-4 pt-4 pb-3 cursor-pointer active:bg-stone-50 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-start justify-between gap-2 mb-2">
          <div className="flex-1 min-w-0">
            <h3 className="font-display text-base font-bold text-ink leading-tight truncate">
              {r.name}
            </h3>
            {r.location && (
              <p className="text-xs text-muted mt-0.5 truncate">📍 {r.location}</p>
            )}
          </div>
          {r.wanghong_analysis && (
            <WanghongBadge score={r.wanghong_analysis.score} />
          )}
        </div>

        {/* Confidence bar */}
        <div className="flex items-center gap-2 mb-2">
          <div className="flex-1 h-1.5 bg-stone-100 rounded-full overflow-hidden">
            <motion.div
              initial={{ width: 0 }}
              animate={{ width: `${r.confidence * 100}%` }}
              transition={{ delay: index * 0.08 + 0.3, duration: 0.6 }}
              className={cn(
                'h-full rounded-full',
                r.confidence > 0.7 ? 'bg-emerald-400' : r.confidence > 0.4 ? 'bg-amber-400' : 'bg-stone-300'
              )}
            />
          </div>
          <span className="text-[10px] font-mono text-muted">{Math.round(r.confidence * 100)}%</span>
        </div>

        {/* Tags */}
        {r.tags.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-2">
            {r.tags.slice(0, 4).map((tag) => (
              <span key={tag} className="px-1.5 py-0.5 text-[10px] bg-cream-dark text-muted rounded">
                {tag}
              </span>
            ))}
          </div>
        )}

        {/* Collapsed preview */}
        {r.features.length > 0 && (
          <p className="text-xs text-ink-light leading-relaxed line-clamp-2">
            {r.features.join(' · ')}
          </p>
        )}
        {!expanded && r.pros.length > 0 && (
          <div className="flex items-center gap-1.5 mt-1.5">
            <span className="text-[10px] text-emerald-600">👍</span>
            <p className="text-[11px] text-emerald-700 truncate">{r.pros.slice(0, 2).join('，')}</p>
          </div>
        )}

        {/* Expand indicator */}
        <div className="flex justify-center mt-2">
          <motion.span
            animate={{ rotate: expanded ? 180 : 0 }}
            className="text-xs text-muted/50"
          >
            ▼
          </motion.span>
        </div>
      </div>

      {/* Expanded content */}
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.3 }}
            className="overflow-hidden"
          >
            <div className="px-4 pb-4 space-y-3 border-t border-border pt-3">
              {/* Pros & Cons */}
              {(r.pros.length > 0 || r.cons.length > 0) && (
                <div className="grid grid-cols-2 gap-2">
                  {r.pros.length > 0 && (
                    <div>
                      <p className="text-[10px] font-medium text-emerald-600 mb-1">优点</p>
                      {r.pros.map((p, i) => (
                        <p key={i} className="text-[11px] text-ink-light leading-relaxed">✓ {p}</p>
                      ))}
                    </div>
                  )}
                  {r.cons.length > 0 && (
                    <div>
                      <p className="text-[10px] font-medium text-red-500 mb-1">不足</p>
                      {r.cons.map((c, i) => (
                        <p key={i} className="text-[11px] text-ink-light leading-relaxed">✗ {c}</p>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Must try */}
              {r.mustTry.length > 0 && (
                <div>
                  <p className="text-[10px] font-medium text-emerald-600 mb-1.5">必点推荐</p>
                  <div className="flex flex-wrap gap-1.5">
                    {r.mustTry.map((item) => (
                      <span key={item.name} className="inline-flex items-center gap-1 px-2 py-1 bg-emerald-50 text-emerald-700 text-[11px] rounded-lg border border-emerald-100">
                        🌟 {item.name}
                        {item.reason && <span className="text-emerald-500">· {item.reason}</span>}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Blacklist */}
              {r.blackList.length > 0 && (
                <div>
                  <p className="text-[10px] font-medium text-red-500 mb-1.5">避雷菜品</p>
                  <div className="flex flex-wrap gap-1.5">
                    {r.blackList.map((item) => (
                      <span key={item.name} className="inline-flex items-center gap-1 px-2 py-1 bg-red-50 text-red-600 text-[11px] rounded-lg border border-red-100">
                        ⚠ {item.name}
                        {item.reason && <span className="text-red-400">· {item.reason}</span>}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Stats */}
              <StatsBar stats={r.stats} />

              {/* POI Details */}
              {r.poi_details && (
                <div className="bg-cream/60 rounded-xl p-3 space-y-1.5">
                  {r.poi_details.address && (
                    <p className="text-[11px] text-ink-light">📍 {r.poi_details.address}</p>
                  )}
                  {r.poi_details.tel && (
                    <p className="text-[11px] text-ink-light">📞 {r.poi_details.tel}</p>
                  )}
                  {r.poi_details.opentime && (
                    <p className="text-[11px] text-ink-light">🕐 {r.poi_details.opentime}</p>
                  )}
                  {r.poi_details.rating && (
                    <p className="text-[11px] text-ink-light">⭐ 评分 {r.poi_details.rating}</p>
                  )}
                </div>
              )}

              {/* Source notes */}
              {r.source_notes.length > 0 && (
                <p className="text-[10px] text-muted">
                  来源: {r.source_notes.length} 篇小红书笔记
                </p>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}
