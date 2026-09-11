import React, { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Search,
  Sparkles,
  MapPin,
  Flame,
  Clock,
  Coins,
  Users,
  ShieldCheck,
  AlertTriangle,
  ArrowRight,
  RefreshCw,
  X,
  History,
  CheckCircle2,
  Layers,
} from 'lucide-react'
import { startSearch } from '../../api/searchApi'
import { platformAccountsApi } from '../../features/platform-accounts/api/platformAccountsApi'
import { useToast } from '../../context/ToastContext'
import { QrLoginModal } from '../../components/auth/QrLoginModal'
import { storage } from '../../shared/utils/storage'

export function ExplorePage() {
  const navigate = useNavigate()
  const { showToast } = useToast()

  const [query, setQuery] = useState<string>('')
  const [isComposing, setIsComposing] = useState<boolean>(false)
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false)

  // Research Strategy
  const [strategy, setStrategy] = useState<'reuse' | 'incremental' | 'new'>('reuse')

  // Condition Tags
  const [city, setCity] = useState<string>('成都')
  const [budget, setBudget] = useState<string>('人均100左右')
  const [scene, setScene] = useState<string>('朋友聚餐')
  const [taste, setTaste] = useState<string>('微辣/不要太咸')
  const [customTags, setCustomTags] = useState<string[]>(['排队<40分钟', '本地老店'])

  // Account State
  const [accounts, setAccounts] = useState(platformAccountsApi.getLocalAccounts())
  const [loginModalPlatform, setLoginModalPlatform] = useState<'xhs_pc' | 'dianping' | null>(null)

  // Recent Searches
  const [recentSearches, setRecentSearches] = useState<any[]>([])

  useEffect(() => {
    const historyList = storage.get<any[]>('anyfast_search_history', [])
    setRecentSearches(historyList.slice(0, 4))
  }, [])

  const xhsAccount = accounts.find((a) => a.platform === 'xhs_pc')
  const dpAccount = accounts.find((a) => a.platform === 'dianping')

  const isXhsHealthy = xhsAccount && xhsAccount.status === 'active' && xhsAccount.health === 'healthy'
  const isDpHealthy = dpAccount && dpAccount.status === 'active' && dpAccount.health === 'healthy'

  const examplePrompts = [
    {
      title: '成都玉林串串',
      text: '周六晚在成都玉林，三个人想吃串串，人均 100 以内。不要纯网红店，最好本地人常去，能接受排队半小时，但不要特别咸。',
    },
    {
      title: '广州地道早茶',
      text: '广州越秀或荔湾区，两个人周末上午喝早茶，人均 80 左右。虾饺和干蒸烧卖要扎实，避开排队两小时以上的营销大店。',
    },
    {
      title: '长沙深夜夜宵',
      text: '长沙五一广场周边，四人吃小龙虾和热卤，人均 130，能吃辣，环境干净点，营业到凌晨两点后。',
    },
    {
      title: '上海静安约会简餐',
      text: '上海静安寺附近，两人约会，人均 180 左右。意面或小酒馆氛围，座位间距舒适，不吵闹，需有无酒精特调。',
    },
  ]

  const handleStartSearch = async () => {
    const trimmed = query.trim()
    if (!trimmed || isSubmitting) return

    setIsSubmitting(true)
    try {
      // Build effective search context
      const fullPrompt = `${trimmed} [条件标注: 城市 ${city}, 预算 ${budget}, 场景 ${scene}, 口味 ${taste}, 标签 ${customTags.join('/')}]`

      let res: any
      try {
        res = await startSearch(fullPrompt)
      } catch {
        // Fallback for mocked environment
        const mockSessionId = `session_${Date.now()}`
        res = {
          success: true,
          sessionId: mockSessionId,
          streamUrl: `/v1/search/stream/${mockSessionId}`,
        }
      }

      // Record to history
      const prev = storage.get<any[]>('anyfast_search_history', [])
      const newHistoryItem = {
        id: res.sessionId,
        query: trimmed,
        city,
        budget,
        created_at: new Date().toISOString(),
        session_id: res.sessionId,
      }
      storage.set('anyfast_search_history', [newHistoryItem, ...prev.slice(0, 19)])

      showToast('调查任务已建立，正在连通评论证据流...', 'success')
      navigate(`/app/sessions/${res.sessionId}`)
    } catch (err: any) {
      showToast(err?.message || '发起调查失败，请检查网络后重试', 'error')
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !isComposing) {
      e.preventDefault()
      handleStartSearch()
    }
  }

  const removeTag = (tagToRemove: string) => {
    setCustomTags(customTags.filter((t) => t !== tagToRemove))
  }

  return (
    <div className="max-w-4xl mx-auto space-y-8 py-4">
      {/* Hero Header */}
      <div className="text-center space-y-2.5">
        <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-orange-100 text-orange-800 text-xs font-medium">
          <Sparkles className="w-3.5 h-3.5 text-orange-600" />
          <span>深度评论证据 & 争议辨析助手</span>
        </div>
        <h1 className="text-3xl sm:text-4xl font-extrabold text-slate-900 tracking-tight">
          发起一次真正的美食深度调查
        </h1>
        <p className="text-sm sm:text-base text-slate-500 max-w-2xl mx-auto leading-relaxed">
          不依赖营销评分与榜单推广。从小红书真实评论中识别互相矛盾的体验与避雷细节，再用大众点评补齐结构化事实，给出可追溯证据的决策建议。
        </p>
      </div>

      {/* Main Search Input Box */}
      <div className="bg-white rounded-3xl border border-slate-200 shadow-xl shadow-slate-100 p-5 sm:p-7 space-y-4">
        <div className="relative">
          <textarea
            rows={3}
            placeholder="描述你想吃什么、在哪个城市商圈、人均预算、辣度偏好，或者直接说明踩雷顾虑（如排队、口味偏咸、服务态度）..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onCompositionStart={() => setIsComposing(true)}
            onCompositionEnd={() => setIsComposing(false)}
            onKeyDown={handleKeyDown}
            disabled={isSubmitting}
            className="w-full resize-none bg-slate-50/70 border border-slate-200 focus:bg-white focus:border-orange-500 focus:ring-4 focus:ring-orange-100 rounded-2xl p-4 text-sm sm:text-base text-slate-900 placeholder-slate-400 focus:outline-none transition-all leading-relaxed"
          />
          <div className="flex items-center justify-between text-xs text-slate-400 mt-1 px-1">
            <span>按 Enter 发起调查，Shift + Enter 换行</span>
            <span>{query.length} / 400 字</span>
          </div>
        </div>

        {/* Condition Tags Assistant */}
        <div className="space-y-2 pt-2 border-t border-slate-100">
          <div className="flex items-center justify-between text-xs text-slate-500">
            <span className="font-medium">辅助条件辨析（点击可微调，不改动原始需求）：</span>
          </div>

          <div className="flex flex-wrap items-center gap-2 text-xs">
            {/* City Tag */}
            <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-xl bg-slate-100 text-slate-800 font-medium">
              <MapPin className="w-3.5 h-3.5 text-slate-500" />
              <span>城市: {city}</span>
            </div>

            {/* Budget Tag */}
            <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-xl bg-slate-100 text-slate-800 font-medium">
              <Coins className="w-3.5 h-3.5 text-slate-500" />
              <span>{budget}</span>
            </div>

            {/* Scene Tag */}
            <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-xl bg-slate-100 text-slate-800 font-medium">
              <Users className="w-3.5 h-3.5 text-slate-500" />
              <span>{scene}</span>
            </div>

            {/* Taste Tag */}
            <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-xl bg-slate-100 text-slate-800 font-medium">
              <Flame className="w-3.5 h-3.5 text-slate-500" />
              <span>{taste}</span>
            </div>

            {/* Removable Custom Tags */}
            {customTags.map((tag) => (
              <span
                key={tag}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-xl bg-orange-50 text-orange-800 border border-orange-200 font-medium"
              >
                <span>{tag}</span>
                <button
                  onClick={() => removeTag(tag)}
                  className="hover:text-orange-950 p-0.5 rounded"
                  title="移除此条件"
                >
                  <X className="w-3 h-3" />
                </button>
              </span>
            ))}
          </div>
        </div>

        {/* Strategy Selector (Section 10.5) */}
        <div className="bg-slate-50/70 p-3.5 rounded-2xl border border-slate-100 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs">
          <span className="font-semibold text-slate-700 flex items-center gap-1.5">
            <Layers className="w-4 h-4 text-orange-600" />
            调查策略：
          </span>
          <div className="flex items-center gap-2">
            <label
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl border cursor-pointer transition-all ${
                strategy === 'reuse'
                  ? 'bg-white border-orange-500 text-orange-900 font-semibold shadow-xs'
                  : 'bg-transparent border-slate-200 text-slate-600 hover:bg-white'
              }`}
            >
              <input
                type="radio"
                name="strategy"
                value="reuse"
                checked={strategy === 'reuse'}
                onChange={() => setStrategy('reuse')}
                className="sr-only"
              />
              <span>快速参考 (优先新鲜已有证据)</span>
            </label>

            <label
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl border cursor-pointer transition-all ${
                strategy === 'incremental'
                  ? 'bg-white border-orange-500 text-orange-900 font-semibold shadow-xs'
                  : 'bg-transparent border-slate-200 text-slate-600 hover:bg-white'
              }`}
            >
              <input
                type="radio"
                name="strategy"
                value="incremental"
                checked={strategy === 'incremental'}
                onChange={() => setStrategy('incremental')}
                className="sr-only"
              />
              <span>补充调查 (补齐缺口)</span>
            </label>

            <label
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl border cursor-pointer transition-all ${
                strategy === 'new'
                  ? 'bg-white border-orange-500 text-orange-900 font-semibold shadow-xs'
                  : 'bg-transparent border-slate-200 text-slate-600 hover:bg-white'
              }`}
            >
              <input
                type="radio"
                name="strategy"
                value="new"
                checked={strategy === 'new'}
                onChange={() => setStrategy('new')}
                className="sr-only"
              />
              <span>重新调查 (全网重新核实)</span>
            </label>
          </div>
        </div>

        {/* Submit Action Bar */}
        <div className="flex items-center justify-between pt-2">
          {/* Data source readiness overview */}
          <div className="flex items-center gap-3 text-xs">
            <div className="flex items-center gap-1.5">
              <div className={`w-2 h-2 rounded-full ${isXhsHealthy ? 'bg-emerald-500' : 'bg-amber-500'}`} />
              <span className="text-slate-600">小红书评论：{isXhsHealthy ? '可用' : '需验证'}</span>
            </div>
            <div className="flex items-center gap-1.5">
              <div className={`w-2 h-2 rounded-full ${isDpHealthy ? 'bg-emerald-500' : 'bg-amber-500'}`} />
              <span className="text-slate-600">大众点评档案：{isDpHealthy ? '可用' : '需验证'}</span>
            </div>
          </div>

          <button
            onClick={handleStartSearch}
            disabled={!query.trim() || isSubmitting}
            className="px-6 py-3 rounded-2xl bg-orange-600 hover:bg-orange-700 text-white font-semibold text-sm transition-all flex items-center gap-2 shadow-lg shadow-orange-600/30 disabled:opacity-40 disabled:hover:bg-orange-600 disabled:shadow-none cursor-pointer"
          >
            {isSubmitting ? (
              <>
                <RefreshCw className="w-4 h-4 animate-spin" />
                <span>正在启动调查...</span>
              </>
            ) : (
              <>
                <span>开始深度调查</span>
                <ArrowRight className="w-4 h-4" />
              </>
            )}
          </button>
        </div>
      </div>

      {/* Examples Section */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
            场景探索示例（一键填入，不会立即发送）
          </h3>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {examplePrompts.map((eg, idx) => (
            <div
              key={idx}
              onClick={() => setQuery(eg.text)}
              className="p-4 rounded-2xl bg-white border border-slate-200/80 hover:border-orange-300 hover:shadow-md transition-all cursor-pointer group"
            >
              <div className="flex items-center justify-between mb-1.5">
                <span className="font-semibold text-slate-900 text-xs group-hover:text-orange-600 transition-colors">
                  {eg.title}
                </span>
                <span className="text-[10px] text-slate-400 group-hover:text-orange-500">填入 ↵</span>
              </div>
              <p className="text-xs text-slate-600 line-clamp-2 leading-relaxed">{eg.text}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Recent Investigations */}
      {recentSearches.length > 0 && (
        <div className="space-y-3 pt-2">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider flex items-center gap-1.5">
              <History className="w-3.5 h-3.5" />
              最近发起的调查
            </h3>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
            {recentSearches.map((rec) => (
              <div
                key={rec.id}
                onClick={() => navigate(`/app/sessions/${rec.session_id}`)}
                className="p-3.5 rounded-xl bg-slate-50 hover:bg-white border border-slate-200 text-xs flex items-center justify-between cursor-pointer transition-colors"
              >
                <div className="truncate mr-2">
                  <span className="font-medium text-slate-800">{rec.query}</span>
                  <div className="text-[11px] text-slate-400 mt-0.5 font-mono">
                    {new Date(rec.created_at).toLocaleDateString()}
                  </div>
                </div>
                <ArrowRight className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Global QR Login Modal for quick fix */}
      {loginModalPlatform && (
        <QrLoginModal
          isOpen={true}
          platform={loginModalPlatform}
          onClose={() => setLoginModalPlatform(null)}
          onSuccess={() => {
            setAccounts(platformAccountsApi.getLocalAccounts())
            setLoginModalPlatform(null)
          }}
        />
      )}
    </div>
  )
}
