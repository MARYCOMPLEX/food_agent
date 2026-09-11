import React, { useState, useEffect, useRef, useMemo } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Sparkles,
  ArrowUp,
  StopCircle,
  Plus,
  Bookmark,
  Layers,
  Server,
  X,
  ChevronRight,
  ChevronDown,
  ChevronUp,
  MessageSquare,
  AlertTriangle,
  CheckCircle2,
  MapPin,
  Clock,
  ExternalLink,
  Trash2,
  ArrowRight,
  PanelRightClose,
  PanelRightOpen,
  PanelLeftClose,
  PanelLeft,
  RefreshCw,
  Tag,
  SquarePen,
} from 'lucide-react'
import { useResearchSessionReact } from '../../features/research-session/domain/useResearchSessionReact'
import { EvidenceTimeline } from '../../components/research-surface/EvidenceTimeline'
import { ControversyPanel } from '../../components/research-surface/ControversyPanel'
import { RestaurantComparisonModal } from '../../components/restaurant/RestaurantComparisonModal'
import { QrLoginModal } from '../../components/auth/QrLoginModal'
import { useToast } from '../../context/ToastContext'
import { storage } from '../../shared/utils/storage'
import { startSearch } from '../../api/searchApi'
import { platformAccountsApi } from '../../features/platform-accounts/api/platformAccountsApi'
import type {
  ResearchProfileViewV1,
  ResearchRecommendationViewV1,
} from '../../shared/contracts/research'
import type { Restaurant } from '../../shared/contracts'

type RightPanelTab = 'evidence' | 'controversies' | 'profile'

