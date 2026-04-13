import { useRef, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { UtensilsCrossed } from 'lucide-react'
import { useSearchStore } from '@/stores/searchStore'
import { SearchPipeline } from '@/components/search/SearchPipeline'
import { MobileRestaurantCard } from './MobileRestaurantCard'
import { MobileSearchInput } from './MobileSearchInput'
import type { PipelineStep } from '@/types/search'
import type { Restaurant } from '@/types/restaurant'

const PROMPT_CHIPS = [
  { title: '成都', sub: '本地人爱去的火锅' },
  { title: '杭州', sub: '地道面馆推荐' },
  { title: '广州', sub: '老城区早茶' },
  { title: '重庆', sub: '巷子里的苍蝇馆子' },
] as const

function EmptyState({ onSelect }: { onSelect: (q: string) => void }) {
  return (
    <div className="h-full flex flex-col items-center justify-center px-5 gap-5">
      <div className="w-14 h-14 rounded-full bg-foreground grid place-items-center">
        <UtensilsCrossed size={26} className="text-background" strokeWidth={2} />
      </div>
      <h2 className="text-[22px] font-semibold text-foreground">今天想吃点什么？</h2>
      <div className="grid grid-cols-2 gap-2.5 w-full max-w-[340px]">
        {PROMPT_CHIPS.map(({ title, sub }) => (
          <button
            key={title}
            onClick={() => onSelect(`${title}${sub}`)}
            className="text-left px-3.5 py-3 rounded-[20px] border border-border bg-background active:bg-bg-elev transition-colors"
          >
            <div className="text-[14px] font-semibold text-foreground leading-tight">
              {title}
            </div>
            <div className="text-[13px] text-muted-foreground leading-tight mt-0.5">
              {sub}
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}

function UserBubble({ content }: { content: string }) {
  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="flex justify-end mb-4">
      <div className="max-w-[85%] rounded-[18px] bg-bubble-user px-3.5 py-2.5 text-[16px] leading-6 text-foreground">
        {content}
      </div>
    </motion.div>
  )
}

function AssistantBubble({
  pipeline,
  restaurants,
  summary,
  streaming,
}: {
  pipeline?: PipelineStep[]
  restaurants?: Restaurant[]
  summary?: string
  streaming?: boolean
}) {
  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="flex gap-2.5 mb-5">
      <div className="shrink-0 w-[26px] h-[26px] rounded-full bg-foreground grid place-items-center text-background">
        <UtensilsCrossed size={13} strokeWidth={2.25} />
      </div>
      <div className="flex-1 min-w-0 space-y-3 pt-0.5">
        {pipeline && pipeline.length > 0 && (
          <div className="rounded-[14px] border border-border px-3.5 py-2.5">
            <SearchPipeline steps={pipeline} />
          </div>
        )}
        {summary && (
          <p className="text-[16px] leading-relaxed text-foreground whitespace-pre-wrap">{summary}</p>
        )}
        {restaurants && restaurants.length > 0 && (
          <>
            <p className="text-[12px] text-muted-foreground -mb-1">
              为你找到 {restaurants.length} 家餐厅
            </p>
            <div className="space-y-3">
              {restaurants.map((r, i) => (
                <MobileRestaurantCard key={`${r.name}-${i}`} restaurant={r} index={i} />
              ))}
            </div>
          </>
        )}
        {streaming && !pipeline?.length && !restaurants?.length && !summary && (
          <div className="flex items-center gap-2 text-[13px] text-muted-foreground">
            <div className="w-3 h-3 border-2 border-muted-foreground border-t-transparent rounded-full animate-spin" />
            正在思考...
          </div>
        )}
      </div>
    </motion.div>
  )
}

export function MobileSearchView() {
  const { messages, status, pipeline, restaurants, summary, search, followUp, sessionId } = useSearchStore()
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
      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        {isIdle ? (
          <EmptyState onSelect={handleSubmit} />
        ) : (
          <div className="px-4 pt-4 pb-6">
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
                )
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
      <div className="shrink-0 px-3 pt-2 pb-4 bg-gradient-to-t from-background via-background to-background/0">
        <MobileSearchInput onSubmit={handleSubmit} disabled={status === 'searching'} />
      </div>
    </div>
  )
}
