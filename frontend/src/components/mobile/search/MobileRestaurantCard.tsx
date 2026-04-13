import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  MapPin, Phone, Clock as ClockIcon, Star, ChevronDown,
  ThumbsUp, ThumbsDown, Sparkles, Ban, ImageOff,
} from 'lucide-react'
import type { Restaurant } from '@/types/restaurant'
import { Badge } from '@/components/ui/badge'
import { WanghongBadge } from '@/components/restaurant/WanghongBadge'
import { StatsBar } from '@/components/restaurant/StatsBar'

interface MobileRestaurantCardProps {
  restaurant: Restaurant
  index?: number
}

function pickCover(r: Restaurant): string | null {
  const poiPhoto = r.poi_details?.photos?.[0]
  if (poiPhoto) return poiPhoto
  const mustTryImg = r.mustTry.find((m) => m.img)?.img
  return mustTryImg ?? null
}

function scoreRingColor(confidence: number): string {
  if (confidence > 0.7) return 'text-emerald-500'
  if (confidence > 0.4) return 'text-amber-500'
  return 'text-stone-400'
}

function ScoreRing({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  const r = 18
  const c = 2 * Math.PI * r
  const offset = c * (1 - value)
  return (
    <div className="relative w-11 h-11 grid place-items-center">
      <svg className="absolute inset-0" viewBox="0 0 44 44">
        <circle cx="22" cy="22" r={r} fill="rgba(0,0,0,0.55)" />
        <circle
          cx="22" cy="22" r={r}
          fill="none"
          stroke="rgba(255,255,255,0.22)"
          strokeWidth="3"
        />
        <circle
          cx="22" cy="22" r={r}
          fill="none"
          strokeLinecap="round"
          strokeWidth="3"
          strokeDasharray={c}
          strokeDashoffset={offset}
          transform="rotate(-90 22 22)"
          className={scoreRingColor(value)}
          stroke="currentColor"
        />
      </svg>
      <span className="relative text-[11px] font-semibold text-white tabular-nums">
        {pct}
      </span>
    </div>
  )
}

function CoverImage({ src, name }: { src: string | null; name: string }) {
  if (!src) {
    return (
      <div className="aspect-[16/10] w-full bg-bg-elev grid place-items-center text-muted-foreground">
        <ImageOff size={28} strokeWidth={1.5} />
      </div>
    )
  }
  return (
    <img
      src={src}
      alt={name}
      loading="lazy"
      className="aspect-[16/10] w-full object-cover bg-bg-elev"
    />
  )
}

export function MobileRestaurantCard({ restaurant: r, index = 0 }: MobileRestaurantCardProps) {
  const [open, setOpen] = useState(false)
  const cover = pickCover(r)

  return (
    <motion.article
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.06, duration: 0.32, ease: 'easeOut' }}
      className="rounded-[20px] overflow-hidden bg-background border border-border"
    >
      {/* Hero image with overlays */}
      <div className="relative">
        <CoverImage src={cover} name={r.name} />

        {/* Top-left: index + wanghong */}
        <div className="absolute top-2.5 left-2.5 flex items-center gap-1.5">
          <span className="px-2 py-0.5 rounded-full bg-black/55 backdrop-blur text-white text-[11px] font-semibold tabular-nums">
            #{index + 1}
          </span>
          {r.wanghong_analysis && (
            <div className="[&>*]:shadow-sm">
              <WanghongBadge score={r.wanghong_analysis.score} />
            </div>
          )}
        </div>

        {/* Top-right: confidence ring */}
        <div className="absolute top-2 right-2">
          <ScoreRing value={r.confidence} />
        </div>

        {/* Bottom gradient with name */}
        <div className="absolute inset-x-0 bottom-0 px-3.5 pt-10 pb-3 bg-gradient-to-t from-black/70 via-black/30 to-transparent">
          <h3 className="font-display text-[19px] font-semibold text-white leading-tight drop-shadow-sm">
            {r.name}
          </h3>
          {r.location && (
            <p className="flex items-center gap-1 text-[12px] text-white/85 mt-0.5">
              <MapPin size={11} strokeWidth={2} /> {r.location}
            </p>
          )}
        </div>
      </div>

      {/* Body */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full text-left px-4 pt-3 pb-2 active:bg-bg-elev/60 transition-colors"
      >
        {r.tags.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-2">
            {r.tags.slice(0, 5).map((t) => (
              <Badge key={t} variant="secondary" className="text-[10px] font-normal px-1.5 py-0">
                {t}
              </Badge>
            ))}
          </div>
        )}

        {r.features.length > 0 && (
          <p className="text-[13px] text-muted-foreground leading-relaxed line-clamp-2">
            {r.features.join(' · ')}
          </p>
        )}

        {!open && r.pros.length > 0 && (
          <div className="flex items-center gap-1.5 mt-2 text-[12px] text-emerald-700">
            <ThumbsUp size={12} />
            <span className="truncate">{r.pros.slice(0, 2).join('，')}</span>
          </div>
        )}

        <div className="flex justify-center pt-1.5">
          <ChevronDown
            size={16}
            className={`text-muted-foreground/50 transition-transform duration-200 ${open ? 'rotate-180' : ''}`}
          />
        </div>
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.24 }}
            className="overflow-hidden"
          >
            <div className="px-4 pb-4 pt-1 space-y-4 border-t border-border">
              <ProsConsBlock pros={r.pros} cons={r.cons} />
              <MustTryBlock items={r.mustTry} />
              <BlackListBlock items={r.blackList} />
              <StatsBar stats={r.stats} />
              <POIBlock poi={r.poi_details} />
              {r.source_notes.length > 0 && (
                <p className="text-[11px] text-muted-foreground pt-0.5">
                  来源 · {r.source_notes.length} 篇小红书笔记
                </p>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.article>
  )
}

