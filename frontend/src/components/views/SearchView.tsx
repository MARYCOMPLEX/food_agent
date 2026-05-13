import { useRef, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { UtensilsCrossed } from 'lucide-react'
import { useSearchStore } from '@/stores/searchStore'
import { SearchPipeline } from '@/components/search/SearchPipeline'
import { RestaurantCard } from '@/components/restaurant/RestaurantCard'
import { MobileSearchInput } from '@/components/mobile/search/MobileSearchInput'
import { Card } from '@/components/ui/card'
import type { PipelineStep } from '@/types/search'
import type { Restaurant } from '@/types/restaurant'

interface PromptChip {
  emoji: string
  city: string
  sub: string
}

const PROMPT_CHIPS: readonly PromptChip[] = [
  { emoji: '🔥', city: '成都', sub: '本地人爱去的火锅' },
  { emoji: '🍜', city: '杭州', sub: '地道面馆推荐' },
  { emoji: '🫖', city: '广州', sub: '老城区早茶' },
  { emoji: '🌶️', city: '重庆', sub: '巷子里的苍蝇馆子' },
] as const

interface EmptyStateProps {
  onSelect: (q: string) => void
}

function EmptyState({ onSelect }: EmptyStateProps) {
  return (
    <div className="h-full flex flex-col items-center justify-center px-5 gap-5">
      <div className="size-14 rounded-full bg-gradient-to-br from-orange-500 to-amber-400 grid place-items-center">
        <UtensilsCrossed className="size-6 text-white" strokeWidth={2} />
      </div>
      <div className="text-center space-y-1.5">
        <h2 className="text-2xl md:text-3xl font-semibold text-foreground">今天想吃点什么？</h2>
        <p className="text-sm md:text-base text-muted-foreground">
          基于小红书真实笔记，帮你找到本地人才知道的好店
        </p>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2.5 w-full max-w-[340px] md:max-w-2xl">
        {PROMPT_CHIPS.map(({ emoji, city, sub }) => (
          <button
            key={city}
            onClick={() => onSelect(`${city}${sub}`)}
            className="text-left px-3.5 py-3 rounded-2xl border border-border bg-card active:bg-bg-elev md:hover:bg-bg-elev transition-colors border-l-[3px] border-l-orange-400"
          >
            <div className="text-sm font-semibold text-foreground leading-tight">
              {emoji} {city}
            </div>
            <div className="text-xs text-muted-foreground leading-tight mt-0.5">{sub}</div>
          </button>
        ))}
      </div>
    </div>
  )
}

interface UserBubbleProps {
  content: string
}

function UserBubble({ content }: UserBubbleProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex justify-end mb-4"
    >
      <div className="max-w-[85%] md:max-w-[70%] rounded-[18px] bg-brand px-3.5 py-2.5 text-base leading-6 text-white">
        {content}
      </div>
    </motion.div>
  )
}

interface AssistantBubbleProps {
  pipeline?: PipelineStep[]
  restaurants?: Restaurant[]
  summary?: string
  streaming?: boolean
}

function AssistantBubble({ pipeline, restaurants, summary, streaming }: AssistantBubbleProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex gap-2.5 mb-5"
    >
      <div className="shrink-0 size-7 rounded-full bg-gradient-to-br from-orange-500 to-amber-400 grid place-items-center text-white">
        <UtensilsCrossed className="size-3.5" strokeWidth={2.25} />
      </div>
      <div className="flex-1 min-w-0 space-y-3 pt-0.5">
        {pipeline && pipeline.length > 0 && (
          <Card className="px-3.5 py-2.5 shadow-none">
            <SearchPipeline steps={pipeline} />
          </Card>
        )}
        {summary && (
          <p className="text-base leading-relaxed text-foreground whitespace-pre-wrap">{summary}</p>
        )}
        {restaurants && restaurants.length > 0 && (
          <>
            <p className="text-xs text-muted-foreground -mb-1">
              为你找到 {restaurants.length} 家餐厅
            </p>
            <div className="space-y-3 md:grid md:grid-cols-2 md:gap-4 md:space-y-0">
              {restaurants.map((r, i) => (
                <RestaurantCard key={`${r.name}-${i}`} restaurant={r} index={i} />
              ))}
            </div>
          </>
        )}
        {streaming && !pipeline?.length && !restaurants?.length && !summary && (
          <div className="flex items-center gap-1.5 py-1">
            {[0, 1, 2].map((i) => (
              <motion.div
                key={i}
                className="size-2 rounded-full bg-orange-400"
                animate={{ y: [0, -6, 0] }}
                transition={{ duration: 0.6, repeat: Infinity, delay: i * 0.15, ease: 'easeInOut' }}
              />
            ))}
          </div>
        )}
      </div>
    </motion.div>
  )
}

export function SearchView() {
  const { messages, status, pipeline, restaurants, summary, search, followUp, sessionId } =
    useSearchStore()
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages.length, restaurants.length, pipeline, status])

  const handleSubmit = (q: string) => {
    if (sessionId) followUp(q)
    else search(q)
  }

  const isIdle = status === 'idle' && messages.length === 0

  return (
    <div className="flex flex-col h-full relative">
      <div ref={scrollRef} className="flex-1 overflow-y-auto overscroll-contain">
        {isIdle ? (
          <EmptyState onSelect={handleSubmit} />
        ) : (
          <div className="px-4 md:px-6 pt-4 pb-6 max-w-4xl mx-auto w-full">
            <AnimatePresence mode="popLayout">
              {messages.map((msg, i) =>
                msg.role === 'user' ? (
                  <UserBubble key={`msg-${i}`} content={msg.content} />
                ) : (
                  <AssistantBubble
                    key={`msg-${i}`}
                    pipeline={msg.pipeline}
                    restaurants={msg.restaurants}
                    summary={msg.summary}
                  />
                ),
              )}
            </AnimatePresence>
            {status === 'searching' && (
              <AssistantBubble
                pipeline={pipeline}
                restaurants={restaurants}
                summary={summary}
                streaming
              />
            )}
          </div>
        )}
      </div>
      <div
        className="shrink-0 px-3 md:px-6 pt-2 pb-3 bg-gradient-to-t from-background via-background to-background/0"
        style={{ paddingBottom: 'calc(env(safe-area-inset-bottom) + 0.75rem)' }}
      >
        <div className="max-w-4xl mx-auto w-full">
          <MobileSearchInput onSubmit={handleSubmit} disabled={status === 'searching'} />
        </div>
      </div>
    </div>
  )
}
