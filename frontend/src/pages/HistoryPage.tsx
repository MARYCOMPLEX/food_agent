import { useEffect } from 'react'
import { motion } from 'framer-motion'
import { useHistoryStore } from '../stores/historyStore'
import { useSearchStore } from '../stores/searchStore'
import { EmptyState } from '../components/shared/EmptyState'
import { formatDate } from '../utils/format'
import { useNavigate } from 'react-router-dom'

export function HistoryPage() {
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

  return (
    <div className="px-4 py-4">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="font-display text-lg font-bold text-ink">搜索足迹</h2>
          <p className="text-xs text-muted">{items.length} 条记录</p>
        </div>
        {items.length > 0 && (
          <button
            onClick={clearAll}
            className="text-xs text-muted hover:text-red-500 transition-colors"
          >
            清空全部
          </button>
        )}
      </div>

      {items.length === 0 ? (
        <EmptyState
          icon="🔍"
          title="暂无搜索记录"
          description="你的美食探索之旅即将开始"
          action={{ label: '开始搜索', onClick: () => navigate('/') }}
        />
      ) : (
        <div className="space-y-2">
          {items.map((item, i) => (
            <motion.div
              key={item.id}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.04 }}
              className="bg-white rounded-xl border border-border p-3.5 flex items-center gap-3 group"
            >
              <button
                onClick={() => handleReSearch(item.query)}
                className="flex-1 min-w-0 text-left"
              >
                <p className="text-sm font-medium text-ink truncate group-hover:text-ember transition-colors">
                  {item.query}
                </p>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-[10px] text-muted">
                    {formatDate(item.createdAt)}
                  </span>
                  {item.resultsCount > 0 && (
                    <span className="text-[10px] text-ember-light">
                      · {item.resultsCount} 家餐厅
                    </span>
                  )}
                  {item.status && (
                    <span className="text-[10px] text-muted">
                      · {item.status === 'completed' ? '已完成' : item.status === 'error' ? '出错' : '进行中'}
                    </span>
                  )}
                </div>
              </button>

              <button
                onClick={() => deleteItem(item.id)}
                className="shrink-0 w-7 h-7 rounded-lg flex items-center justify-center text-muted hover:text-red-500 hover:bg-red-50 transition-all opacity-0 group-hover:opacity-100"
              >
                ×
              </button>
            </motion.div>
          ))}
        </div>
      )}
    </div>
  )
}
