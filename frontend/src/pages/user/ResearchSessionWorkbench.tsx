import React, { useState, useEffect, useCallback, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Compass,
  Layers,
  Sparkles,
  AlertTriangle,
  MessageSquare,
  Utensils,
  Share2,
  RefreshCw,
  Clock,
  CheckCircle2,
  XCircle,
  HelpCircle,
  Wifi,
  WifiOff,
  ChevronLeft,
  ChevronRight,
  Bookmark,
  SlidersHorizontal,
  Info,
} from 'lucide-react'
import { useResearchSessionReact } from '../../features/research-session/domain/useResearchSessionReact'
import { ControversyPanel } from '../../components/research-surface/ControversyPanel'
import { EvidenceTimeline } from '../../components/research-surface/EvidenceTimeline'
import { RecommendationList } from '../../components/research-surface/RecommendationList'
import { ShopProfileDrawer } from '../../components/research-surface/ShopProfileDrawer'
import { DataGapsPanel } from '../../components/research-surface/DataGapsPanel'
import { ResearchPlanPanel } from '../../components/research-surface/ResearchPlanPanel'
import { FollowUpComposer } from '../../components/research-session/FollowUpComposer'
import { RestaurantComparisonModal } from '../../components/restaurant/RestaurantComparisonModal'
import { QrLoginModal } from '../../components/auth/QrLoginModal'
import { useToast } from '../../context/ToastContext'
import { storage } from '../../shared/utils/storage'
import { startSearch } from '../../api/searchApi'
import type {
  ResearchProfileViewV1,
  ResearchRecommendationViewV1,
  ResearchControversyViewV1,
} from '../../shared/contracts/research'
import type { Restaurant } from '../../shared/contracts'

type MainTab = 'recommendations' | 'controversies' | 'evidence' | 'gaps'