export function UnifiedChatWorkbench() {
  const { sessionId: routeSessionId } = useParams<{ sessionId?: string }>()
  const navigate = useNavigate()
  const { showToast } = useToast()

  // Current session ID
  const [currentSessionId, setCurrentSessionId] = useState<string>(
    routeSessionId || 'session_demo_cd_hotpot',
  )

  // Research session hook
  const {
    state,
    projection,
    start,
    stop,
    appendEvent,
  } = useResearchSessionReact(currentSessionId, { autoStart: true })

  // UI States
  const [sidebarOpen, setSidebarOpen] = useState<boolean>(true)
  const [rightPanelOpen, setRightPanelOpen] = useState<boolean>(false)
  const [rightPanelTab, setRightPanelTab] = useState<RightPanelTab>('evidence')
  const [selectedProfile, setSelectedProfile] = useState<ResearchProfileViewV1 | null>(null)
  const [selectedRec, setSelectedRec] = useState<ResearchRecommendationViewV1 | null>(null)

  // Plan accordion
  const [planExpanded, setPlanExpanded] = useState<boolean>(false)

  // Follow-up context
  const [attachedContext, setAttachedContext] = useState<{
    type: 'shop' | 'controversy'
    title: string
  } | null>(null)

  // Text Composer
  const [inputText, setInputText] = useState<string>('')
  const [isComposing, setIsComposing] = useState<boolean>(false)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const chatBottomRef = useRef<HTMLDivElement | null>(null)

  // Comparison & Favorites
  const [compareList, setCompareList] = useState<Restaurant[]>([])
  const [isCompareModalOpen, setIsCompareModalOpen] = useState<boolean>(false)
  const [favorites, setFavorites] = useState<string[]>(() =>
    storage.get<string[]>('anyfast_user_favorites', ['shop_fav_1']),
  )

  // Platform Accounts & QR Modal
  const [accounts, setAccounts] = useState(platformAccountsApi.getLocalAccounts())
  const [loginModalPlatform, setLoginModalPlatform] = useState<'xhs_pc' | 'dianping' | null>(null)

  // History sessions list
  const [historyList, setHistoryList] = useState<any[]>(() => {
    const saved = storage.get<any[]>('anyfast_search_history', [])
    if (saved.length === 0) {
      const defaultHistory = [
        {
          session_id: 'session_demo_cd_hotpot',
          query: '成都玉林，本地人常去的老火锅，人均100，排队别太久，不要太甜太咸',
          created_at: new Date().toISOString(),
        },
        {
          session_id: 'session_demo_gz_tea',
          query: '广州越秀或荔湾区正宗早茶，两人人均80，虾饺要扎实',
          created_at: new Date(Date.now() - 86400000).toISOString(),
        },
      ]
      storage.set('anyfast_search_history', defaultHistory)
      return defaultHistory
    }
    return saved
  })

  // Synchronize route
  useEffect(() => {
    if (routeSessionId && routeSessionId !== currentSessionId) {
      setCurrentSessionId(routeSessionId)
    }
  }, [routeSessionId, currentSessionId])

  // Auto scroll chat
  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [projection?.summary, projection?.recommendations?.length])

  // Auto expand textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 180)}px`
    }
  }, [inputText])

  // Is investigation running
  const isRunning = state.syncState === 'synced' && projection?.status === 'running'

  // Current session query title
  const currentQuery = useMemo(() => {
    const found = historyList.find((h) => h.session_id === currentSessionId)
    return found?.query || projection?.intent?.objective || '美食深度调查'
  }, [historyList, currentSessionId, projection])

  // Check account health
  const xhsDegraded = accounts.some(
    (a) => a.platform === 'xhs_pc' && (a.status !== 'active' || a.health !== 'healthy'),
  )
  const dpDegraded = accounts.some(
    (a) => a.platform === 'dianping' && (a.status !== 'active' || a.health !== 'healthy'),
  )

  // Suggestion chips
  const suggestions = [
    '附近步行20分钟内是否有口碑老店？',
    '核实排队时间到底要多久？',
    '对比前两家的人均与必点招牌菜',
    '评论中反映的最严重缺点是什么？',
  ]

  // Start new search
  const handleStartNewChat = () => {
    const newId = `session_${Date.now()}`
    setCurrentSessionId(newId)
    setRightPanelOpen(false)
    setAttachedContext(null)
    setInputText('')
    navigate(`/chat/${newId}`)
  }

  // Switch session
  const handleSelectSession = (sid: string) => {
    setCurrentSessionId(sid)
    setRightPanelOpen(false)
    navigate(`/chat/${sid}`)
  }

  // Delete session
  const handleDeleteSession = (sid: string, e: React.MouseEvent) => {
    e.stopPropagation()
    const next = historyList.filter((h) => h.session_id !== sid)
    setHistoryList(next)
    storage.set('anyfast_search_history', next)
    if (currentSessionId === sid && next.length > 0 && next[0]) {
      handleSelectSession(next[0].session_id)
    }
  }

  // Send message
  const handleSendMessage = async (overrideText?: string) => {
    const text = (overrideText || inputText).trim()
    if (!text || isRunning) return

    const fullPrompt = attachedContext
      ? `[针对: ${attachedContext.title}] ${text}`
      : text

    // Record to history if new
    if (!historyList.some((h) => h.session_id === currentSessionId)) {
      const newHistoryItem = {
        session_id: currentSessionId,
        query: text,
        created_at: new Date().toISOString(),
      }
      const nextHistory = [newHistoryItem, ...historyList]
      setHistoryList(nextHistory)
      storage.set('anyfast_search_history', nextHistory)
    }

    setInputText('')
    setAttachedContext(null)

    try {
      await startSearch(fullPrompt, currentSessionId)
      showToast('已提交需求，Agent 正在搜集评论证据...', 'info')
    } catch {
      // Local fallback event
      appendEvent({
        schemaVersion: 'research-event/v1',
        eventId: `ev_${Date.now()}`,
        sessionId: currentSessionId,
        taskId: projection?.taskId || 'task_1',
        turnId: (projection?.turnId || 1) + 1,
        sequence: (projection?.lastSequence || 0) + 1,
        occurredAt: new Date().toISOString(),
        kind: 'run_progress',
        mutation: 'patch',
        payload: {
          summary: `已收到针对“${attachedContext ? attachedContext.title : '全局'}”的追问：“${text}”，正在补充核对评论证据...`,
        },
      })
      showToast('已收到追问，正在更新研判结论...', 'info')
    }
  }

  // Keydown
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !isComposing) {
      e.preventDefault()
      handleSendMessage()
    }
  }

  // Open Inspector
  const openInspector = (tab: RightPanelTab, profile?: ResearchProfileViewV1 | null, rec?: ResearchRecommendationViewV1 | null) => {
    setRightPanelTab(tab)
    if (profile !== undefined) setSelectedProfile(profile)
    if (rec !== undefined) setSelectedRec(rec)
    setRightPanelOpen(true)
  }

  // Toggle favorite
  const handleToggleFavorite = (shopId: string, shopName: string) => {
    let next: string[]
    if (favorites.includes(shopId)) {
      next = favorites.filter((id) => id !== shopId)
      showToast(`已取消收藏 ${shopName}`, 'info')
    } else {
      next = [...favorites, shopId]
      showToast(`已收藏 ${shopName}`, 'success')
    }
    setFavorites(next)
    storage.set('anyfast_user_favorites', next)
  }

  // Add to compare
  const handleAddToCompare = (rec: ResearchRecommendationViewV1, profile?: ResearchProfileViewV1 | null) => {
    const rObj: Restaurant = {
      id: rec.recommendationId,
      name: rec.title,
      oneLiner: rec.summary,
      pros: rec.highlights,
      cons: rec.warnings,
      price: profile?.averagePrice ? String(profile.averagePrice) : undefined,
      address: profile?.address || undefined,
      hours: profile?.openingHours || undefined,
    }
    if (compareList.some((c) => c.id === rec.recommendationId)) {
      setIsCompareModalOpen(true)
      return
    }
    if (compareList.length >= 4) {
      showToast('最多同时对比 4 家餐厅', 'warning')
      return
    }
    setCompareList([...compareList, rObj])
    showToast(`已将 ${rec.title} 加入对比`, 'success')
  }

  // Recommendations & Active items
  const recommendations = projection?.recommendations || []
  const evidenceItems = projection?.evidence || []
  const controversies = projection?.controversies || []
  const profiles = projection?.profiles || []
  const plan = projection?.plan || []

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-white text-zinc-900 font-sans">
      {/* 1. Left Sidebar (Authentic ChatGPT style) */}
      <aside
        className={`${
          sidebarOpen ? 'w-64 sm:w-72' : 'w-0 -ml-72'
        } flex flex-col bg-[#f9f9f9] border-r border-zinc-200/80 transition-all duration-200 z-30 flex-shrink-0 select-none overflow-hidden`}
      >
        {/* Sidebar Header */}
        <div className="p-3.5 flex items-center justify-between border-b border-zinc-200/60">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-lg bg-[#10a37f] text-white flex items-center justify-center font-bold shadow-2xs">
              <Sparkles className="w-4 h-4" />
            </div>
            <div className="flex items-center gap-1.5">
              <span className="font-semibold text-sm text-zinc-900 tracking-tight">Food Agent</span>
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded-md bg-zinc-200/70 text-zinc-600 font-medium">
                4o
              </span>
            </div>
          </div>
          <button
            onClick={() => setSidebarOpen(false)}
            className="p-1 rounded-lg text-zinc-400 hover:text-zinc-700 hover:bg-zinc-200/60 transition-colors"
            title="收起侧栏"
          >
            <PanelLeftClose className="w-4 h-4" />
          </button>
        </div>

        {/* New Chat Button */}
        <div className="p-3">
          <button
            onClick={handleStartNewChat}
            className="w-full flex items-center justify-between py-2 px-3 rounded-xl bg-white hover:bg-zinc-100 border border-zinc-200/80 text-zinc-800 text-xs font-medium transition-all shadow-2xs group"
          >
            <span className="flex items-center gap-2">
              <Plus className="w-3.5 h-3.5 text-zinc-600" />
              <span>新建美食调研</span>
            </span>
            <SquarePen className="w-3.5 h-3.5 text-zinc-400 group-hover:text-zinc-700 transition-colors" />
          </button>
        </div>

        {/* Sessions History List */}
        <div className="flex-1 overflow-y-auto px-2 space-y-0.5 text-xs">
          <div className="px-3 py-1.5 text-[10px] font-medium text-zinc-400 uppercase tracking-wider">
            历史对话
          </div>
          {historyList.map((item) => {
            const isSelected = item.session_id === currentSessionId
            return (
              <div
                key={item.session_id}
                onClick={() => handleSelectSession(item.session_id)}
                className={`group flex items-center justify-between px-3 py-2 rounded-xl cursor-pointer transition-colors ${
                  isSelected
                    ? 'bg-zinc-200/80 text-zinc-900 font-medium'
                    : 'text-zinc-600 hover:bg-zinc-200/50 hover:text-zinc-900'
                }`}
              >
                <div className="flex items-center gap-2 min-w-0 flex-1">
                  <MessageSquare className={`w-3.5 h-3.5 flex-shrink-0 ${isSelected ? 'text-[#10a37f]' : 'text-zinc-400'}`} />
                  <span className="truncate text-xs">{item.query}</span>
                </div>
                <button
                  onClick={(e) => handleDeleteSession(item.session_id, e)}
                  className="opacity-0 group-hover:opacity-100 p-1 text-zinc-400 hover:text-red-500 rounded transition-opacity"
                  title="删除此会话"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            )
          })}
        </div>

        {/* Sidebar Footer */}
        <div className="p-3 border-t border-zinc-200/80 space-y-2 text-xs">
          {/* Account Connectivity Status */}
          <div className="bg-white p-2.5 rounded-xl border border-zinc-200/80 space-y-1.5 shadow-2xs">
            <div className="flex items-center justify-between text-[11px] text-zinc-500 font-medium">
              <span>探店数据源</span>
              <span className="text-[10px] font-mono text-zinc-400">STATUS</span>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setLoginModalPlatform('xhs_pc')}
                className="flex-1 py-1 px-2 rounded-lg bg-zinc-50 hover:bg-zinc-100 border border-zinc-200/70 text-[11px] font-medium flex items-center justify-center gap-1.5 transition-colors"
              >
                <span className={`w-1.5 h-1.5 rounded-full ${xhsDegraded ? 'bg-amber-500' : 'bg-[#10a37f]'}`} />
                <span>小红书</span>
              </button>
              <button
                onClick={() => setLoginModalPlatform('dianping')}
                className="flex-1 py-1 px-2 rounded-lg bg-zinc-50 hover:bg-zinc-100 border border-zinc-200/70 text-[11px] font-medium flex items-center justify-center gap-1.5 transition-colors"
              >
                <span className={`w-1.5 h-1.5 rounded-full ${dpDegraded ? 'bg-amber-500' : 'bg-[#10a37f]'}`} />
                <span>大众点评</span>
              </button>
            </div>
          </div>

          {/* Link to Ops console */}
          <button
            onClick={() => navigate('/ops')}
            className="w-full flex items-center justify-between px-3 py-2 rounded-xl text-zinc-600 hover:text-zinc-900 hover:bg-zinc-200/60 transition-colors"
          >
            <span className="flex items-center gap-2">
              <Server className="w-3.5 h-3.5 text-zinc-500" />
              <span className="text-xs font-medium">运维管控中台</span>
            </span>
            <ExternalLink className="w-3 h-3 text-zinc-400" />
          </button>
        </div>
      </aside>

      {/* 2. Main Chat Conversation Body */}
      <main className="flex-1 flex flex-col h-full min-w-0 bg-white relative">
        {/* Chat Top Header */}
        <header className="h-14 border-b border-zinc-100 px-4 sm:px-6 flex items-center justify-between bg-white/95 backdrop-blur-md z-10 flex-shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            {!sidebarOpen && (
              <button
                onClick={() => setSidebarOpen(true)}
                className="p-1.5 rounded-lg text-zinc-500 hover:text-zinc-900 hover:bg-zinc-100 transition-colors"
                title="展开边栏"
              >
                <PanelLeft className="w-4 h-4" />
              </button>
            )}

            {/* Model Pill */}
            <div className="flex items-center gap-1 px-2.5 py-1 rounded-xl hover:bg-zinc-100 cursor-pointer transition-colors">
              <span className="font-semibold text-zinc-900 text-sm">Food Agent 4o</span>
              <ChevronDown className="w-3.5 h-3.5 text-zinc-400" />
            </div>
          </div>

          {/* Header Actions */}
          <div className="flex items-center gap-2">
            {compareList.length > 0 && (
              <button
                onClick={() => setIsCompareModalOpen(true)}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-zinc-100 hover:bg-zinc-200 text-zinc-800 text-xs font-medium transition-colors"
              >
                <Layers className="w-3.5 h-3.5 text-zinc-600" />
                <span>对比 ({compareList.length})</span>
              </button>
            )}

            {/* Toggle Right Inspector Button */}
            <button
              onClick={() => setRightPanelOpen(!rightPanelOpen)}
              className={`p-2 rounded-xl text-xs flex items-center gap-1.5 transition-colors ${
                rightPanelOpen
                  ? 'bg-zinc-900 text-white shadow-2xs'
                  : 'bg-zinc-100 text-zinc-700 hover:bg-zinc-200'
              }`}
              title={rightPanelOpen ? '收起检查器' : '展开评论与档案检查器'}
            >
              {rightPanelOpen ? <PanelRightClose className="w-4 h-4" /> : <PanelRightOpen className="w-4 h-4" />}
              <span className="hidden sm:inline">检查器</span>
              {evidenceItems.length > 0 && (
                <span className={`text-[10px] px-1.5 rounded-full font-mono ${rightPanelOpen ? 'bg-zinc-800 text-white' : 'bg-white text-zinc-700'}`}>
                  {evidenceItems.length}
                </span>
              )}
            </button>
          </div>
        </header>

        {/* Messages Stream Scroll Area */}
        <div className="flex-1 overflow-y-auto px-4 sm:px-8 py-6 space-y-6">
          {/* User Message Bubble */}
          <div className="max-w-3xl mx-auto flex justify-end">
            <div className="max-w-[85%] bg-[#f4f4f4] text-zinc-900 px-5 py-3.5 rounded-[24px] text-sm leading-relaxed shadow-2xs">
              {currentQuery}
            </div>
          </div>

          {/* Assistant Response Container */}
          <div className="max-w-3xl mx-auto flex items-start gap-3.5">
            {/* Assistant Avatar */}
            <div className="w-7 h-7 rounded-full bg-[#10a37f] text-white flex items-center justify-center flex-shrink-0 shadow-2xs mt-0.5">
              <Sparkles className="w-3.5 h-3.5" />
            </div>

            <div className="flex-1 space-y-4 min-w-0">
              {/* 1. Thought Process (OpenAI o1 / o3-mini style) */}
              {plan.length > 0 && (
                <div>
                  <button
                    onClick={() => setPlanExpanded(!planExpanded)}
                    className="inline-flex items-center gap-1.5 text-xs text-zinc-500 hover:text-zinc-800 font-medium py-1 transition-colors group"
                  >
                    <span>思考与检索步骤 ({plan.length} 步)</span>
                    <ChevronDown
                      className={`w-3.5 h-3.5 text-zinc-400 group-hover:text-zinc-700 transition-transform duration-200 ${
                        planExpanded ? 'rotate-180' : ''
                      }`}
                    />
                  </button>

                  {planExpanded && (
                    <div className="mt-2 mb-3 pl-3.5 border-l-2 border-zinc-200 space-y-2 text-xs text-zinc-500 animate-in fade-in duration-150">
                      {plan.map((s, idx) => (
                        <div key={idx} className="flex items-start gap-2">
                          {s.status === 'succeeded' ? (
                            <CheckCircle2 className="w-3.5 h-3.5 text-[#10a37f] mt-0.5 flex-shrink-0" />
                          ) : s.status === 'running' ? (
                            <RefreshCw className="w-3.5 h-3.5 text-zinc-700 animate-spin mt-0.5 flex-shrink-0" />
                          ) : (
                            <Clock className="w-3.5 h-3.5 text-zinc-300 mt-0.5 flex-shrink-0" />
                          )}
                          <div>
                            <span className="font-medium text-zinc-700">{s.label}</span>
                            {s.detail && <div className="text-[11px] text-zinc-400 mt-0.5">{s.detail}</div>}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* 2. Agent Synthesis Summary */}
              {projection?.summary ? (
                <div className="text-sm leading-relaxed text-zinc-900 font-normal">
                  <p className="whitespace-pre-line">{projection.summary}</p>
                </div>
              ) : (
                <div className="flex items-center gap-2 text-xs text-zinc-400 py-2">
                  <RefreshCw className="w-3.5 h-3.5 animate-spin text-zinc-600" />
                  <span>正在检索分析小红书与大众点评真实评论...</span>
                </div>
              )}

              {/* 3. Embedded Recommendation Cards */}
              {recommendations.length > 0 && (
                <div className="space-y-3 pt-2">
                  <div className="text-xs text-zinc-400 font-medium uppercase tracking-wider">
                    精选建议候选 ({recommendations.length})
                  </div>

                  <div className="space-y-3">
                    {recommendations.map((rec, idx) => {
                      const matchedProfile = profiles.find(
                        (p) => p.name === rec.title || p.profileId === rec.profileRef,
                      )
                      const isFavorite = favorites.includes(rec.recommendationId)

                      return (
                        <div
                          key={rec.recommendationId}
                          className="bg-white rounded-2xl border border-zinc-200 p-4.5 shadow-2xs hover:border-zinc-300 hover:shadow-xs transition-all space-y-3"
                        >
                          {/* Card Header: Rank, Title, Price, Bookmark */}
                          <div className="flex items-start justify-between gap-3">
                            <div className="flex items-start gap-3">
                              <div className="w-6 h-6 rounded-full bg-zinc-100 text-zinc-800 font-mono font-semibold text-xs flex items-center justify-center flex-shrink-0 mt-0.5">
                                {rec.rank || idx + 1}
                              </div>

                              <div>
                                <div className="flex items-center gap-2 flex-wrap">
                                  <h4
                                    onClick={() => openInspector('profile', matchedProfile || null, rec)}
                                    className="font-semibold text-zinc-900 text-base hover:text-[#10a37f] transition-colors cursor-pointer"
                                  >
                                    {rec.title}
                                  </h4>
                                  {matchedProfile?.averagePrice && (
                                    <span className="font-mono text-xs text-zinc-500">
                                      ¥{matchedProfile.averagePrice}/人
                                    </span>
                                  )}
                                </div>
                                {matchedProfile?.address && (
                                  <div className="flex items-center gap-1 text-xs text-zinc-400 mt-0.5">
                                    <MapPin className="w-3 h-3 text-zinc-400" />
                                    <span className="truncate max-w-xs">{matchedProfile.address}</span>
                                  </div>
                                )}
                              </div>
                            </div>

                            <button
                              onClick={() => handleToggleFavorite(rec.recommendationId, rec.title)}
                              className={`p-1.5 rounded-lg text-xs transition-colors ${
                                isFavorite
                                  ? 'text-amber-500'
                                  : 'text-zinc-400 hover:text-zinc-700'
                              }`}
                              title={isFavorite ? '已收藏' : '收藏'}
                            >
                              <Bookmark className={`w-4 h-4 ${isFavorite ? 'fill-current' : ''}`} />
                            </button>
                          </div>

                          {/* Highlights & Warnings Pills */}
                          <div className="flex flex-wrap gap-1.5 text-xs">
                            {rec.highlights?.map((h, i) => (
                              <span
                                key={i}
                                className="px-2.5 py-0.5 rounded-full bg-zinc-100 text-zinc-700 text-xs font-medium border border-zinc-200/50"
                              >
                                {h}
                              </span>
                            ))}
                            {rec.warnings?.map((w, i) => (
                              <span
                                key={i}
                                className="px-2.5 py-0.5 rounded-full bg-amber-50 text-amber-800 text-xs font-medium border border-amber-200/60"
                              >
                                避雷: {w}
                              </span>
                            ))}
                          </div>

                          {/* One-liner summary */}
                          {rec.summary && (
                            <div className="text-xs text-zinc-600 leading-relaxed">
                              {rec.summary}
                            </div>
                          )}

                          {/* Footer Action Buttons (OpenAI Pill Buttons) */}
                          <div className="pt-2 border-t border-zinc-100 flex items-center justify-between gap-2 text-xs flex-wrap">
                            <div className="flex items-center gap-1.5">
                              <button
                                onClick={() => openInspector('evidence', matchedProfile || null, rec)}
                                className="px-3 py-1.5 rounded-full border border-zinc-200 hover:bg-zinc-50 text-zinc-700 font-medium transition-colors text-xs"
                              >
                                查阅真实评论 ({rec.evidenceRefs?.length || 0})
                              </button>

                              <button
                                onClick={() => openInspector('profile', matchedProfile || null, rec)}
                                className="px-3 py-1.5 rounded-full border border-zinc-200 hover:bg-zinc-50 text-zinc-700 font-medium transition-colors text-xs hidden sm:inline"
                              >
                                店铺档案
                              </button>

                              <button
                                onClick={() => handleAddToCompare(rec, matchedProfile)}
                                className="px-3 py-1.5 rounded-full border border-zinc-200 hover:bg-zinc-50 text-zinc-700 font-medium transition-colors text-xs hidden sm:inline"
                              >
                                加入对比
                              </button>
                            </div>

                            <button
                              onClick={() => {
                                setAttachedContext({ type: 'shop', title: rec.title })
                                textareaRef.current?.focus()
                              }}
                              className="inline-flex items-center gap-1 px-3 py-1.5 rounded-full bg-zinc-900 hover:bg-zinc-800 text-white font-medium transition-colors shadow-2xs text-xs"
                            >
                              <span>就此店追问</span>
                              <ArrowRight className="w-3 h-3" />
                            </button>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              {/* 4. Controversies Callout Banner */}
              {controversies.length > 0 && (
                <div
                  onClick={() => openInspector('controversies')}
                  className="p-3.5 rounded-2xl bg-amber-50/70 border border-amber-200/80 text-xs text-amber-900 flex items-center justify-between cursor-pointer hover:bg-amber-100/50 transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <AlertTriangle className="w-4 h-4 text-amber-600 flex-shrink-0" />
                    <span className="font-medium">
                      发现 {controversies.length} 项评论分歧争议（如排队耗时、服务体验）
                    </span>
                  </div>
                  <span className="text-amber-800 font-medium flex items-center gap-1">
                    <span>查看争议对抗详情</span>
                    <ChevronRight className="w-3.5 h-3.5" />
                  </span>
                </div>
              )}

              {/* 5. Follow-up Quick Chips */}
              <div className="pt-2">
                <div className="flex flex-wrap items-center gap-1.5 text-xs">
                  <span className="text-zinc-400 text-[11px] mr-1">建议追问：</span>
                  {suggestions.map((sug, i) => (
                    <button
                      key={i}
                      onClick={() => handleSendMessage(sug)}
                      className="px-3 py-1.5 rounded-full border border-zinc-200 bg-white hover:bg-zinc-50 text-zinc-700 font-medium transition-all shadow-2xs"
                    >
                      {sug}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>

          <div ref={chatBottomRef} />
        </div>

        {/* 3. Floating ChatGPT Composer at Bottom */}
        <div className="sticky bottom-0 bg-gradient-to-t from-white via-white/95 to-transparent pt-4 pb-3 px-4 z-20">
          <div className="max-w-3xl mx-auto space-y-2">
            {/* Input Box Container */}
            <div className="bg-[#f4f4f4] focus-within:bg-white focus-within:ring-1 focus-within:ring-zinc-300 focus-within:shadow-[0_8px_30px_rgb(0,0,0,0.06)] border border-transparent focus-within:border-zinc-200 rounded-[26px] p-3 pl-4 transition-all space-y-2">
              {/* Attached context chip */}
              {attachedContext && (
                <div className="inline-flex items-center gap-1.5 bg-white border border-zinc-200 px-2.5 py-1 rounded-full text-xs text-zinc-800 shadow-2xs">
                  <Tag className="w-3 h-3 text-[#10a37f]" />
                  <span className="font-medium">针对：{attachedContext.title}</span>
                  <button onClick={() => setAttachedContext(null)} className="ml-1 text-zinc-400 hover:text-zinc-700">
                    <X className="w-3 h-3" />
                  </button>
                </div>
              )}

              {/* Textarea */}
              <div className="flex items-end gap-2">
                <textarea
                  ref={textareaRef}
                  rows={1}
                  placeholder={
                    attachedContext
                      ? `向 Food Agent 追问关于“${attachedContext.title}”的具体评价或排队避坑...`
                      : '向 Food Agent 提问，例如：“静安寺200元内正宗本帮菜”、“第一家排队严重吗”...'
                  }
                  value={inputText}
                  onChange={(e) => setInputText(e.target.value)}
                  onCompositionStart={() => setIsComposing(true)}
                  onCompositionEnd={() => setIsComposing(false)}
                  onKeyDown={handleKeyDown}
                  disabled={isRunning}
                  className="flex-1 bg-transparent resize-none p-1 text-sm text-zinc-900 placeholder-zinc-400 focus:outline-none max-h-44 leading-relaxed"
                />

                {isRunning ? (
                  <button
                    onClick={stop}
                    className="w-8 h-8 rounded-full bg-zinc-900 text-white flex items-center justify-center hover:bg-zinc-800 transition-colors flex-shrink-0"
                    title="停止生成"
                  >
                    <StopCircle className="w-4 h-4" />
                  </button>
                ) : (
                  <button
                    onClick={() => handleSendMessage()}
                    disabled={!inputText.trim()}
                    className="w-8 h-8 rounded-full bg-zinc-900 text-white flex items-center justify-center disabled:bg-zinc-200 disabled:text-zinc-400 hover:bg-zinc-800 transition-all flex-shrink-0"
                    title="发送"
                  >
                    <ArrowUp className="w-4 h-4" />
                  </button>
                )}
              </div>
            </div>

            {/* Bottom Disclaimer */}
            <div className="text-[11px] text-zinc-400 text-center">
              Food Agent 可能会提供不准确的商户信息，请核对重要餐饮与排队信息。
            </div>
          </div>
        </div>
      </main>

      {/* 4. Right Inspector Slide-over (OpenAI Canvas style) */}
      <aside
        className={`${
          rightPanelOpen ? 'w-full md:w-[440px]' : 'w-0 hidden md:flex md:w-0'
        } border-l border-zinc-200 bg-white flex flex-col h-full z-20 transition-all duration-200 overflow-hidden flex-shrink-0 shadow-lg md:shadow-none`}
      >
        {/* Inspector Header & Segmented Tabs */}
        <div className="p-3 border-b border-zinc-100 flex items-center justify-between">
          <div className="flex items-center gap-1 bg-zinc-100 p-1 rounded-xl text-xs">
            <button
              onClick={() => setRightPanelTab('evidence')}
              className={`px-3 py-1.5 rounded-lg font-medium transition-colors ${
                rightPanelTab === 'evidence'
                  ? 'bg-white text-zinc-900 shadow-2xs'
                  : 'text-zinc-500 hover:text-zinc-900'
              }`}
            >
              评论证据 ({evidenceItems.length})
            </button>
            <button
              onClick={() => setRightPanelTab('controversies')}
              className={`px-3 py-1.5 rounded-lg font-medium transition-colors ${
                rightPanelTab === 'controversies'
                  ? 'bg-white text-zinc-900 shadow-2xs'
                  : 'text-zinc-500 hover:text-zinc-900'
              }`}
            >
              争议焦点 ({controversies.length})
            </button>
            <button
              onClick={() => setRightPanelTab('profile')}
              className={`px-3 py-1.5 rounded-lg font-medium transition-colors ${
                rightPanelTab === 'profile'
                  ? 'bg-white text-zinc-900 shadow-2xs'
                  : 'text-zinc-500 hover:text-zinc-900'
              }`}
            >
              店铺档案
            </button>
          </div>

          <button
            onClick={() => setRightPanelOpen(false)}
            className="p-1 rounded-lg text-zinc-400 hover:text-zinc-700 hover:bg-zinc-100 transition-colors"
            title="关闭检查器"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Inspector Tab Content */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {rightPanelTab === 'evidence' && (
            <EvidenceTimeline
              evidenceItems={evidenceItems}
              recommendations={recommendations}
            />
          )}

          {rightPanelTab === 'controversies' && (
            <ControversyPanel
              controversies={controversies}
              evidenceItems={evidenceItems}
              onVerifyControversy={(c) => {
                setAttachedContext({ type: 'controversy', title: c.topic })
                textareaRef.current?.focus()
              }}
            />
          )}

          {rightPanelTab === 'profile' && (
            <div className="space-y-4">
              <div className="text-xs font-medium text-zinc-400 uppercase tracking-wider">
                大众点评店铺事实档案
              </div>
              {(() => {
                const p = selectedProfile || (profiles.length > 0 ? profiles[0] : null)
                if (!p) {
                  return (
                    <div className="p-8 text-center text-xs text-zinc-400">
                      请在推荐列表中点击某家店铺以查看其大众点评结构化档案
                    </div>
                  )
                }
                return (
                  <div className="bg-zinc-50/80 p-4.5 rounded-2xl border border-zinc-200 space-y-3 text-xs">
                    <div className="font-semibold text-zinc-900 text-base">{p.name || '精选门店'}</div>
                    {p.address && (
                      <div className="flex items-start gap-2 text-zinc-700">
                        <MapPin className="w-3.5 h-3.5 text-zinc-400 mt-0.5 flex-shrink-0" />
                        <span>{p.address}</span>
                      </div>
                    )}
                    {p.openingHours && (
                      <div className="flex items-start gap-2 text-zinc-700">
                        <Clock className="w-3.5 h-3.5 text-zinc-400 mt-0.5 flex-shrink-0" />
                        <span>营业时间：{p.openingHours}</span>
                      </div>
                    )}
                    <div className="pt-2 border-t border-zinc-200 flex items-center justify-between text-zinc-600">
                      <span>人均消费：{p.averagePrice ? `￥${p.averagePrice}` : '暂无'}</span>
                      <span>点评评分：{p.rating ? `${p.rating} 分` : '暂无'}</span>
                    </div>
                  </div>
                )
              })()}
            </div>
          )}
        </div>
      </aside>

      {/* Comparison Modal */}
      <RestaurantComparisonModal
        isOpen={isCompareModalOpen}
        restaurants={compareList}
        onClose={() => setIsCompareModalOpen(false)}
        onRemoveRestaurant={(id) => setCompareList(compareList.filter((r) => r.id !== id))}
        onSelectForFollowUp={(r) => {
          setAttachedContext({ type: 'shop', title: r.name })
          textareaRef.current?.focus()
        }}
      />

      {/* QR Login Modal */}
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

