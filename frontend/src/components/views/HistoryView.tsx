import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { ChevronRight, Clock, Search, Trash2 } from 'lucide-react'
import { useHistoryStore } from '@/stores/historyStore'
import { useSearchStore } from '@/stores/searchStore'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { EmptyState } from '@/components/shared/EmptyState'
import { MobilePage } from '@/components/mobile/MobilePage'
import { formatDate } from '@/utils/format'

export function HistoryView() {
  const { items, fetchHistory, deleteItem, clearAll } = useHistoryStore()
  const { search } = useSearchStore()
  const navigate = useNavigate()

  useEffect(() => {
    fetchHistory()
  }, [fetchHistory])

  const handleReSearch = (query: string) => {
    search(query)
    navigate('/')
  }

  const clearAction =
    items.length > 0 ? (
      <Button
        variant="destructive"
        size="sm"
        onClick={clearAll}
        className="h-7 px-2 text-xs"
      >
        清空
      </Button>
    ) : undefined

  return (
    <MobilePage subtitle={`${items.length} 条记录`} action={clearAction}>
      {items.length === 0 ? (
        <EmptyState
          icon={<Search size={24} />}
          title="暂无搜索记录"
          description="你的每次搜索都会保存在这里"
        />
      ) : (
        <div className="px-4 md:px-6 pb-6 max-w-3xl mx-auto w-full">
          <Card className="overflow-hidden p-0 divide-y divide-border">
            <AnimatePresence mode="popLayout">
              {items.map((item) => (
                <motion.div
                  key={item.id}
                  layout
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, x: -24 }}
                  className="flex items-center gap-3 px-3.5 py-3 active:bg-bg-elev/60 md:hover:bg-bg-elev/40 transition-colors"
                >
                  <Search className="size-4 shrink-0 text-muted-foreground/50" />
                  <button
                    type="button"
                    onClick={() => handleReSearch(item.query)}
                    className="flex-1 min-w-0 text-left"
                  >
                    <p className="text-sm font-medium text-foreground truncate">{item.query}</p>
                    <div className="flex items-center gap-2 mt-1">
                      <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
                        <Clock className="size-2.5" />
                        {formatDate(item.createdAt)}
                      </span>
                      {item.resultsCount > 0 && (
                        <Badge variant="secondary" className="text-[10px] py-0 h-4 font-normal">
                          {item.resultsCount} 家
                        </Badge>
                      )}
                    </div>
                  </button>
                  <button
                    type="button"
                    onClick={() => handleReSearch(item.query)}
                    className="hidden md:flex shrink-0 items-center gap-0.5 text-[11px] text-muted-foreground hover:text-primary transition-colors"
                  >
                    查看详情
                    <ChevronRight className="size-3.5" />
                  </button>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={(e) => {
                      e.stopPropagation()
                      deleteItem(item.id)
                    }}
                    className="shrink-0 size-8 text-muted-foreground hover:text-destructive"
                    aria-label="删除"
                  >
                    <Trash2 className="size-3.5" />
                  </Button>
                </motion.div>
              ))}
            </AnimatePresence>
          </Card>
        </div>
      )}
    </MobilePage>
  )
}
