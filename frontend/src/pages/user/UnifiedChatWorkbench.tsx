import React, { useState, useEffect, useRef, useMemo } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Sparkles,
  Send,
  StopCircle,
  Plus,
  History,
  Bookmark,
  Layers,
  Shield,
  Server,
  Settings,
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
  UtensilsCrossed,
  Tag,
  Search,
  RefreshCw,
  PanelRightClose,
  PanelRightOpen,
  Menu,
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
  ResearchControversyViewV1,
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
    transportState,
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
    '附近步行20分钟内是否有替代老店？',
    '核实排队时间到底要多久？',
    '只对比前两家的人均与口味评价',
    '有无完全免辣的锅底推荐？',
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
    if (currentSessionId === sid && next.length > 0) {
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
    <div className="flex h-screen w-screen overflow-hidden bg-slate-50 text-slate-900 font-sans">
      {/* 1. Left Sidebar (Collapsible History & Accounts) */}
      <aside
        className={`${
          sidebarOpen ? 'w-64 sm:w-72' : 'w-0 -ml-72'
        } flex flex-col bg-slate-900 text-slate-200 border-r border-slate-800 transition-all duration-200 z-30 flex-shrink-0 select-none`}
      >
        {/* Sidebar Header */}
        <div className="p-3.5 border-b border-slate-800/80 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-xl bg-orange-600 text-white flex items-center justify-center font-bold shadow-sm shadow-orange-600/30">
              <UtensilsCrossed className="w-4 h-4" />
            </div>
            <div className="flex flex-col">
              <span className="font-bold text-sm text-white tracking-tight">Food Agent</span>
              <span className="text-[10px] text-slate-400 font-medium -mt-0.5">真实评论调查助手</span>
            </div>
          </div>
          <button
            onClick={() => setSidebarOpen(false)}
            className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
            title="收起边栏"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* New Chat Button */}
        <div className="p-3">
          <button
            onClick={handleStartNewChat}
            className="w-full flex items-center justify-center gap-2 py-2.5 px-4 rounded-xl bg-orange-600 hover:bg-orange-500 text-white text-xs font-semibold shadow-sm transition-all"
          >
            <Plus className="w-4 h-4" />
            <span>新建美食调查</span>
          </button>
        </div>

        {/* Sessions History List */}
        <div className="flex-1 overflow-y-auto px-2 space-y-1 text-xs">
          <div className="px-3 py-1.5 text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
            历史调查记录
          </div>
          {historyList.map((item) => {
            const isSelected = item.session_id === currentSessionId
            return (
              <div
                key={item.session_id}
                onClick={() => handleSelectSession(item.session_id)}
                className={`group flex items-center justify-between p-2.5 rounded-xl cursor-pointer transition-colors ${
                  isSelected
                    ? 'bg-slate-800 text-white font-medium shadow-xs'
                    : 'text-slate-400 hover:bg-slate-800/50 hover:text-slate-200'
                }`}
              >
                <div className="flex items-center gap-2 min-w-0 flex-1">
                  <MessageSquare className={`w-3.5 h-3.5 flex-shrink-0 ${isSelected ? 'text-orange-500' : 'text-slate-500'}`} />
                  <span className="truncate text-xs">{item.query}</span>
                </div>
                <button
                  onClick={(e) => handleDeleteSession(item.session_id, e)}
                  className="opacity-0 group-hover:opacity-100 p-1 text-slate-500 hover:text-rose-400 rounded transition-opacity"
                  title="删除此记录"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            )
          })}
        </div>

        {/* Sidebar Footer (Platform Status & Ops Link) */}
        <div className="p-3 border-t border-slate-800/80 space-y-2 text-xs">
          {/* Account Status Chips */}
          <div className="bg-slate-950/60 p-2.5 rounded-xl border border-slate-800 space-y-1.5">
            <div className="flex items-center justify-between text-[11px]">
              <span className="text-slate-400">数据源就绪度：</span>
              <span className="text-slate-500 font-mono text-[10px]">MCP CHANNEL</span>
            </div>
            <div className="flex items-center justify-between gap-2">
              <button
                onClick={() => setLoginModalPlatform('xhs_pc')}
                className={`flex-1 py-1 px-2 rounded-lg text-[10px] font-medium border text-center transition-colors ${
                  xhsDegraded
                    ? 'bg-amber-500/10 text-amber-400 border-amber-500/30'
                    : 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                }`}
              >
                小红书: {xhsDegraded ? '需验证' : '正常'}
              </button>
              <button
                onClick={() => setLoginModalPlatform('dianping')}
                className={`flex-1 py-1 px-2 rounded-lg text-[10px] font-medium border text-center transition-colors ${
                  dpDegraded
                    ? 'bg-amber-500/10 text-amber-400 border-amber-500/30'
                    : 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                }`}
              >
                大众点评: {dpDegraded ? '需验证' : '正常'}
              </button>
            </div>
          </div>

          {/* Link to Ops console */}
          <button
            onClick={() => navigate('/ops')}
            className="w-full flex items-center justify-between p-2 rounded-xl text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
          >
            <span className="flex items-center gap-2">
              <Server className="w-3.5 h-3.5" />
              <span>内部运维管控台</span>
            </span>
            <ExternalLink className="w-3 h-3 text-slate-500" />
          </button>
        </div>
      </aside>

      {/* 2. Main Chat Conversation Body */}
      <main className="flex-1 flex flex-col h-full min-w-0 bg-white relative">
        {/* Chat Top Header */}
        <header className="h-14 border-b border-slate-100 px-4 sm:px-6 flex items-center justify-between bg-white/90 backdrop-blur-md z-10 flex-shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            {!sidebarOpen && (
              <button
                onClick={() => setSidebarOpen(true)}
                className="p-1.5 rounded-lg text-slate-500 hover:text-slate-800 hover:bg-slate-100 transition-colors"
                title="展开边栏"
              >
                <Menu className="w-5 h-5" />
              </button>
            )}

            <div className="truncate">
              <h2 className="font-bold text-slate-900 text-sm sm:text-base truncate leading-tight">
                {currentQuery}
              </h2>
              <div className="flex items-center gap-2 text-[11px] text-slate-400 mt-0.5">
                <span className="flex items-center gap-1 font-mono">
                  <span
                    className={`w-1.5 h-1.5 rounded-full ${
                      isRunning ? 'bg-orange-500 animate-ping' : 'bg-emerald-500'
                    }`}
                  />
                  {isRunning ? '正在调查评论...' : '调查已完成'}
                </span>
                <span>·</span>
                <span>第 {projection?.turnId || 1} 轮</span>
                {evidenceItems.length > 0 && (
                  <>
                    <span>·</span>
                    <span className="font-mono">{evidenceItems.length} 条评论证据</span>
                  </>
                )}
              </div>
            </div>
          </div>

          {/* Header Action Buttons */}
          <div className="flex items-center gap-2">
            {compareList.length > 0 && (
              <button
                onClick={() => setIsCompareModalOpen(true)}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-orange-50 text-orange-800 border border-orange-200 text-xs font-semibold hover:bg-orange-100 transition-colors shadow-xs"
              >
                <Layers className="w-3.5 h-3.5" />
                <span>已选 {compareList.length} 家对比</span>
              </button>
            )}

            {/* Toggle Right Inspector Button */}
            <button
              onClick={() => setRightPanelOpen(!rightPanelOpen)}
              className={`p-2 rounded-xl border text-xs flex items-center gap-1.5 transition-colors ${
                rightPanelOpen
                  ? 'bg-orange-50 text-orange-700 border-orange-200'
                  : 'bg-slate-50 text-slate-600 border-slate-200 hover:bg-slate-100'
              }`}
              title={rightPanelOpen ? '收起右侧详情抽屉' : '展开右侧证据与档案'}
            >
              {rightPanelOpen ? <PanelRightClose className="w-4 h-4" /> : <PanelRightOpen className="w-4 h-4" />}
              <span className="hidden sm:inline">证据与档案</span>
            </button>
          </div>
        </header>

        {/* Messages Stream Scroll Area */}
        <div className="flex-1 overflow-y-auto px-4 sm:px-8 py-6 space-y-6">
          {/* User Message Bubble */}
          <div className="flex items-start gap-3 max-w-3xl mx-auto">
            <div className="w-8 h-8 rounded-full bg-slate-800 text-white flex items-center justify-center font-semibold text-xs flex-shrink-0">
              你
            </div>
            <div className="flex-1 bg-slate-100 text-slate-900 p-4 rounded-2xl rounded-tl-sm text-sm leading-relaxed shadow-xs">
              {currentQuery}
            </div>
          </div>

          {/* Assistant Response Container */}
          <div className="flex items-start gap-3 max-w-3xl mx-auto">
            <div className="w-8 h-8 rounded-full bg-orange-600 text-white flex items-center justify-center font-semibold text-xs flex-shrink-0 shadow-sm shadow-orange-600/30">
              <UtensilsCrossed className="w-4 h-4" />
            </div>

            <div className="flex-1 space-y-4 min-w-0">
              {/* 1. Collapsible Investigation Plan & Progress Accordion */}
              {plan.length > 0 && (
                <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-3.5 text-xs">
                  <div
                    className="flex items-center justify-between cursor-pointer"
                    onClick={() => setPlanExpanded(!planExpanded)}
                  >
                    <div className="flex items-center gap-2">
                      <Sparkles className="w-3.5 h-3.5 text-orange-600" />
                      <span className="font-semibold text-slate-800">Agent 调查过程与步骤</span>
                      <span className="text-[11px] font-mono px-2 py-0.5 rounded-full bg-white text-slate-600 border border-slate-200">
                        {plan.filter((s) => s.status === 'succeeded').length}/{plan.length} 完成
                      </span>
                    </div>
                    <button className="text-slate-400 hover:text-slate-600 p-0.5">
                      {planExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                    </button>
                  </div>

                  {planExpanded && (
                    <div className="mt-3 pt-3 border-t border-slate-200/70 space-y-2">
                      {plan.map((s, idx) => (
                        <div key={idx} className="flex items-start gap-2 text-slate-600">
                          {s.status === 'succeeded' ? (
                            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 mt-0.5 flex-shrink-0" />
                          ) : s.status === 'running' ? (
                            <RefreshCw className="w-3.5 h-3.5 text-orange-500 animate-spin mt-0.5 flex-shrink-0" />
                          ) : (
                            <Clock className="w-3.5 h-3.5 text-slate-300 mt-0.5 flex-shrink-0" />
                          )}
                          <div className="flex-1">
                            <span className="font-medium text-slate-800">{s.label}</span>
                            {s.detail && <div className="text-[11px] text-slate-400 mt-0.5">{s.detail}</div>}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* 2. Agent Synthesis Summary */}
              {projection?.summary ? (
                <div className="bg-white border border-slate-200 p-4 rounded-2xl text-sm leading-relaxed text-slate-800 shadow-xs">
                  <p className="whitespace-pre-line">{projection.summary}</p>
                </div>
              ) : (
                <div className="flex items-center gap-2 text-xs text-slate-400 p-3">
                  <RefreshCw className="w-3.5 h-3.5 animate-spin text-orange-500" />
                  <span>正在分析评论线索，整理候选与避雷细节...</span>
                </div>
              )}

              {/* 3. Embedded Recommendation Cards */}
              {recommendations.length > 0 && (
                <div className="space-y-3 pt-1">
                  <div className="flex items-center justify-between text-xs text-slate-500 font-semibold uppercase tracking-wider">
                    <span>精选推荐候选 ({recommendations.length})</span>
                    <span className="text-[11px] font-normal text-slate-400">点击卡片可查看右侧完整证据</span>
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
                          className="bg-white rounded-2xl border border-slate-200/90 p-4.5 shadow-xs hover:shadow-md hover:border-orange-200 transition-all space-y-3 group"
                        >
                          {/* Card Header: Rank, Title, Price, Actions */}
                          <div className="flex items-start justify-between gap-3">
                            <div className="flex items-start gap-3">
                              <div className="w-7 h-7 rounded-xl bg-orange-600 text-white font-bold text-xs flex items-center justify-center flex-shrink-0 shadow-sm shadow-orange-600/20">
                                {rec.rank || idx + 1}
                              </div>

                              <div>
                                <div className="flex items-center gap-2 flex-wrap">
                                  <h4
                                    onClick={() => openInspector('profile', matchedProfile || null, rec)}
                                    className="font-bold text-slate-900 text-base group-hover:text-orange-600 transition-colors cursor-pointer"
                                  >
                                    {rec.title}
                                  </h4>
                                  {matchedProfile?.averagePrice && (
                                    <span className="text-orange-600 font-medium text-xs">
                                      ￥{matchedProfile.averagePrice}/人
                                    </span>
                                  )}
                                </div>
                                {matchedProfile?.address && (
                                  <div className="flex items-center gap-1 text-xs text-slate-400 mt-0.5">
                                    <MapPin className="w-3 h-3 text-slate-400" />
                                    <span className="truncate max-w-xs">{matchedProfile.address}</span>
                                  </div>
                                )}
                              </div>
                            </div>

                            <div className="flex items-center gap-1">
                              <button
                                onClick={() => handleToggleFavorite(rec.recommendationId, rec.title)}
                                className={`p-1.5 rounded-lg border text-xs transition-colors ${
                                  isFavorite
                                    ? 'bg-amber-50 text-amber-600 border-amber-200'
                                    : 'bg-slate-50 text-slate-400 border-slate-200 hover:text-amber-500'
                                }`}
                                title={isFavorite ? '已收藏' : '收藏'}
                              >
                                <Bookmark className={`w-3.5 h-3.5 ${isFavorite ? 'fill-current' : ''}`} />
                              </button>
                            </div>
                          </div>

                          {/* One-liner conclusion */}
                          {rec.summary && (
                            <div className="text-xs text-slate-700 bg-slate-50 p-2.5 rounded-xl border border-slate-100 leading-relaxed">
                              {rec.summary}
                            </div>
                          )}

                          {/* Highlights & Warnings */}
                          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">
                            {rec.highlights?.slice(0, 2).map((h, i) => (
                              <div key={i} className="text-emerald-800 flex items-start gap-1 leading-snug">
                                <span className="text-emerald-500 font-bold">✓</span>
                                <span>{h}</span>
                              </div>
                            ))}
                            {rec.warnings?.slice(0, 1).map((w, i) => (
                              <div key={i} className="text-amber-800 flex items-start gap-1 leading-snug">
                                <AlertTriangle className="w-3 h-3 text-amber-500 flex-shrink-0 mt-0.5" />
                                <span>{w}</span>
                              </div>
                            ))}
                          </div>

                          {/* Footer Buttons */}
                          <div className="pt-2 border-t border-slate-100 flex items-center justify-between gap-2 text-xs">
                            <div className="flex items-center gap-2">
                              <button
                                onClick={() => openInspector('evidence', matchedProfile || null, rec)}
                                className="px-2.5 py-1 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 font-medium transition-colors"
                              >
                                查阅真实评论 ({rec.evidenceRefs?.length || 0})
                              </button>

                              <button
                                onClick={() => handleAddToCompare(rec, matchedProfile)}
                                className="px-2.5 py-1 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 font-medium transition-colors hidden sm:inline"
                              >
                                加入对比
                              </button>
                            </div>

                            <button
                              onClick={() => {
                                setAttachedContext({ type: 'shop', title: rec.title })
                                textareaRef.current?.focus()
                              }}
                              className="inline-flex items-center gap-1 px-3 py-1 rounded-lg bg-slate-900 hover:bg-orange-600 text-white font-medium transition-colors shadow-xs"
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
                  className="p-3.5 rounded-2xl bg-amber-500/10 border border-amber-500/20 text-xs text-amber-900 flex items-center justify-between cursor-pointer hover:bg-amber-500/15 transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <AlertTriangle className="w-4 h-4 text-amber-600 flex-shrink-0" />
                    <span className="font-semibold">
                      已识别出 {controversies.length} 项评论分歧争议（如排队、口味偏咸等）
                    </span>
                  </div>
                  <span className="text-amber-700 font-medium flex items-center gap-1">
                    <span>查看争议双方详情</span>
                    <ChevronRight className="w-3.5 h-3.5" />
                  </span>
                </div>
              )}

              {/* 5. Follow-up Quick Chips */}
              <div className="pt-2">
                <div className="flex flex-wrap items-center gap-1.5 text-xs">
                  <span className="text-slate-400 text-[11px] flex items-center gap-1 mr-1">
                    <Sparkles className="w-3 h-3 text-orange-500" />
                    快捷建议：
                  </span>
                  {suggestions.map((sug, i) => (
                    <button
                      key={i}
                      onClick={() => handleSendMessage(sug)}
                      className="px-2.5 py-1 rounded-xl bg-slate-100 hover:bg-orange-50 hover:text-orange-700 text-slate-700 transition-colors"
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

        {/* Sticky Chat Composer at Bottom */}
        <div className="p-4 border-t border-slate-100 bg-white/95 backdrop-blur-md">
          <div className="max-w-3xl mx-auto space-y-2">
            {/* Context attachment chip */}
            {attachedContext && (
              <div className="flex items-center justify-between bg-orange-50 border border-orange-200 px-3 py-1 rounded-xl text-xs text-orange-900 w-fit">
                <span className="font-semibold flex items-center gap-1.5">
                  <Tag className="w-3 h-3 text-orange-600" />
                  针对店铺：{attachedContext.title}
                </span>
                <button onClick={() => setAttachedContext(null)} className="ml-2 hover:text-orange-600">
                  <X className="w-3 h-3" />
                </button>
              </div>
            )}

            {/* Input box */}
            <div className="flex items-end gap-2 bg-slate-100/80 focus-within:bg-white focus-within:ring-2 focus-within:ring-orange-500/20 focus-within:border-orange-500 border border-slate-200 rounded-2xl p-2 transition-all">
              <textarea
                ref={textareaRef}
                rows={1}
                placeholder={
                  attachedContext
                    ? `向 Agent 追问关于“${attachedContext.title}”的具体细节（如排队、避雷菜品、人均）...`
                    : '用自然语言继续输入需求，例如：“只看步行20分钟内”、“第一家排队有多严重”...'
                }
                value={inputText}
                onChange={(e) => setInputText(e.target.value)}
                onCompositionStart={() => setIsComposing(true)}
                onCompositionEnd={() => setIsComposing(false)}
                onKeyDown={handleKeyDown}
                disabled={isRunning}
                className="flex-1 bg-transparent resize-none p-2 text-xs sm:text-sm text-slate-900 placeholder-slate-400 focus:outline-none max-h-32 leading-relaxed"
              />

              {isRunning ? (
                <button
                  onClick={stop}
                  className="p-2.5 rounded-xl bg-rose-50 text-rose-600 hover:bg-rose-100 transition-colors"
                  title="停止调查"
                >
                  <StopCircle className="w-4 h-4" />
                </button>
              ) : (
                <button
                  onClick={() => handleSendMessage()}
                  disabled={!inputText.trim()}
                  className="p-2.5 rounded-xl bg-slate-900 hover:bg-orange-600 text-white transition-colors disabled:opacity-30 disabled:hover:bg-slate-900 shadow-xs"
                  title="发送需求"
                >
                  <Send className="w-4 h-4" />
                </button>
              )}
            </div>
          </div>
        </div>
      </main>

      {/* 3. Right Inspector Slide-over (Evidence, Controversies, Shop Profiles) */}
      <aside
        className={`${
          rightPanelOpen ? 'w-full md:w-[440px]' : 'w-0 hidden md:flex md:w-0'
        } border-l border-slate-200 bg-white flex flex-col h-full z-20 transition-all duration-200 overflow-hidden flex-shrink-0 shadow-lg md:shadow-none`}
      >
        {/* Inspector Header & Tabs */}
        <div className="p-3 border-b border-slate-200 bg-slate-50 flex items-center justify-between">
          <div className="flex items-center gap-1 text-xs">
            <button
              onClick={() => setRightPanelTab('evidence')}
              className={`px-3 py-1.5 rounded-xl font-semibold transition-colors ${
                rightPanelTab === 'evidence'
                  ? 'bg-white text-orange-700 shadow-xs'
                  : 'text-slate-500 hover:text-slate-800'
              }`}
            >
              评论证据 ({evidenceItems.length})
            </button>
            <button
              onClick={() => setRightPanelTab('controversies')}
              className={`px-3 py-1.5 rounded-xl font-semibold transition-colors ${
                rightPanelTab === 'controversies'
                  ? 'bg-white text-orange-700 shadow-xs'
                  : 'text-slate-500 hover:text-slate-800'
              }`}
            >
              争议焦点 ({controversies.length})
            </button>
            <button
              onClick={() => setRightPanelTab('profile')}
              className={`px-3 py-1.5 rounded-xl font-semibold transition-colors ${
                rightPanelTab === 'profile'
                  ? 'bg-white text-orange-700 shadow-xs'
                  : 'text-slate-500 hover:text-slate-800'
              }`}
            >
              店铺档案
            </button>
          </div>

          <button
            onClick={() => setRightPanelOpen(false)}
            className="p-1 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-200 transition-colors"
            title="关闭右侧面板"
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
              <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
                大众点评店铺事实档案
              </div>
              {(() => {
                const p = selectedProfile || (profiles.length > 0 ? profiles[0] : null)
                if (!p) {
                  return (
                    <div className="p-8 text-center text-xs text-slate-400">
                      请在推荐列表中点击某家店铺以查看其大众点评结构化档案
                    </div>
                  )
                }
                return (
                  <div className="bg-slate-50 p-4 rounded-2xl border border-slate-200/90 space-y-3 text-xs">
                    <div className="font-bold text-slate-900 text-base">{p.name || '精选门店'}</div>
                    {p.address && (
                      <div className="flex items-start gap-2 text-slate-700">
                        <MapPin className="w-3.5 h-3.5 text-slate-400 mt-0.5 flex-shrink-0" />
                        <span>{p.address}</span>
                      </div>
                    )}
                    {p.openingHours && (
                      <div className="flex items-start gap-2 text-slate-700">
                        <Clock className="w-3.5 h-3.5 text-slate-400 mt-0.5 flex-shrink-0" />
                        <span>营业时间：{p.openingHours}</span>
                      </div>
                    )}
                    <div className="pt-2 border-t border-slate-200 flex items-center justify-between text-slate-600">
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
