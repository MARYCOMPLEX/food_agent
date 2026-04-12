import { useRef, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useSearchStore } from '../stores/searchStore'
import { SearchInput } from '../components/search/SearchInput'
import { SearchPipeline } from '../components/search/SearchPipeline'
import { RestaurantCard } from '../components/restaurant/RestaurantCard'

const SUGGESTIONS = [
  '成都本地人爱去的火锅',
  '杭州地道的面馆推荐',
  '广州老城区早茶',
  '重庆苍蝇馆子',
  '长沙夜宵一条街',
  '西安回民街以外的美食',
]

export function SearchPage() {
  const { messages, restaurants, pipeline, status, search, followUp, sessionId } = useSearchStore()
  const scrollRef = useRef<HTMLDivElement>(null)
  const isSearching = status === 'searching'

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, restaurants, pipeline])

  const handleSubmit = (query: string) => {
    if (sessionId && messages.length > 0) {
      followUp(query)
    } else {
      search(query)
    }
  }

  return (
    <div className="flex flex-col h-[calc(100dvh-64px)]">
      {/* Scrollable message area */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 pt-4">
        {/* Welcome state */}
        {messages.length === 0 && !isSearching && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex flex-col items-center pt-16 pb-8"
          >
            <span className="text-5xl mb-3">🥘</span>
            <h1 className="font-display text-2xl font-bold text-ink mb-1">
              <span className="text-ember">食</span>探
            </h1>
            <p className="text-sm text-muted mb-8">发现本地人才知道的地道美食</p>

            <div className="w-full max-w-sm">
              <p className="text-[10px] text-muted/70 uppercase tracking-widest mb-3 text-center">
                试试这些搜索
              </p>
              <div className="flex flex-wrap justify-center gap-2">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    onClick={() => search(s)}
                    className="px-3 py-1.5 text-xs text-ink-light bg-white border border-border rounded-full hover:border-ember/40 hover:text-ember transition-all active:scale-95"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          </motion.div>
        )}

        {/* Messages */}
        <div className="space-y-4 pb-4">
          {messages.map((msg, i) => (
            <div key={i}>
              {msg.role === 'user' ? (
                <motion.div
                  initial={{ opacity: 0, x: 20 }}
                  animate={{ opacity: 1, x: 0 }}
                  className="flex justify-end"
                >
                  <div className="max-w-[80%] bg-ember text-white px-4 py-2.5 rounded-2xl rounded-br-md text-sm">
                    {msg.content}
                  </div>
                </motion.div>
              ) : (
                <motion.div
                  initial={{ opacity: 0, x: -20 }}
                  animate={{ opacity: 1, x: 0 }}
                  className="space-y-3"
                >
                  {msg.pipeline && (
                    <div className="bg-white/70 rounded-xl px-3 py-2 border border-border">
                      <SearchPipeline steps={msg.pipeline} />
                    </div>
                  )}
                  {msg.summary && (
                    <p className="text-sm text-ink-light bg-white/70 rounded-xl px-4 py-3 border border-border">
                      {msg.summary}
                    </p>
                  )}
                  {msg.restaurants && msg.restaurants.length > 0 && (
                    <div className="space-y-3">
                      {msg.restaurants.map((r, j) => (
                        <RestaurantCard key={r.name + j} restaurant={r} index={j} />
                      ))}
                    </div>
                  )}
                </motion.div>
              )}
            </div>
          ))}

          {/* Live searching state */}
          <AnimatePresence>
            {isSearching && (
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                className="space-y-3"
              >
                <div className="bg-white/70 rounded-xl px-3 py-2 border border-border">
                  <SearchPipeline steps={pipeline} />
                </div>
                {restaurants.length > 0 && (
                  <div className="space-y-3">
                    {restaurants.map((r, j) => (
                      <RestaurantCard key={r.name + j} restaurant={r} index={j} />
                    ))}
                  </div>
                )}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>

      <SearchInput
        onSubmit={handleSubmit}
        disabled={isSearching}
      />
    </div>
  )
}