function ProsConsBlock({ pros, cons }: { pros: string[]; cons: string[] }) {
  if (!pros.length && !cons.length) return null
  return (
    <div className="grid grid-cols-2 gap-3">
      {pros.length > 0 && (
        <div>
          <div className="flex items-center gap-1 text-[12px] font-medium text-emerald-700 mb-1.5">
            <ThumbsUp size={12} /> 优点
          </div>
          {pros.map((p, i) => (
            <p key={i} className="text-[11px] text-muted-foreground leading-relaxed">· {p}</p>
          ))}
        </div>
      )}
      {cons.length > 0 && (
        <div>
          <div className="flex items-center gap-1 text-[12px] font-medium text-destructive mb-1.5">
            <ThumbsDown size={12} /> 不足
          </div>
          {cons.map((c, i) => (
            <p key={i} className="text-[11px] text-muted-foreground leading-relaxed">· {c}</p>
          ))}
        </div>
      )}
    </div>
  )
}

function MustTryBlock({ items }: { items: Restaurant['mustTry'] }) {
  if (!items.length) return null
  return (
    <div>
      <div className="flex items-center gap-1 text-[12px] font-medium text-emerald-700 mb-1.5">
        <Sparkles size={12} /> 必点推荐
      </div>
      <div className="flex flex-wrap gap-1.5">
        {items.map((m) => (
          <Badge key={m.name} variant="local" className="font-normal gap-1">
            {m.name}
            {m.reason && <span className="text-emerald-600/70">· {m.reason}</span>}
          </Badge>
        ))}
      </div>
    </div>
  )
}

function BlackListBlock({ items }: { items: Restaurant['blackList'] }) {
  if (!items.length) return null
  return (
    <div>
      <div className="flex items-center gap-1 text-[12px] font-medium text-destructive mb-1.5">
        <Ban size={12} /> 避雷菜品
      </div>
      <div className="flex flex-wrap gap-1.5">
        {items.map((b) => (
          <Badge key={b.name} variant="wanghong" className="font-normal gap-1">
            {b.name}
            {b.reason && <span className="text-red-500/70">· {b.reason}</span>}
          </Badge>
        ))}
      </div>
    </div>
  )
}

function POIBlock({ poi }: { poi: Restaurant['poi_details'] }) {
  if (!poi) return null
  const items = [
    { icon: MapPin, text: poi.address },
    { icon: Phone, text: poi.tel },
    { icon: ClockIcon, text: poi.opentime },
    { icon: Star, text: poi.rating ? `评分 ${poi.rating}` : undefined },
  ].filter((i): i is { icon: typeof MapPin; text: string } => Boolean(i.text))

  if (!items.length) return null
  return (
    <div className="rounded-[14px] bg-bg-elev p-3 space-y-1.5">
      {items.map(({ icon: Icon, text }, i) => (
        <p key={i} className="flex items-center gap-2 text-[11px] text-muted-foreground">
          <Icon size={12} className="shrink-0" /> {text}
        </p>
      ))}
    </div>
  )
}