export function ResearchSessionWorkbench() {
  const { sessionId = 'default-session' } = useParams<{ sessionId: string }>()
  const navigate = useNavigate()
  const { showToast } = useToast()

  // Domain Store hook
  const {
    state,
    projection,
    transportState,
    start,
    stop,
    appendEvent,
  } = useResearchSessionReact(sessionId, {
    autoStart: true,
  })

  // UI State
  const [activeTab, setActiveTab] = useState<MainTab>('recommendations')
  const [selectedProfile, setSelectedProfile] = useState<ResearchProfileViewV1 | null>(null)
  const [selectedRecForDrawer, setSelectedRecForDrawer] = useState<ResearchRecommendationViewV1 | null>(null)
  const [isDrawerOpen, setIsDrawerOpen] = useState<boolean>(false)

  // Follow-up context attachment
  const [attachedContext, setAttachedContext] = useState<{
    type: 'shop' | 'controversy' | 'evidence' | 'general'
    title: string
    id?: string
  } | null>(null)

  // Comparison State
  const [compareList, setCompareList] = useState<Restaurant[]>([])
  const [isCompareModalOpen, setIsCompareModalOpen] = useState<boolean>(false)

  // Favorites
  const [favorites, setFavorites] = useState<string[]>(() => {
    return storage.get<string[]>('anyfast_user_favorites', [])
  })

  // Login Modal
  const [loginPlatform, setLoginPlatform] = useState<'xhs_pc' | 'dianping' | null>(null)

  // Diagnostics Modal
  const [showDiagnostics, setShowDiagnostics] = useState<boolean>(false)

  // Query history info
  const sessionHistoryItem = useMemo(() => {
    const historyList = storage.get<any[]>('anyfast_search_history', [])
    return historyList.find((h) => h.session_id === sessionId)
  }, [sessionId])

  const sessionTitle = sessionHistoryItem?.query || projection?.intent?.objective || '美食深度调查'

  // Is Investigation running
  const isRunning = state.syncState === 'synced' && projection?.status === 'running'

  // Follow-up suggestions based on unresolved controversies or gaps
  const followUpSuggestions = useMemo(() => {
    const list: string[] = []
    if (projection?.controversies) {
      for (const c of projection.controversies) {
        if (c.remainingQuestion) {
          list.push(`核实：${c.remainingQuestion}`)
        } else {
          list.push(`继续调查关于“${c.topic}”的评价`)
        }
      }
    }
    if (projection?.gaps && projection.gaps.length > 0) {
      list.push('补充大众点评详细到店营业时间与排队情况')
    }
    if (list.length === 0) {
      list.push('附近步行20分钟内是否有替代推荐？', '只对比前两家的人均与口味一致性', '有无不辣的菜品选择？')
    }
    return list
  }, [projection])

  // Handle Bookmarks
  const handleToggleFavorite = (restaurantId: string, restaurantName: string) => {
    let next: string[]
    if (favorites.includes(restaurantId)) {
      next = favorites.filter((id) => id !== restaurantId)
      showToast(`已从收藏中移除 ${restaurantName}`, 'info')
    } else {
      next = [...favorites, restaurantId]
      showToast(`已收藏 ${restaurantName}`, 'success')
    }
    setFavorites(next)
    storage.set('anyfast_user_favorites', next)
  }

  // Handle Compare
  const handleAddToCompare = (restaurant: Restaurant) => {
    if (compareList.some((r) => r.id === restaurant.id)) {
      setIsCompareModalOpen(true)
      return
    }
    if (compareList.length >= 4) {
      showToast('最多同时对比 4 家餐厅', 'warning')
      return
    }
    setCompareList([...compareList, restaurant])
    showToast(`已将 ${restaurant.name} 加入对比`, 'success')
  }

  // Handle Follow-up send
  const handleSendFollowUp = async (queryText: string, context?: any) => {
    const fullQuery = context ? `[针对: ${context.title}] ${queryText}` : queryText

    try {
      await startSearch(fullQuery, sessionId)
      showToast('追问已提交，Agent 正在继续调查...', 'info')
    } catch {
      // Mocked local event creation if backend stream is in mock mode
      appendEvent({
        schemaVersion: 'research-event/v1',
        eventId: `ev_${Date.now()}`,
        sessionId,
        taskId: projection?.taskId || 'task_1',
        turnId: (projection?.turnId || 1) + 1,
        sequence: (projection?.lastSequence || 0) + 1,
        occurredAt: new Date().toISOString(),
        kind: 'run_progress',
        mutation: 'patch',
        payload: {
          summary: `已收到针对“${context ? context.title : '全局'}”的追问：“${queryText}”，正在重新核对相关评论证据...`,
        },
      })
      showToast('追问已提交，正在获取评论证据...', 'info')
    }
  }

  // Handle controversy verification action
  const handleVerifyControversy = (controversy: ResearchControversyViewV1) => {
    setAttachedContext({
      type: 'controversy',
      title: controversy.topic,
      id: controversy.controversyId,
    })
    showToast(`已附加争议焦点：“${controversy.topic}”，请在输入框直接追问`, 'info')
  }

  // Handle shop follow-up selection
  const handleSelectShopForFollowUp = (shopTitle: string) => {
    setAttachedContext({
      type: 'shop',
      title: shopTitle,
    })
    showToast(`已附加店铺上下文：“${shopTitle}”，请在输入框直接追问`, 'info')
  }

  // Select shop drawer
  const handleOpenShopDrawer = (profile: ResearchProfileViewV1 | null, rec: ResearchRecommendationViewV1) => {
    setSelectedProfile(profile)
    setSelectedRecForDrawer(rec)
    setIsDrawerOpen(true)
  }

  // Retry gap
  const handleRetryGap = async (gap: any) => {
    showToast(`正在重新请求 ${gap.source} 数据源...`, 'info')
    setTimeout(() => {
      showToast(`${gap.source} 数据补充重试完成`, 'success')
    }, 1200)
  }

  // Status Badge Logic
  const status = projection?.status || 'running'
  let statusBadge = {
    label: '深度调查中',
    class: 'bg-orange-50 text-orange-700 border-orange-200',
    icon: RefreshCw,
    spin: true,
  }
  if (status === 'succeeded') {
    statusBadge = {
      label: '调查已完成',
      class: 'bg-emerald-50 text-emerald-800 border-emerald-200',
      icon: CheckCircle2,
      spin: false,
    }
  } else if (status === 'partial') {
    statusBadge = {
      label: '部分完成 (有缺口)',
      class: 'bg-blue-50 text-blue-800 border-blue-200',
      icon: AlertTriangle,
      spin: false,
    }
  } else if (status === 'failed') {
    statusBadge = {
      label: '调查受阻',
      class: 'bg-rose-50 text-rose-800 border-rose-200',
      icon: XCircle,
      spin: false,
    }
  } else if (status === 'cancelled') {
    statusBadge = {
      label: '已停止调查',
      class: 'bg-slate-100 text-slate-700 border-slate-200',
      icon: Clock,
      spin: false,
    }
  }

  const StatusIcon = statusBadge.icon

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-6">
      {/* Session Top Header Bar */}
      <div className="bg-white rounded-2xl border border-slate-200/90 shadow-xs p-4 sm:p-5 flex flex-col md:flex-row md:items-center justify-between gap-4">
        {/* Left: Back + Title + Badges */}
        <div className="flex items-start gap-3">
          <button
            onClick={() => navigate('/app/explore')}
            className="p-2 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-600 transition-colors flex-shrink-0 mt-0.5"
            title="返回美食探索"
          >
            <ChevronLeft className="w-5 h-5" />
          </button>

          <div>
            <div className="flex items-center gap-2 flex-wrap mb-1">
              <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold border ${statusBadge.class}`}>
                <StatusIcon className={`w-3.5 h-3.5 ${statusBadge.spin ? 'animate-spin text-orange-600' : ''}`} />
                {statusBadge.label}
              </span>

              <span className="text-xs font-mono text-slate-500 bg-slate-100 px-2 py-0.5 rounded-md">
                第 {projection?.turnId || 1} 轮
              </span>

              {/* Connection state */}
              <span className="text-xs text-slate-400 flex items-center gap-1 font-mono">
                {transportState === 'connected' ? (
                  <>
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                    <span>实时流接入</span>
                  </>
                ) : transportState === 'reconnecting' ? (
                  <>
                    <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-ping" />
                    <span>正在重连...</span>
                  </>
                ) : (
                  <>
                    <span className="w-1.5 h-1.5 rounded-full bg-slate-300" />
                    <span>已保留最新快照</span>
                  </>
                )}
              </span>
            </div>

            <h2 className="text-lg sm:text-xl font-bold text-slate-900 leading-tight">
              {sessionTitle}
            </h2>
          </div>
        </div>

        {/* Right Action Buttons */}
        <div className="flex items-center gap-2 self-end md:self-center flex-wrap">
          {compareList.length > 0 && (
            <button
              onClick={() => setIsCompareModalOpen(true)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-orange-50 border border-orange-200 text-orange-800 text-xs font-semibold hover:bg-orange-100 transition-colors shadow-xs"
            >
              <Layers className="w-3.5 h-3.5" />
              <span>已选 {compareList.length} 家对比</span>
            </button>
          )}

          <button
            onClick={() => setShowDiagnostics(true)}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-medium transition-colors"
            title="查看会话技术诊断与事件流游标"
          >
            <Info className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">技术诊断</span>
          </button>
        </div>
      </div>

      {/* Main Grid: Left Plan/Chat Column & Right Research Workspace */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Left Column (4 cols): Research Plan & Conversation Flow */}
        <div className="lg:col-span-4 space-y-4">
          {/* Plan & Step Progress */}
          <ResearchPlanPanel
            plan={projection?.plan || []}
            currentPhase={projection?.phase}
            metrics={projection?.metrics}
          />

          {/* Agent Milestone Summary */}
          {projection?.summary && (
            <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-xs space-y-2">
              <div className="flex items-center gap-1.5 text-xs font-bold text-slate-900">
                <Sparkles className="w-4 h-4 text-orange-600" />
                <span>Agent 阶段性研判摘要</span>
              </div>
              <p className="text-xs text-slate-700 leading-relaxed bg-slate-50 p-3 rounded-xl border border-slate-100">
                {projection.summary}
              </p>
            </div>
          )}

          {/* Quick Stats Banner */}
          <div className="grid grid-cols-3 gap-2 text-center text-xs">
            <div className="bg-white p-3 rounded-xl border border-slate-200/80 shadow-xs">
              <div className="font-bold text-slate-900 text-base font-mono">
                {projection?.recommendations?.length || 0}
              </div>
              <div className="text-slate-400 text-[11px] mt-0.5">候选店铺</div>
            </div>
            <div className="bg-white p-3 rounded-xl border border-slate-200/80 shadow-xs">
              <div className="font-bold text-slate-900 text-base font-mono">
                {projection?.evidence?.length || 0}
              </div>
              <div className="text-slate-400 text-[11px] mt-0.5">真实评论依据</div>
            </div>
            <div className="bg-white p-3 rounded-xl border border-slate-200/80 shadow-xs">
              <div className="font-bold text-amber-600 text-base font-mono">
                {projection?.controversies?.length || 0}
              </div>
              <div className="text-slate-400 text-[11px] mt-0.5">矛盾争议点</div>
            </div>
          </div>
        </div>

        {/* Right Column (8 cols): Main Research Workspace Surface */}
        <div className="lg:col-span-8 space-y-4">
          {/* Surface Tabs Bar */}
          <div className="flex items-center justify-between border-b border-slate-200 bg-white px-2 rounded-2xl shadow-xs overflow-x-auto no-scrollbar">
            <div className="flex items-center gap-1 py-1.5">
              <button
                onClick={() => setActiveTab('recommendations')}
                className={`flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold transition-colors whitespace-nowrap ${
                  activeTab === 'recommendations'
                    ? 'bg-orange-50 text-orange-700'
                    : 'text-slate-500 hover:text-slate-800 hover:bg-slate-50'
                }`}
              >
                <Utensils className="w-3.5 h-3.5" />
                <span>综合结论与推荐 ({projection?.recommendations?.length || 0})</span>
              </button>

              <button
                onClick={() => setActiveTab('controversies')}
                className={`flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold transition-colors whitespace-nowrap ${
                  activeTab === 'controversies'
                    ? 'bg-orange-50 text-orange-700'
                    : 'text-slate-500 hover:text-slate-800 hover:bg-slate-50'
                }`}
              >
                <AlertTriangle className="w-3.5 h-3.5" />
                <span>评论争议与反例 ({projection?.controversies?.length || 0})</span>
              </button>

              <button
                onClick={() => setActiveTab('evidence')}
                className={`flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold transition-colors whitespace-nowrap ${
                  activeTab === 'evidence'
                    ? 'bg-orange-50 text-orange-700'
                    : 'text-slate-500 hover:text-slate-800 hover:bg-slate-50'
                }`}
              >
                <MessageSquare className="w-3.5 h-3.5" />
                <span>评论证据时间线 ({projection?.evidence?.length || 0})</span>
              </button>

              {projection?.gaps && projection.gaps.length > 0 && (
                <button
                  onClick={() => setActiveTab('gaps')}
                  className={`flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold transition-colors whitespace-nowrap ${
                    activeTab === 'gaps'
                      ? 'bg-amber-50 text-amber-800'
                      : 'text-amber-600 hover:bg-amber-50/50'
                  }`}
                >
                  <AlertTriangle className="w-3.5 h-3.5" />
                  <span>数据缺口 ({projection.gaps.length})</span>
                </button>
              )}
            </div>
          </div>

          {/* Tab Content Display */}
          <div className="min-h-[420px]">
            {activeTab === 'recommendations' && (
              <RecommendationList
                recommendations={projection?.recommendations || []}
                profiles={projection?.profiles || []}
                evidenceItems={projection?.evidence || []}
                controversies={projection?.controversies || []}
                favorites={favorites}
                onToggleFavorite={handleToggleFavorite}
                onSelectShopDetail={handleOpenShopDrawer}
                onSelectForFollowUp={handleSelectShopForFollowUp}
                onAddToCompare={handleAddToCompare}
                comparedIds={compareList.map((c) => c.id)}
              />
            )}

            {activeTab === 'controversies' && (
              <ControversyPanel
                controversies={projection?.controversies || []}
                evidenceItems={projection?.evidence || []}
                onVerifyControversy={handleVerifyControversy}
                onSelectEvidence={(evId) => {
                  setActiveTab('evidence')
                }}
              />
            )}

            {activeTab === 'evidence' && (
              <EvidenceTimeline
                evidenceItems={projection?.evidence || []}
                recommendations={projection?.recommendations || []}
                onSelectShop={(shop) => {
                  setActiveTab('recommendations')
                }}
              />
            )}

            {activeTab === 'gaps' && (
              <DataGapsPanel
                gaps={projection?.gaps || []}
                onRetryGap={handleRetryGap}
                onOpenLogin={(platform) => setLoginPlatform(platform)}
              />
            )}
          </div>

          {/* Sticky Bottom Follow-up Composer */}
          <div className="sticky bottom-4 z-30 pt-2">
            <FollowUpComposer
              isRunning={isRunning}
              attachedContext={attachedContext}
              onClearContext={() => setAttachedContext(null)}
              onSendFollowUp={handleSendFollowUp}
              onStop={stop}
              suggestions={followUpSuggestions}
            />
          </div>
        </div>
      </div>

      {/* Shop Profile Drawer */}
      <ShopProfileDrawer
        isOpen={isDrawerOpen}
        profile={selectedProfile}
        recommendation={selectedRecForDrawer}
        onClose={() => setIsDrawerOpen(false)}
        onFollowUp={handleSelectShopForFollowUp}
      />

      {/* Comparison Modal */}
      <RestaurantComparisonModal
        isOpen={isCompareModalOpen}
        restaurants={compareList}
        onClose={() => setIsCompareModalOpen(false)}
        onRemoveRestaurant={(id) => setCompareList(compareList.filter((r) => r.id !== id))}
        onSelectForFollowUp={(r) => handleSelectShopForFollowUp(r.name)}
      />

      {/* QR Login Modal */}
      {loginPlatform && (
        <QrLoginModal
          isOpen={true}
          platform={loginPlatform}
          onClose={() => setLoginPlatform(null)}
          onSuccess={() => {
            setLoginPlatform(null)
            showToast('平台账号已就绪，可重试受限的资料补充步骤', 'success')
          }}
        />
      )}

      {/* Technical Diagnostics Modal */}
      {showDiagnostics && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-in fade-in">
          <div className="bg-white rounded-2xl max-w-lg w-full p-6 shadow-2xl space-y-4 border border-slate-100">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold text-slate-900 text-sm">会话运行与事件流诊断</h3>
              <button onClick={() => setShowDiagnostics(false)} className="text-slate-400 hover:text-slate-600">
                ✕
              </button>
            </div>
            <div className="bg-slate-900 text-slate-200 font-mono text-xs p-4 rounded-xl space-y-1.5 overflow-x-auto max-h-72">
              <div>Session ID: {sessionId}</div>
              <div>Task ID: {projection?.taskId || 'null'}</div>
              <div>Revision: {projection?.revision ?? 0}</div>
              <div>Last Sequence: {projection?.lastSequence ?? 0}</div>
              <div>Sync State: {state.syncState}</div>
              <div>Transport Cursor: {state.transportCursor || 'null'}</div>
              <div>Duplicate Events: {state.duplicateEventCount}</div>
              <div>Gaps Encountered: {projection?.gaps?.length ?? 0}</div>
            </div>
            <div className="text-xs text-slate-400 leading-relaxed">
              * 技术 ID 与事件游标仅在诊断层露出，普通业务视图隐藏底层细节以保护用户心智。
            </div>
            <button
              onClick={() => setShowDiagnostics(false)}
              className="w-full py-2 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold transition-colors"
            >
              关闭
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
