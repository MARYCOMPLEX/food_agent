import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  History,
  Search,
  Trash2,
  ArrowRight,
  RefreshCw,
  Clock,
  Compass,
  CheckCircle2,
  AlertTriangle,
  RotateCcw,
} from 'lucide-react'
import { storage } from '../../shared/utils/storage'
import { useToast } from '../../context/ToastContext'

interface HistorySessionItem {
  id: string
  session_id: string
  query: string
  city?: string
  budget?: string
  created_at: string
  status?: string
  roundCount?: number
  evidenceCount?: number
  candidateCount?: number
  summaryPreview?: string
}

export function HistoryPage() {
  const navigate = useNavigate()
  const { showToast } = useToast()

  const [historyList, setHistoryList] = useState<HistorySessionItem[]>([])
  const [searchQuery, setSearchQuery] = useState<string>('')

  useEffect(() => {
    const raw = storage.get<HistorySessionItem[]>('anyfast_search_history', [])
    if (raw.length === 0) {
      // Default mock sessions if starting empty
      const defaultHistory: HistorySessionItem[] = [
        {
          id: 'session_demo_cd_hotpot',
          session_id: 'session_demo_cd_hotpot',
          query: '周六晚在成都玉林，三个人想吃串串，人均 100 以内。不要纯网红店，最好本地人常去，能接受排队半小时，但不要特别咸。',
          city: '成都',
          budget: '人均100左右',
          created_at: new Date(Date.now() - 3600000 * 4).toISOString(),
          status: 'succeeded',
          roundCount: 2,
          evidenceCount: 18,
          candidateCount: 4,
          summaryPreview: '首推玉林串串香总店与结子串串，评论一致认可锅底牛油醇厚；高峰期排队约35分钟。',
        },
        {
          id: 'session_demo_gz_morningtea',
          session_id: 'session_demo_gz_morningtea',
          query: '广州越秀或荔湾区，两个人周末上午喝早茶，人均 80 左右。虾饺和干蒸烧卖要扎实，避开排队两小时以上的营销大店。',
          city: '广州',
          budget: '人均80左右',
          created_at: new Date(Date.now() - 86400000 * 2).toISOString(),
          status: 'partial',
          roundCount: 1,
          evidenceCount: 12,
          candidateCount: 3,
          summaryPreview: '陶陶居与荣华楼虾饺品质获真实好评；大众点评因验证码限制部分营业时间未及时补齐。',
        },
      ]
      setHistoryList(defaultHistory)
      storage.set('anyfast_search_history', defaultHistory)
    } else {
      setHistoryList(raw)
    }
  }, [])

  const handleDeleteItem = (id: string, e: React.MouseEvent) => {
    e.stopPropagation()
    const next = historyList.filter((item) => item.id !== id && item.session_id !== id)
    setHistoryList(next)
    storage.set('anyfast_search_history', next)
    showToast('已从本地历史列表中移除该调查记录', 'info')
  }

  const handleClearAll = () => {
    if (window.confirm('确认清空所有历史调查记录？这不会删除平台的原始抓取数据。')) {
      setHistoryList([])
      storage.set('anyfast_search_history', [])
      showToast('历史调查记录已清空', 'info')
    }
  }

  const filteredHistory = historyList.filter((item) => {
    if (!searchQuery.trim()) return true
    const q = searchQuery.toLowerCase()
    return item.query.toLowerCase().includes(q) || (item.city && item.city.toLowerCase().includes(q))
  })

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight flex items-center gap-2">
            <History className="w-6 h-6 text-orange-600" />
            <span>美食调查历史</span>
          </h1>
          <p className="text-xs text-slate-500 mt-1">
            浏览所有发起的深度调查会话，随时点击恢复调查、追问新条件或查验证据
          </p>
        </div>

        {/* Search & Clear */}
        <div className="flex items-center gap-3">
          <div className="relative">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              placeholder="搜索历史需求..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-9 pr-3 py-2 bg-white border border-slate-200 rounded-xl text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-orange-500 w-48 sm:w-60 shadow-xs"
            />
          </div>

          {historyList.length > 0 && (
            <button
              onClick={handleClearAll}
              className="p-2 rounded-xl text-slate-400 hover:text-rose-600 hover:bg-rose-50 border border-slate-200 transition-colors"
              title="清空历史记录"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>

      {/* History List */}
      {filteredHistory.length === 0 ? (
        <div className="bg-white rounded-3xl border border-dashed border-slate-200 p-12 text-center space-y-4 shadow-xs">
          <div className="w-12 h-12 rounded-2xl bg-orange-50 text-orange-600 flex items-center justify-center mx-auto">
            <History className="w-6 h-6" />
          </div>
          <div>
            <h3 className="text-base font-semibold text-slate-900">暂无调查历史</h3>
            <p className="text-xs text-slate-500 mt-1 max-w-sm mx-auto">
              在美食探索页发起调查后，每次的调查进度与证据链都会保存在此处
            </p>
          </div>
          <button
            onClick={() => navigate('/app/explore')}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-orange-600 hover:bg-orange-700 text-white text-xs font-semibold shadow-md transition-colors"
          >
            <Compass className="w-4 h-4" />
            <span>发起一次美食调查</span>
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {filteredHistory.map((item) => {
            const sid = item.session_id || item.id
            const isCompleted = item.status === 'succeeded'
            const isPartial = item.status === 'partial'

            return (
              <div
                key={item.id}
                onClick={() => navigate(`/app/sessions/${sid}`)}
                className="bg-white rounded-2xl border border-slate-200/90 p-5 shadow-xs hover:border-orange-300 hover:shadow-md transition-all cursor-pointer group flex flex-col sm:flex-row sm:items-center justify-between gap-4"
              >
                <div className="space-y-2 flex-1">
                  <div className="flex items-center gap-2 flex-wrap text-xs">
                    {item.city && (
                      <span className="px-2 py-0.5 rounded-md bg-slate-100 text-slate-700 font-medium">
                        {item.city}
                      </span>
                    )}

                    {isCompleted ? (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-emerald-50 text-emerald-700 border border-emerald-200 text-[11px] font-medium">
                        <CheckCircle2 className="w-3 h-3" />
                        调查完成
                      </span>
                    ) : isPartial ? (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-blue-50 text-blue-700 border border-blue-200 text-[11px] font-medium">
                        <AlertTriangle className="w-3 h-3" />
                        部分完成
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-orange-50 text-orange-700 border border-orange-200 text-[11px] font-medium">
                        <RefreshCw className="w-3 h-3 animate-spin" />
                        进行中
                      </span>
                    )}

                    <span className="text-[11px] text-slate-400 font-mono">
                      {new Date(item.created_at).toLocaleString()}
                    </span>
                  </div>

                  <h3 className="font-semibold text-slate-900 text-sm sm:text-base group-hover:text-orange-600 transition-colors leading-snug">
                    {item.query}
                  </h3>

                  {item.summaryPreview && (
                    <p className="text-xs text-slate-500 line-clamp-1 leading-relaxed">
                      结论摘要：{item.summaryPreview}
                    </p>
                  )}

                  <div className="flex items-center gap-3 text-[11px] text-slate-400 font-mono">
                    <span>{item.roundCount || 1} 轮调查</span>
                    <span>·</span>
                    <span>{item.evidenceCount || 12} 条评论依据</span>
                    <span>·</span>
                    <span>{item.candidateCount || 3} 家候选推荐</span>
                  </div>
                </div>

                {/* Right Action Buttons */}
                <div className="flex items-center gap-2 flex-shrink-0 self-end sm:self-center">
                  <button
                    onClick={(e) => handleDeleteItem(item.id, e)}
                    className="p-2 rounded-xl text-slate-300 hover:text-rose-600 hover:bg-rose-50 transition-colors"
                    title="从本地记录中移除"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>

                  <div className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-900 group-hover:bg-orange-600 text-white text-xs font-medium transition-colors shadow-xs">
                    <span>继续会话</span>
                    <ArrowRight className="w-3.5 h-3.5" />
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
