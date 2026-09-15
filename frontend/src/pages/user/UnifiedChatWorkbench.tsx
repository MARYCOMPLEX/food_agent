import React, { useState, useEffect, useRef, useMemo } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Layout,
  Button,
  Input,
  Card,
  Tag,
  Badge,
  Avatar,
  Space,
  Typography,
  Collapse,
  Timeline,
  Drawer,
  Tabs,
  Select,
  Tooltip,
  Alert,
  List,
  Flex,
  Divider,
} from 'antd'
import {
  PlusOutlined,
  SendOutlined,
  ArrowUpOutlined,
  StopOutlined,
  LoadingOutlined,
  DeleteOutlined,
  MessageOutlined,
  ClockCircleOutlined,
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  EnvironmentOutlined,
  ShopOutlined,
  StarOutlined,
  StarFilled,
  DiffOutlined,
  CopyOutlined,
  LikeOutlined,
  DislikeOutlined,
  ReloadOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  ControlOutlined,
  AuditOutlined,
  GlobalOutlined,
  ArrowRightOutlined,
  FileTextOutlined,
  RobotOutlined,
  CheckOutlined,
} from '@ant-design/icons'
import { useResearchSessionReact } from '../../features/research-session/domain/useResearchSessionReact'
import { EvidenceTimeline } from '../../components/research-surface/EvidenceTimeline'
import { ControversyPanel } from '../../components/research-surface/ControversyPanel'
import { RestaurantComparisonModal } from '../../components/restaurant/RestaurantComparisonModal'
import { ShopProfileDrawer } from '../../components/research-surface/ShopProfileDrawer'
import { QrLoginModal } from '../../components/auth/QrLoginModal'
import { useToast } from '../../context/ToastContext'
import { storage } from '../../shared/utils/storage'
import { apiGet, apiPost } from '../../api/client'
import { startSearch } from '../../api/searchApi'
import { platformAccountsApi } from '../../features/platform-accounts/api/platformAccountsApi'
import {
  DEMO_CD_HOTPOT_PROJECTION,
  DEMO_GZ_TEA_PROJECTION,
} from '../../features/research-session/domain/demoProjections'
import type {
  ResearchProfileViewV1,
  ResearchRecommendationViewV1,
  ResearchControversyViewV1,
} from '../../shared/contracts/research'
import type { Restaurant } from '../../shared/contracts'

export interface ChatTurn {
  id: string
  turnId: number
  userMessage: {
    content: string
    attachedContext?: { type: 'shop' | 'controversy'; title: string } | null
    createdAt: string
  }
  assistantMessage: {
    summary: string
    plan?: Array<{
      id: string
      label: string
      status: 'loading' | 'running' | 'succeeded' | 'failed' | 'idle'
      detail?: string
    }>
    recommendations?: any[]
    controversies?: any[]
    profiles?: any[]
    evidence?: any[]
    isRunning?: boolean
    statusMessage?: string
    error?: string
    createdAt: string
  }
}

type RightPanelTab = 'evidence' | 'controversies' | 'profile'

export function UnifiedChatWorkbench() {
  const { sessionId: routeSessionId } = useParams<{ sessionId?: string }>()
  const navigate = useNavigate()
  const { showToast } = useToast()

  // Current session ID (clean new session by default)
  const [currentSessionId, setCurrentSessionId] = useState<string>(() => {
    return routeSessionId || ''
  })

  // Default snapshot (only used if explicitly navigating to a demo URL)
  const defaultSnapshot = useMemo(() => {
    if (routeSessionId === 'session_demo_cd_hotpot') return DEMO_CD_HOTPOT_PROJECTION
    if (routeSessionId === 'session_demo_gz_tea') return DEMO_GZ_TEA_PROJECTION
    return null
  }, [routeSessionId])

  // History sessions list (starts empty, only stores real user queries)
  const [historyList, setHistoryList] = useState<any[]>(() => {
    return storage.get<any[]>('food_agent_search_history', [])
  })

  // Sequential multi-turn dialogue state
  const [sessionTurns, setSessionTurns] = useState<ChatTurn[]>([])
  const activeAbortRef = useRef<AbortController | null>(null)
  const isSendingRef = useRef(false)

  // Whether current session is a brand-new, unstarted draft session
  const isNewSession = useMemo(() => {
    if (!currentSessionId && sessionTurns.length === 0) return true
    return false
  }, [currentSessionId, sessionTurns.length])

  // Research session hook (keeps demo projections compatible)
  const {
    state,
    projection,
    stop,
    appendEvent,
    initializeSnapshot,
  } = useResearchSessionReact(currentSessionId, {
    snapshot: defaultSnapshot,
    autoStart: Boolean(defaultSnapshot),
  })

  // UI States
  const [sidebarOpen, setSidebarOpen] = useState<boolean>(true)
  const [rightPanelOpen, setRightPanelOpen] = useState<boolean>(false)
  const [rightPanelTab, setRightPanelTab] = useState<RightPanelTab>('evidence')
  const [selectedProfile, setSelectedProfile] = useState<ResearchProfileViewV1 | null>(null)
  const [selectedRec, setSelectedRec] = useState<ResearchRecommendationViewV1 | null>(null)
  const [isProfileDrawerOpen, setIsProfileDrawerOpen] = useState<boolean>(false)

  // Model Selection
  const [modelOptions, setModelOptions] = useState<Array<{
    value: string
    label: string
    is_default: boolean
    provider?: string
    model_id?: string
  }>>([])
  const [selectedModel, setSelectedModel] = useState<string>('')

  useEffect(() => {
    let isMounted = true
    apiGet('/v1/chat/models')
      .then((res: any) => {
        if (!isMounted) return
        const list = res?.data || res || []
        if (Array.isArray(list) && list.length > 0) {
          setModelOptions(list)
          const defaultOption = list.find((m: any) => m.is_default) || list[0]
          setSelectedModel(defaultOption.value)
        } else {
          setModelOptions([])
          setSelectedModel('')
        }
      })
      .catch(() => {
        if (!isMounted) return
        setModelOptions([])
        setSelectedModel('')
      })
    return () => {
      isMounted = false
    }
  }, [])

  // Registered MCP Data Sources (Dynamic from DB)
  const [mcpServices, setMcpServices] = useState<Array<{
    service_id: string
    name: string
    base_url: string
    mcp_url: string
    protocol: string
    channels?: string[]
    is_active: boolean
    health_status?: string
  }>>([])

  useEffect(() => {
    let isMounted = true
    apiGet('/v1/platform/ops/mcp-services')
      .then((res: any) => {
        if (!isMounted) return
        const list = res?.data || res || []
        if (Array.isArray(list)) {
          setMcpServices(list)
        } else {
          setMcpServices([])
        }
      })
      .catch(() => {
        if (!isMounted) return
        setMcpServices([])
      })
    return () => {
      isMounted = false
    }
  }, [])

  // Follow-up context
  const [attachedContext, setAttachedContext] = useState<{
    type: 'shop' | 'controversy'
    title: string
  } | null>(null)

  // Text Composer
  const [inputText, setInputText] = useState<string>('')
  const [isInputFocused, setIsInputFocused] = useState<boolean>(false)
  const [isComposing, setIsComposing] = useState<boolean>(false)
  const textareaRef = useRef<any>(null)
  const chatBottomRef = useRef<HTMLDivElement | null>(null)

  // Feedback state
  const [hasCopied, setHasCopied] = useState<boolean>(false)
  const [feedbackRating, setFeedbackRating] = useState<'up' | 'down' | null>(null)

  // Comparison & Favorites
  const [compareList, setCompareList] = useState<Restaurant[]>([])
  const [isCompareModalOpen, setIsCompareModalOpen] = useState<boolean>(false)
  const [favorites, setFavorites] = useState<string[]>(() =>
    storage.get<string[]>('food_agent_user_favorites', []),
  )

  // Platform Accounts & QR Modal
  const [accounts, setAccounts] = useState(platformAccountsApi.getLocalAccounts())
  const [loginModalPlatform, setLoginModalPlatform] = useState<'xhs_pc' | 'dianping' | null>(null)

  // Synchronize route
  useEffect(() => {
    if (routeSessionId && routeSessionId !== currentSessionId) {
      setCurrentSessionId(routeSessionId)
    }
  }, [routeSessionId, currentSessionId])

  // Restore turns when session changes
  useEffect(() => {
    if (!currentSessionId) {
      setSessionTurns([])
      return
    }

    // 1. Check localStorage first
    const saved = storage.get<ChatTurn[]>(`food_agent_turns_${currentSessionId}`, [])
    if (saved && saved.length > 0) {
      const cleaned = saved.map((t) => ({
        ...t,
        assistantMessage: {
          ...t.assistantMessage,
          isRunning: false,
          statusMessage: undefined,
          plan: (t.assistantMessage?.plan || [])
            .filter((s) => s.id !== 'thinking')
            .map((s) => (s.status === 'running' ? { ...s, status: 'succeeded' as const } : s)),
        },
      }))
      setSessionTurns(cleaned)
      storage.set(`food_agent_turns_${currentSessionId}`, cleaned)
      return
    }

    // 2. Demo snapshot
    if (currentSessionId === 'session_demo_cd_hotpot' || currentSessionId === 'session_demo_gz_tea') {
      const demo = currentSessionId === 'session_demo_cd_hotpot' ? DEMO_CD_HOTPOT_PROJECTION : DEMO_GZ_TEA_PROJECTION
      const demoTurn: ChatTurn = {
        id: `turn_demo_${currentSessionId}`,
        turnId: 1,
        userMessage: {
          content: demo.intent?.objective || '探索特色美食',
          createdAt: new Date().toISOString(),
        },
        assistantMessage: {
          summary: demo.summary || '',
          plan: (demo.plan || []).map((s: any) => ({
            id: s.stepId || s.id,
            label: s.label,
            status: (s.status === 'completed' ? 'succeeded' : s.status) || 'succeeded',
            detail: s.detail,
          })),
          recommendations: demo.recommendations as any,
          controversies: demo.controversies as any,
          profiles: demo.profiles as any,
          evidence: demo.evidence as any,
          isRunning: false,
          createdAt: new Date().toISOString(),
        },
      }
      setSessionTurns([demoTurn])
      storage.set(`food_agent_turns_${currentSessionId}`, [demoTurn])
      return
    }

    // 3. Fallback: recover turns from backend
    let isCancelled = false
    apiPost<any>('/v1/search/', { sessionId: currentSessionId })
      .then((res: any) => {
        if (isCancelled) return
        const d = res?.data || res
        if (d?.turns && Array.isArray(d.turns) && d.turns.length > 0) {
          const recovered: ChatTurn[] = d.turns.map((t: any, idx: number) => ({
            id: `turn_rec_${t.turnId || idx + 1}`,
            turnId: t.turnId || idx + 1,
            userMessage: {
              content: t.query || '美食探店需求',
              createdAt: t.createdAt || new Date().toISOString(),
            },
            assistantMessage: {
              summary: t.summary || '',
              recommendations: (t.restaurants || []).map((r: any, rIdx: number) => ({
                recommendationId: r.id || `rec_${rIdx + 1}`,
                title: r.name || r.title,
                rank: rIdx + 1,
                summary: r.one_liner || r.summary || '',
                highlights: r.features || r.highlights || [],
                warnings: r.warnings || [],
                mustTry: r.must_try || [],
                score: r.score,
                confidence: r.confidence,
              })),
              profiles: (t.restaurants || []).map((r: any) => ({
                profileId: r.id,
                name: r.name || r.title,
                averagePrice: r.cost_per_person || r.price,
                address: r.location || r.address,
                tags: r.tags || [],
                dishRecommendations: r.must_try?.map((m: any) => typeof m === 'string' ? m : (m?.name || '')) || [],
              })),
              isRunning: false,
              createdAt: t.createdAt || new Date().toISOString(),
            },
          }))
          setSessionTurns(recovered)
          storage.set(`food_agent_turns_${currentSessionId}`, recovered)
        } else if (d?.summary || (d?.restaurants && d.restaurants.length > 0)) {
          const singleTurn: ChatTurn = {
            id: `turn_rec_1`,
            turnId: 1,
            userMessage: {
              content: d.query || historyList.find((h) => h.session_id === currentSessionId)?.query || '美食探店需求',
              createdAt: new Date().toISOString(),
            },
            assistantMessage: {
              summary: d.summary || '',
              recommendations: (d.restaurants || []).map((r: any, rIdx: number) => ({
                recommendationId: r.id || `rec_${rIdx + 1}`,
                title: r.name || r.title,
                rank: rIdx + 1,
                summary: r.one_liner || r.summary || '',
                highlights: r.features || r.highlights || [],
                warnings: r.warnings || [],
                mustTry: r.must_try || [],
                score: r.score,
                confidence: r.confidence,
              })),
              profiles: (d.restaurants || []).map((r: any) => ({
                profileId: r.id,
                name: r.name || r.title,
                averagePrice: r.cost_per_person || r.price,
                address: r.location || r.address,
                tags: r.tags || [],
                dishRecommendations: r.must_try?.map((m: any) => typeof m === 'string' ? m : (m?.name || '')) || [],
              })),
              isRunning: false,
              createdAt: new Date().toISOString(),
            },
          }
          setSessionTurns([singleTurn])
          storage.set(`food_agent_turns_${currentSessionId}`, [singleTurn])
        }
      })
      .catch(() => {
        // Silently ignore if session is new or not found
      })

    return () => {
      isCancelled = true
    }
  }, [currentSessionId])

  // Auto scroll chat
  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [sessionTurns])

  // Is investigation running
  const isRunning = useMemo(() => {
    return sessionTurns.some((t) => t.assistantMessage.isRunning)
  }, [sessionTurns])

  // Current session query title
  const currentQuery = useMemo(() => {
    const found = historyList.find((h) => h.session_id === currentSessionId)
    return found?.query || sessionTurns[0]?.userMessage?.content || '美食深度调查'
  }, [historyList, currentSessionId, sessionTurns])

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
    if (activeAbortRef.current) {
      activeAbortRef.current.abort()
      activeAbortRef.current = null
    }
    setCurrentSessionId('')
    setSessionTurns([])
    setRightPanelOpen(false)
    setAttachedContext(null)
    setInputText('')
    setFeedbackRating(null)
    navigate('/chat')
  }

  // Switch session
  const handleSelectSession = (sid: string) => {
    if (activeAbortRef.current) {
      activeAbortRef.current.abort()
      activeAbortRef.current = null
    }
    setCurrentSessionId(sid)
    setRightPanelOpen(false)
    setAttachedContext(null)
    setFeedbackRating(null)
    navigate(`/chat/${sid}`)
  }

  // Delete session
  const handleDeleteSession = (sid: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (currentSessionId === sid && activeAbortRef.current) {
      activeAbortRef.current.abort()
      activeAbortRef.current = null
    }
    const next = historyList.filter((h) => h.session_id !== sid)
    setHistoryList(next)
    storage.set('food_agent_search_history', next)
    storage.remove(`food_agent_turns_${sid}`)
    if (currentSessionId === sid) {
      if (next.length > 0 && next[0]) {
        handleSelectSession(next[0].session_id)
      } else {
        handleStartNewChat()
      }
    }
  }

  // Copy response
  const handleCopyResponse = async (summaryText?: string, queryText?: string) => {
    const textToCopy = summaryText
      ? `${queryText ? `${queryText}\n\n` : ''}${summaryText}`
      : `${currentQuery}\n\n${projection?.summary || ''}`
    try {
      await navigator.clipboard.writeText(textToCopy)
      setHasCopied(true)
      showToast('已复制回答内容至剪贴板', 'success')
      setTimeout(() => setHasCopied(false), 2000)
    } catch {
      showToast('复制失败，请手动选择文本', 'warning')
    }
  }

  // Stop running generation
  const handleStop = () => {
    if (activeAbortRef.current) {
      activeAbortRef.current.abort()
      activeAbortRef.current = null
    }
    setSessionTurns((prev) => {
      const updated = prev.map((t) =>
        t.assistantMessage.isRunning
          ? {
              ...t,
              assistantMessage: {
                ...t.assistantMessage,
                isRunning: false,
                statusMessage: undefined,
                plan: (t.assistantMessage.plan || [])
                  .filter((s) => s.id !== 'thinking')
                  .map((s) => (s.status === 'running' ? { ...s, status: 'succeeded' as const } : s)),
              },
            }
          : t,
      )
      if (currentSessionId) {
        storage.set(`food_agent_turns_${currentSessionId}`, updated)
      }
      return updated
    })
  }

  // Regenerate / Retry response
  const handleRegenerate = () => {
    if (sessionTurns.length === 0 || isRunning) return
    const lastTurn = sessionTurns[sessionTurns.length - 1]
    if (!lastTurn) return
    const lastQuery = lastTurn.userMessage.content
    setSessionTurns((prev) => prev.slice(0, -1))
    handleSendMessage(lastQuery)
  }

  const handleSseEvent = (
    turnId: string,
    eventName: string,
    data: any,
    sessionId: string,
  ) => {
    setSessionTurns((prev) => {
      const turnIndex = prev.findIndex((t) => t.id === turnId)
      if (turnIndex === -1 || !prev[turnIndex]) return prev

      const currentTurn = prev[turnIndex]!
      const assistant = { ...currentTurn.assistantMessage }

      if (eventName === 'step_start') {
        const stepId = data.step || `step_${Date.now()}`
        const stepMsg = data.message || '进行中...'
        const plan = [...(assistant.plan || []).filter((p) => p.id !== 'thinking')]
        if (Array.isArray(data.steps) && data.steps.length > 0) {
          assistant.plan = data.steps.map((s: any) => ({
            id: s.id || s.stepId || stepId,
            label: s.label || s.message || stepMsg,
            status: s.status === 'done' ? 'succeeded' : (s.status === 'loading' ? 'running' : 'idle'),
            detail: s.message || undefined,
          }))
        } else {
          const existing = plan.findIndex((p) => p.id === stepId)
          if (existing >= 0 && plan[existing]) {
            plan[existing] = {
              id: plan[existing]!.id,
              label: plan[existing]!.label,
              status: 'running',
              detail: stepMsg,
            }
          } else {
            plan.push({ id: stepId, label: stepMsg, status: 'running', detail: stepMsg })
          }
          assistant.plan = plan
        }
      } else if (eventName === 'step_done') {
        const stepId = data.step
        const plan = [...(assistant.plan || []).filter((p) => p.id !== 'thinking')]
        const existing = plan.findIndex((p) => p.id === stepId)
        if (existing >= 0 && plan[existing]) {
          plan[existing] = {
            id: plan[existing]!.id,
            label: plan[existing]!.label,
            status: 'succeeded',
            detail: data.message,
          }
        }
        assistant.plan = plan
      } else if (eventName === 'progress') {
        if (data.message) {
          assistant.statusMessage = data.message
        }
      } else if (eventName === 'restaurant') {
        const currentRecs = [...(assistant.recommendations || [])]
        const currentProfiles = [...(assistant.profiles || [])]
        if (data.name || data.title) {
          const recId = data.id || `rec_${currentRecs.length + 1}`
          if (!currentRecs.some((r) => r.recommendationId === recId || r.title === (data.name || data.title))) {
            currentRecs.push({
              recommendationId: recId,
              title: data.name || data.title,
              rank: currentRecs.length + 1,
              summary: data.one_liner || data.summary || '',
              highlights: data.features || data.highlights || [],
              warnings: data.warnings || [],
              mustTry: data.must_try?.map((m: any) => typeof m === 'string' ? { name: m } : m) || [],
              score: data.score,
              confidence: data.confidence,
            })
            currentProfiles.push({
              profileId: recId,
              name: data.name || data.title,
              averagePrice: data.cost_per_person || data.price,
              address: data.location || data.address,
              tags: data.tags || [],
              dishRecommendations: data.must_try?.map((m: any) => typeof m === 'string' ? m : (m?.name || '')) || [],
            })
            assistant.recommendations = currentRecs
            assistant.profiles = currentProfiles
          }
        }
      } else if (eventName === 'result') {
        if (data.summary) {
          assistant.summary = data.summary
        }
        if (Array.isArray(data.steps)) {
          if (data.steps.length === 0) {
            assistant.plan = []
          } else {
            assistant.plan = data.steps.map((s: any) => ({
              id: s.id || s.stepId,
              label: s.label || s.message,
              status: s.status === 'done' ? 'succeeded' : (s.status === 'loading' ? 'running' : 'idle'),
              detail: s.message,
            }))
          }
        }
        if (Array.isArray(data.restaurants) && data.restaurants.length > 0) {
          assistant.recommendations = data.restaurants.map((r: any, idx: number) => ({
            recommendationId: r.id || `rec_${idx + 1}`,
            title: r.name || r.title,
            rank: idx + 1,
            summary: r.one_liner || r.summary || '',
            highlights: r.features || r.highlights || [],
            warnings: r.warnings || [],
            mustTry: r.must_try?.map((m: any) => typeof m === 'string' ? { name: m } : m) || [],
            score: r.score,
            confidence: r.confidence,
          }))
          assistant.profiles = data.restaurants.map((r: any) => ({
            profileId: r.id,
            name: r.name || r.title,
            averagePrice: r.cost_per_person || r.price,
            address: r.location || r.address,
            tags: r.tags || [],
            dishRecommendations: r.must_try?.map((m: any) => typeof m === 'string' ? m : (m?.name || '')) || [],
          }))
        }
      } else if (eventName === 'done') {
        assistant.isRunning = false
        assistant.statusMessage = undefined
        if (assistant.plan && assistant.plan.length > 0) {
          assistant.plan = assistant.plan
            .filter((s) => s.id !== 'thinking')
            .map((s) => (s.status === 'running' ? { ...s, status: 'succeeded' as const } : s))
        }
      } else if (eventName === 'error') {
        assistant.isRunning = false
        assistant.statusMessage = undefined
        assistant.error = data.error || data.message || '生成失败'
        if (assistant.plan && assistant.plan.length > 0) {
          assistant.plan = assistant.plan
            .filter((s) => s.id !== 'thinking')
            .map((s) => (s.status === 'running' ? { ...s, status: 'failed' as const } : s))
        }
      }

      const nextTurns = [...prev]
      nextTurns[turnIndex] = {
        ...currentTurn,
        assistantMessage: assistant,
      }
      storage.set(`food_agent_turns_${sessionId}`, nextTurns)
      return nextTurns
    })
  }

  const readSseStream = async (sessionId: string, turnId: string, signal: AbortSignal) => {
    try {
      const response = await fetch(`/v1/search/stream/${sessionId}`, {
        headers: {
          Accept: 'text/event-stream',
          'X-Device-Id': storage.get('deviceId', '') || 'default-device',
        },
        signal,
      })

      if (!response.ok) {
        throw new Error(`SSE 状态异常: ${response.status}`)
      }

      const reader = response.body?.getReader()
      if (!reader) return

      const decoder = new TextDecoder('utf-8')
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        let currentEvent = 'message'
        let currentDataLines: string[] = []

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed) {
            if (currentDataLines.length > 0) {
              const rawData = currentDataLines.join('\n')
              let parsed: any = rawData
              try {
                parsed = JSON.parse(rawData)
              } catch {}
              handleSseEvent(turnId, currentEvent, parsed, sessionId)
            }
            currentEvent = 'message'
            currentDataLines = []
            continue
          }
          if (trimmed.startsWith('event:')) {
            currentEvent = trimmed.slice(6).trim()
          } else if (trimmed.startsWith('data:')) {
            currentDataLines.push(line.slice(line.indexOf(':') + 1).trim())
          }
        }
      }

      // Finalize turn running state
      setSessionTurns((prev) => {
        const updated = prev.map((t) =>
          t.id === turnId
            ? {
                ...t,
                assistantMessage: {
                  ...t.assistantMessage,
                  isRunning: false,
                  statusMessage: undefined,
                  plan: (t.assistantMessage.plan || [])
                    .filter((s) => s.id !== 'thinking')
                    .map((s) => (s.status === 'running' ? { ...s, status: 'succeeded' as const } : s)),
                },
              }
            : t,
        )
        storage.set(`food_agent_turns_${sessionId}`, updated)
        return updated
      })
    } catch (err: any) {
      if (err.name === 'AbortError') {
        setSessionTurns((prev) => {
          const updated = prev.map((t) =>
            t.id === turnId
              ? {
                  ...t,
                  assistantMessage: {
                    ...t.assistantMessage,
                    isRunning: false,
                    statusMessage: undefined,
                    plan: (t.assistantMessage.plan || [])
                      .filter((s) => s.id !== 'thinking')
                      .map((s) => (s.status === 'running' ? { ...s, status: 'succeeded' as const } : s)),
                  },
                }
              : t,
          )
          storage.set(`food_agent_turns_${sessionId}`, updated)
          return updated
        })
        return
      }
      throw err
    }
  }

  // Send message
  const handleSendMessage = async (overrideText?: string) => {
    const text = (overrideText || inputText).trim()
    if (!text || isRunning || isSendingRef.current) return
    isSendingRef.current = true

    const fullPrompt = attachedContext
      ? `[针对: ${attachedContext.title}] ${text}`
      : text

    const targetSessionId = currentSessionId || undefined
    const newTurnId = sessionTurns.length + 1
    const newTurn: ChatTurn = {
      id: `turn_${Date.now()}_${newTurnId}`,
      turnId: newTurnId,
      userMessage: {
        content: text,
        attachedContext: attachedContext ? { ...attachedContext } : null,
        createdAt: new Date().toISOString(),
      },
      assistantMessage: {
        summary: '',
        plan: [],
        recommendations: [],
        controversies: [],
        profiles: [],
        evidence: [],
        isRunning: true,
        statusMessage: '正在为您组织回答...',
        createdAt: new Date().toISOString(),
      },
    }

    // Ensure all previous turns are strictly finalized and not running
    const prevTurnsCleaned = sessionTurns.map((t) => ({
      ...t,
      assistantMessage: {
        ...t.assistantMessage,
        isRunning: false,
        statusMessage: undefined,
        plan: (t.assistantMessage.plan || [])
          .filter((s) => s.id !== 'thinking')
          .map((s) => (s.status === 'running' ? { ...s, status: 'succeeded' as const } : s)),
      },
    }))

    const nextTurns = [...prevTurnsCleaned, newTurn]
    setSessionTurns(nextTurns)
    setInputText('')
    setAttachedContext(null)

    const abortController = new AbortController()
    activeAbortRef.current = abortController

    try {
      showToast('已提交需求，Agent 正在分析...', 'info')
      const res: any = await startSearch(fullPrompt, targetSessionId, selectedModel || undefined)
      const data = res?.data || res
      const activeSessionId = data?.sessionId || res?.sessionId || targetSessionId

      if (activeSessionId) {
        if (!historyList.some((h) => h.session_id === activeSessionId)) {
          const newHistoryItem = {
            session_id: activeSessionId,
            query: text,
            created_at: new Date().toISOString(),
          }
          const nextHistory = [newHistoryItem, ...historyList]
          setHistoryList(nextHistory)
          storage.set('food_agent_search_history', nextHistory)
        }
        if (activeSessionId !== currentSessionId) {
          setCurrentSessionId(activeSessionId)
          navigate(`/chat/${activeSessionId}`, { replace: true })
        }
      }

      // Stream events from SSE
      await readSseStream(activeSessionId, newTurn.id, abortController.signal)
    } catch (err: any) {
      if (err.name === 'AbortError') return
      showToast('发起请求失败: ' + (err.message || '后端服务异常'), 'error')
      setSessionTurns((prev) => {
        const updated = prev.map((t) =>
          t.id === newTurn.id
            ? {
                ...t,
                assistantMessage: {
                  ...t.assistantMessage,
                  isRunning: false,
                  statusMessage: undefined,
                  error: err.message || '请求失败',
                },
              }
            : t,
        )
        if (currentSessionId) storage.set(`food_agent_turns_${currentSessionId}`, updated)
        return updated
      })
    } finally {
      isSendingRef.current = false
      if (activeAbortRef.current === abortController) {
        activeAbortRef.current = null
      }
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
  const openInspector = (
    tab: RightPanelTab,
    profile?: ResearchProfileViewV1 | null,
    rec?: ResearchRecommendationViewV1 | null,
  ) => {
    setRightPanelTab(tab)
    if (profile !== undefined) setSelectedProfile(profile)
    if (rec !== undefined) setSelectedRec(rec)
    setRightPanelOpen(true)
  }

  // Open standalone profile drawer
  const openStandaloneProfile = (
    profile: ResearchProfileViewV1 | null,
    rec: ResearchRecommendationViewV1 | null,
  ) => {
    setSelectedProfile(profile)
    setSelectedRec(rec)
    setIsProfileDrawerOpen(true)
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
    storage.set('food_agent_user_favorites', next)
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

  // Recommendations & Active items across turns
  const latestTurnWithData = useMemo(() => {
    for (let i = sessionTurns.length - 1; i >= 0; i--) {
      const t = sessionTurns[i]
      if (!t) continue
      if (
        (t.assistantMessage.recommendations && t.assistantMessage.recommendations.length > 0) ||
        (t.assistantMessage.evidence && t.assistantMessage.evidence.length > 0) ||
        (t.assistantMessage.controversies && t.assistantMessage.controversies.length > 0)
      ) {
        return t
      }
    }
    return sessionTurns[sessionTurns.length - 1] || null
  }, [sessionTurns])

  const recommendations = latestTurnWithData?.assistantMessage?.recommendations || projection?.recommendations || []
  const evidenceItems = latestTurnWithData?.assistantMessage?.evidence || projection?.evidence || []
  const controversies = latestTurnWithData?.assistantMessage?.controversies || projection?.controversies || []
  const profiles = latestTurnWithData?.assistantMessage?.profiles || projection?.profiles || []
  const plan = latestTurnWithData?.assistantMessage?.plan || projection?.plan || []

  return (
    <Layout style={{ height: '100vh', width: '100vw', overflow: 'hidden' }}>
      {/* 1. Left Sider: Ant Design Sider with Menu & Session History */}
      <Layout.Sider
        width={270}
        collapsedWidth={0}
        theme="light"
        collapsible
        collapsed={!sidebarOpen}
        trigger={null}
        style={{
          borderRight: sidebarOpen ? '1px solid #f0f0f0' : 'none',
          display: 'flex',
          flexDirection: 'column',
          height: '100vh',
          overflow: 'hidden',
          transition: 'all 0.2s ease',
        }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
          {/* Sider Header */}
          <div style={{ padding: '16px 14px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid #f5f5f5' }}>
            <Space align="center" size={8}>
              <Avatar
                shape="square"
                size="small"
                icon={<RobotOutlined />}
                style={{ backgroundColor: '#1677ff' }}
              />
              <Typography.Text strong style={{ fontSize: 14 }}>
                Food Agent
              </Typography.Text>
              <Tag color="blue" variant="filled" style={{ fontSize: 11 }}>
                {(selectedModel ? selectedModel.split(/[-_]/)[0] : 'AI')?.toUpperCase() || 'AI'}
              </Tag>
            </Space>
            <Button
              type="text"
              size="small"
              icon={<MenuFoldOutlined />}
              onClick={() => setSidebarOpen(false)}
              title="收起侧边栏"
            />
          </div>

          {/* New Search Button */}
          <div style={{ padding: '12px 14px 8px' }}>
            <Button
              type="primary"
              block
              icon={<PlusOutlined />}
              onClick={handleStartNewChat}
            >
              新建美食调研
            </Button>
          </div>

          {/* Session History List */}
          <div style={{ flex: 1, overflowY: 'auto', padding: '4px 10px' }}>
            <Typography.Text type="secondary" style={{ fontSize: 11, padding: '6px 8px', display: 'block' }}>
              历史对话
            </Typography.Text>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
              {historyList.length === 0 ? (
                <div style={{ padding: '24px 8px', textAlign: 'center' }}>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    暂无历史对话
                  </Typography.Text>
                </div>
              ) : (
                historyList.map((item) => {
                const isSelected = item.session_id === currentSessionId
                return (
                  <div
                    key={item.session_id}
                    onClick={() => handleSelectSession(item.session_id)}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '8px 10px',
                      borderRadius: 8,
                      cursor: 'pointer',
                      background: isSelected ? '#e6f4ff' : 'transparent',
                      transition: 'all 0.15s ease',
                    }}
                    onMouseEnter={(e) => {
                      if (!isSelected) e.currentTarget.style.background = '#f5f5f5'
                    }}
                    onMouseLeave={(e) => {
                      if (!isSelected) e.currentTarget.style.background = 'transparent'
                    }}
                  >
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 8,
                        flex: 1,
                        minWidth: 0,
                        marginRight: 6,
                      }}
                    >
                      <MessageOutlined
                        style={{
                          color: isSelected ? '#1677ff' : '#8c8c8c',
                          fontSize: 13,
                          flexShrink: 0,
                        }}
                      />
                      <Typography.Text
                        ellipsis={{ tooltip: item.query }}
                        style={{
                          fontSize: 12,
                          color: isSelected ? '#1677ff' : '#262626',
                          fontWeight: isSelected ? 500 : 400,
                          width: '100%',
                          lineHeight: 1.4,
                        }}
                      >
                        {item.query}
                      </Typography.Text>
                    </div>

                    <Button
                      type="text"
                      danger
                      size="small"
                      icon={<DeleteOutlined style={{ fontSize: 12 }} />}
                      onClick={(e) => {
                        e.stopPropagation()
                        handleDeleteSession(item.session_id, e)
                      }}
                      title="删除会话"
                      style={{
                        flexShrink: 0,
                        width: 24,
                        height: 24,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        color: isSelected ? '#ff4d4f' : '#bfbfbf',
                        padding: 0,
                      }}
                    />
                  </div>
                )
              }))}
            </div>
          </div>

          {/* Sider Footer */}
          <div style={{ padding: 12, borderTop: '1px solid #f0f0f0' }}>
            <Card size="small" style={{ marginBottom: 8, background: '#fafafa' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                <Typography.Text strong style={{ fontSize: 11 }}>
                  探店数据源 {mcpServices.length > 0 ? `(${mcpServices.length})` : ''}
                </Typography.Text>
                {mcpServices.length > 0 ? (
                  <Tag
                    color={mcpServices.some((s) => s.is_active) ? 'success' : 'warning'}
                    style={{ margin: 0, fontSize: 10 }}
                  >
                    {mcpServices.some((s) => s.is_active) ? 'LIVE' : 'OFFLINE'}
                  </Tag>
                ) : (
                  <Tag color="default" style={{ margin: 0, fontSize: 10 }}>未接入</Tag>
                )}
              </div>

              {mcpServices.length === 0 ? (
                <div style={{ padding: '4px 0' }}>
                  <Typography.Text type="secondary" style={{ fontSize: 11, display: 'block', marginBottom: 8, lineHeight: 1.4 }}>
                    暂未接入任何 MCP 探店数据源，当前仅由大模型提供通用分析。
                  </Typography.Text>
                  <Button
                    size="small"
                    type="dashed"
                    block
                    icon={<PlusOutlined />}
                    onClick={() => navigate('/ops/service-catalog')}
                    style={{ fontSize: 11 }}
                  >
                    配置 MCP 数据源
                  </Button>
                </div>
              ) : (
                <Space direction="vertical" size={4} style={{ width: '100%' }}>
                  {mcpServices.map((svc) => {
                    const hasXhs = svc.channels?.some((c) => c.includes('xhs'))
                    const hasDp = svc.channels?.some((c) => c.includes('dianping'))
                    const canLogin = hasXhs || hasDp

                    return (
                      <div
                        key={svc.service_id}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          padding: '4px 8px',
                          background: '#fff',
                          borderRadius: 4,
                          border: '1px solid #f0f0f0',
                          fontSize: 11,
                        }}
                      >
                        <Space size={6} style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 120 }}>
                          <Badge status={svc.is_active ? 'success' : 'default'} />
                          <Typography.Text ellipsis style={{ fontSize: 11 }} title={svc.name}>
                            {svc.name}
                          </Typography.Text>
                        </Space>
                        {canLogin ? (
                          <Button
                            type="link"
                            size="small"
                            onClick={() => setLoginModalPlatform(hasXhs ? 'xhs_pc' : 'dianping')}
                            style={{ padding: 0, height: 'auto', fontSize: 10 }}
                          >
                            扫码授权
                          </Button>
                        ) : (
                          <Tag color={svc.is_active ? 'blue' : 'default'} style={{ margin: 0, fontSize: 10 }}>
                            {svc.protocol || 'MCP'}
                          </Tag>
                        )}
                      </div>
                    )
                  })}
                </Space>
              )}
            </Card>

            <Button
              block
              icon={<ControlOutlined />}
              onClick={() => navigate('/ops')}
              style={{ fontSize: 12 }}
            >
              运维管控平台
            </Button>
          </div>
        </div>
      </Layout.Sider>

      {/* 2. Main Layout Area */}
      <Layout style={{ height: '100vh', display: 'flex', flexDirection: 'column', background: '#fff' }}>
        {/* Ant Design Header */}
        <Layout.Header
          style={{
            background: '#fff',
            borderBottom: '1px solid #f0f0f0',
            height: 52,
            padding: '0 20px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            lineHeight: '52px',
          }}
        >
          <Space align="center" size={12}>
            {!sidebarOpen && (
              <Button
                type="text"
                icon={<MenuUnfoldOutlined />}
                onClick={() => setSidebarOpen(true)}
                title="展开侧边栏"
              />
            )}

            <Select
              value={selectedModel || undefined}
              placeholder="暂无大模型 (请在管理后台配置)"
              onChange={setSelectedModel}
              style={{ minWidth: 230, maxWidth: 300 }}
              options={modelOptions.map((m) => ({
                value: m.value,
                label: (
                  <Space size={6}>
                    <span>{m.label}</span>
                    {m.is_default && (
                      <Tag color="blue" bordered={false} style={{ fontSize: 10, marginInlineEnd: 0 }}>
                        默认
                      </Tag>
                    )}
                  </Space>
                ),
              }))}
            />
          </Space>

          <Space size={8}>
            {compareList.length > 0 && (
              <Badge count={compareList.length}>
                <Button
                  icon={<DiffOutlined />}
                  onClick={() => setIsCompareModalOpen(true)}
                >
                  对比矩阵
                </Button>
              </Badge>
            )}

            <Button
              type={rightPanelOpen ? 'primary' : 'default'}
              icon={<AuditOutlined />}
              onClick={() => setRightPanelOpen(!rightPanelOpen)}
            >
              调研检查器
              {evidenceItems.length > 0 && ` (${evidenceItems.length})`}
            </Button>
          </Space>
        </Layout.Header>

        {/* Chat Messages Content */}
        <Layout.Content
          style={{
            flex: 1,
            overflowY: 'auto',
            padding: '24px 24px 0',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          <div style={{ maxWidth: 840, width: '100%', margin: '0 auto', flex: 1, display: 'flex', flexDirection: 'column', gap: 20 }}>
            {isNewSession ? (
              <div
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flex: 1,
                  padding: '36px 16px 20px',
                  maxWidth: 720,
                  margin: '0 auto',
                  width: '100%',
                }}
              >
                <div
                  style={{
                    width: 52,
                    height: 52,
                    borderRadius: '50%',
                    background: '#e6f4ff',
                    color: '#1677ff',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: 26,
                    marginBottom: 16,
                  }}
                >
                  <RobotOutlined />
                </div>

                <Typography.Title level={3} style={{ marginBottom: 8, fontWeight: 600, textAlign: 'center' }}>
                  今天想找什么美食？
                </Typography.Title>
                <Typography.Text
                  type="secondary"
                  style={{ fontSize: 14, textAlign: 'center', marginBottom: 32, maxWidth: 540, lineHeight: 1.6 }}
                >
                  {mcpServices.length > 0
                    ? `输入你的就餐偏好、城市或就餐场景。Agent 将调取已接入的 ${mcpServices.map((s) => s.name).join('、')} 真实探店数据，深度识别本地人口碑，过滤网红流量陷阱。`
                    : '输入你的就餐偏好、城市或就餐场景。Agent 将基于大模型进行美食深度调查与口碑推演，过滤网红流量陷阱。'}
                </Typography.Text>

                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
                    gap: 12,
                    width: '100%',
                  }}
                >
                  {[
                    {
                      icon: '🍲',
                      title: '成都玉林老火锅',
                      desc: '本地人常去的口碑老店，人均100左右，排队别太久',
                      prompt: '成都玉林，本地人常去的老火锅，人均100，排队别太久，不要太甜太咸',
                    },
                    {
                      icon: '☕',
                      title: '广州西关正宗早茶',
                      desc: '两人人均80以内，虾饺烧卖扎实的老字号',
                      prompt: '广州越秀或荔湾区正宗早茶，两人人均80，虾饺要扎实',
                    },
                    {
                      icon: '🥩',
                      title: '上海静安商务宴请',
                      desc: '适合商务洽谈的本帮菜，包厢安静不踩雷',
                      prompt: '上海静安寺附近，适合商务宴请的本帮菜餐厅，环境安静不踩雷',
                    },
                    {
                      icon: '🍢',
                      title: '西安回民街地道小吃',
                      desc: '避开主街游客陷阱，寻找本地人认可的老店',
                      prompt: '西安大皮院附近的本地回民街小吃，避开主街游客店，寻找本地人认可的老店',
                    },
                  ].map((card, idx) => (
                    <Card
                      key={idx}
                      hoverable
                      size="small"
                      onClick={() => handleSendMessage(card.prompt)}
                      style={{
                        borderRadius: 12,
                        cursor: 'pointer',
                        borderColor: '#f0f0f0',
                        transition: 'all 0.2s ease',
                      }}
                      styles={{
                        body: { padding: '12px 14px' },
                      }}
                    >
                      <Space align="start" size={10}>
                        <span style={{ fontSize: 22 }}>{card.icon}</span>
                        <div>
                          <Typography.Text strong style={{ fontSize: 13, display: 'block', marginBottom: 2 }}>
                            {card.title}
                          </Typography.Text>
                          <Typography.Text type="secondary" style={{ fontSize: 12, lineHeight: 1.4 }}>
                            {card.desc}
                          </Typography.Text>
                        </div>
                      </Space>
                    </Card>
                  ))}
                </div>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
                {sessionTurns.map((turn, turnIdx) => {
                  const isLatest = turnIdx === sessionTurns.length - 1
                  const turnRunning = turn.assistantMessage.isRunning
                  const turnPlan = turn.assistantMessage.plan || []
                  const turnSummary = turn.assistantMessage.summary
                  const turnRecs = turn.assistantMessage.recommendations || []
                  const turnControversies = turn.assistantMessage.controversies || []
                  const turnProfiles = turn.assistantMessage.profiles || []

                  return (
                    <div key={turn.id} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                      {/* User Message Bubble */}
                      <Flex justify="flex-end">
                        <div style={{ maxWidth: '85%', display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4 }}>
                          {turn.userMessage.attachedContext && (
                            <Tag color="blue" style={{ borderRadius: 10, margin: 0 }}>
                              针对: {turn.userMessage.attachedContext.title}
                            </Tag>
                          )}
                          <Card
                            size="small"
                            style={{
                              backgroundColor: '#f5f5f5',
                              borderRadius: 16,
                              borderColor: '#e8e8e8',
                            }}
                          >
                            <Typography.Text style={{ fontSize: 14, whiteSpace: 'pre-wrap' }}>
                              {turn.userMessage.content}
                            </Typography.Text>
                          </Card>
                        </div>
                      </Flex>

                      {/* Assistant Answer Box */}
                      <Flex align="flex-start" gap={12}>
                        <Avatar
                          icon={<RobotOutlined />}
                          style={{ backgroundColor: '#1677ff', flexShrink: 0, marginTop: 2 }}
                        />

                        <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 14 }}>
                          {/* 1. Thought Accordion (Ant Design Collapse) */}
                          {turnPlan.length > 0 && (
                            <Collapse
                              ghost
                              size="small"
                              defaultActiveKey={turnRunning ? ['1'] : []}
                              items={[
                                {
                                  key: '1',
                                  label: (
                                    <Space>
                                      {turnRunning ? (
                                        <LoadingOutlined style={{ color: '#1677ff' }} />
                                      ) : (
                                        <ClockCircleOutlined style={{ color: '#52c41a' }} />
                                      )}
                                      <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                                        {turnRunning ? '正在分阶段搜集分析...' : `思考与调查步骤 (${turnPlan.length} 步)`}
                                      </Typography.Text>
                                    </Space>
                                  ),
                                  children: (
                                    <Timeline
                                      style={{ marginTop: 8 }}
                                      items={turnPlan.map((s) => ({
                                        color: s.status === 'succeeded' ? 'green' : (turnRunning && s.status === 'running' ? 'blue' : 'gray'),
                                        dot: (turnRunning && s.status === 'running') ? <LoadingOutlined /> : undefined,
                                        children: (
                                          <div>
                                            <Typography.Text strong style={{ fontSize: 12 }}>{s.label}</Typography.Text>
                                            {s.detail && (
                                              <div>
                                                <Typography.Text type="secondary" style={{ fontSize: 11 }}>{s.detail}</Typography.Text>
                                              </div>
                                            )}
                                          </div>
                                        ),
                                      }))}
                                    />
                                  ),
                                },
                              ]}
                            />
                          )}

                          {/* 2. Synthesis Summary or Single Loading State */}
                          {turnSummary ? (
                            <Typography.Paragraph style={{ fontSize: 14, lineHeight: 1.8, marginBottom: 0, whiteSpace: 'pre-line' }}>
                              {turnSummary}
                            </Typography.Paragraph>
                          ) : turnRunning ? (
                            turnPlan.length === 0 ? (
                              <Space style={{ padding: '8px 0' }}>
                                <LoadingOutlined style={{ color: '#1677ff' }} />
                                <Typography.Text type="secondary">
                                  {turn.assistantMessage.statusMessage || (mcpServices.length > 0
                                    ? `正在调取已接入的 ${mcpServices.map((s) => s.name).join('、')} 真实探店数据...`
                                    : '正在为您组织回答...')}
                                </Typography.Text>
                              </Space>
                            ) : turnPlan.every((s) => s.status === 'succeeded') ? (
                              <Space style={{ padding: '8px 0' }}>
                                <LoadingOutlined style={{ color: '#1677ff' }} />
                                <Typography.Text type="secondary">
                                  {turn.assistantMessage.statusMessage || '步骤已就绪，正在综合生成最终分析...'}
                                </Typography.Text>
                              </Space>
                            ) : null
                          ) : turn.assistantMessage.error ? (
                            <Alert type="error" message={turn.assistantMessage.error} showIcon />
                          ) : null}

                          {/* 3. Embedded Recommendation Cards */}
                          {turnRecs.length > 0 && (
                            <div>
                              <Typography.Text strong style={{ fontSize: 13, color: '#8c8c8c', display: 'block', marginBottom: 10 }}>
                                精选候选餐厅 ({turnRecs.length})
                              </Typography.Text>

                              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                                {turnRecs.map((rec, idx) => {
                                  const matchedProfile = turnProfiles.find(
                                    (p) => p.name === rec.title || p.profileId === rec.profileRef,
                                  )
                                  const isFavorite = favorites.includes(rec.recommendationId)

                                  return (
                                    <Card
                                      key={rec.recommendationId || `rec_${idx}`}
                                      size="small"
                                      hoverable
                                      style={{ borderRadius: 10, borderColor: '#e8e8e8' }}
                                      title={
                                        <Space align="center" style={{ width: '100%', justifyContent: 'space-between' }}>
                                          <Space>
                                            <Avatar size={20} style={{ backgroundColor: '#1677ff', fontSize: 11 }}>
                                              {rec.rank || idx + 1}
                                            </Avatar>
                                            <Typography.Text
                                              strong
                                              style={{ fontSize: 15, cursor: 'pointer' }}
                                              onClick={() => openStandaloneProfile(matchedProfile || null, rec)}
                                            >
                                              {rec.title}
                                            </Typography.Text>
                                            {matchedProfile?.averagePrice && (
                                              <Tag color="blue">￥{matchedProfile.averagePrice}/人</Tag>
                                            )}
                                          </Space>

                                          <Button
                                            type="text"
                                            size="small"
                                            icon={isFavorite ? <StarFilled style={{ color: '#faad14' }} /> : <StarOutlined />}
                                            onClick={() => handleToggleFavorite(rec.recommendationId, rec.title)}
                                            title={isFavorite ? '已收藏' : '收藏'}
                                          />
                                        </Space>
                                      }
                                    >
                                      <Space direction="vertical" size="small" style={{ width: '100%' }}>
                                        {matchedProfile?.address && (
                                          <Space size={4} style={{ fontSize: 12, color: '#8c8c8c' }}>
                                            <EnvironmentOutlined />
                                            <span>{matchedProfile.address}</span>
                                          </Space>
                                        )}

                                        {/* Highlights & Warnings */}
                                        <Space wrap size={[4, 4]}>
                                          {rec.highlights?.map((h: any, i: number) => (
                                            <Tag key={`high_${i}`} color="success">
                                              {h}
                                            </Tag>
                                          ))}
                                          {rec.warnings?.map((w: any, i: number) => (
                                            <Tag key={`warn_${i}`} color="warning">
                                              避雷: {w}
                                            </Tag>
                                          ))}
                                        </Space>

                                        {rec.summary && (
                                          <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 4 }}>
                                            {rec.summary}
                                          </Typography.Paragraph>
                                        )}

                                        <Divider style={{ margin: '8px 0' }} />

                                        {/* Card Action Row */}
                                        <Flex justify="space-between" align="center" wrap="wrap" gap={8}>
                                          <Space size={6}>
                                            <Button
                                              size="small"
                                              icon={<FileTextOutlined />}
                                              onClick={() => openInspector('evidence', matchedProfile || null, rec)}
                                            >
                                              真实评论 ({rec.evidenceRefs?.length || 0})
                                            </Button>
                                            <Button
                                              size="small"
                                              icon={<ShopOutlined />}
                                              onClick={() => openStandaloneProfile(matchedProfile || null, rec)}
                                            >
                                              店铺档案
                                            </Button>
                                            <Button
                                              size="small"
                                              icon={<DiffOutlined />}
                                              onClick={() => handleAddToCompare(rec, matchedProfile)}
                                            >
                                              加入对比
                                            </Button>
                                          </Space>

                                          <Button
                                            type="primary"
                                            size="small"
                                            icon={<ArrowRightOutlined />}
                                            onClick={() => {
                                              setAttachedContext({ type: 'shop', title: rec.title })
                                              textareaRef.current?.focus()
                                            }}
                                          >
                                            就此店追问
                                          </Button>
                                        </Flex>
                                      </Space>
                                    </Card>
                                  )
                                })}
                              </div>
                            </div>
                          )}

                          {/* 4. Controversy Alert */}
                          {turnControversies.length > 0 && (
                            <Alert
                              message={`发现 ${turnControversies.length} 项评论分歧争议焦点（如排队耗时、服务体验）`}
                              type="warning"
                              showIcon
                              action={
                                <Button
                                  size="small"
                                  type="primary"
                                  ghost
                                  onClick={() => openInspector('controversies')}
                                >
                                  查阅争议
                                </Button>
                              }
                            />
                          )}

                          {/* 5. Assistant Action Row */}
                          {!turnRunning && turnSummary && (
                            <Space size={8}>
                              <Tooltip title="复制回答">
                                <Button
                                  type="text"
                                  size="small"
                                  icon={hasCopied ? <CheckOutlined style={{ color: '#52c41a' }} /> : <CopyOutlined />}
                                  onClick={() => handleCopyResponse(turnSummary, turn.userMessage.content)}
                                />
                              </Tooltip>
                              <Tooltip title="正面好评">
                                <Button
                                  type="text"
                                  size="small"
                                  icon={<LikeOutlined style={{ color: feedbackRating === 'up' ? '#1677ff' : undefined }} />}
                                  onClick={() => {
                                    setFeedbackRating(feedbackRating === 'up' ? null : 'up')
                                    showToast('感谢你的反馈', 'success')
                                  }}
                                />
                              </Tooltip>
                              <Tooltip title="体验欠佳">
                                <Button
                                  type="text"
                                  size="small"
                                  icon={<DislikeOutlined style={{ color: feedbackRating === 'down' ? '#faad14' : undefined }} />}
                                  onClick={() => {
                                    setFeedbackRating(feedbackRating === 'down' ? null : 'down')
                                    showToast('已记录反馈，持续优化模型', 'info')
                                  }}
                                />
                              </Tooltip>
                              {isLatest && (
                                <Tooltip title="重新生成">
                                  <Button
                                    type="text"
                                    size="small"
                                    icon={<ReloadOutlined />}
                                    onClick={handleRegenerate}
                                  />
                                </Tooltip>
                              )}
                            </Space>
                          )}
                        </div>
                      </Flex>
                    </div>
                  )
                })}

                {/* 6. Quick Suggestions at the bottom of the conversation */}
                {!isRunning && sessionTurns.length > 0 && (
                  <Flex justify="flex-start" style={{ paddingLeft: 44 }}>
                    <Space wrap size={6}>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        建议追问：
                      </Typography.Text>
                      {suggestions.map((sug, i) => (
                        <Button
                          key={i}
                          shape="round"
                          size="small"
                          onClick={() => handleSendMessage(sug)}
                        >
                          {sug}
                        </Button>
                      ))}
                    </Space>
                  </Flex>
                )}

                <div ref={chatBottomRef} style={{ height: 16 }} />
              </div>
            )}
          </div>
        </Layout.Content>

        {/* 3. Composer Input Bar */}
        <div style={{ padding: '14px 24px 22px', background: '#fff', borderTop: '1px solid #f5f5f5' }}>
          <div style={{ maxWidth: 840, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div
              onClick={() => textareaRef.current?.focus()}
              style={{
                background: '#fff',
                border: isInputFocused ? '1px solid #1677ff' : '1px solid #d9d9d9',
                boxShadow: isInputFocused
                  ? '0 0 0 3px rgba(22, 119, 255, 0.12), 0 4px 20px rgba(0, 0, 0, 0.08)'
                  : '0 2px 10px rgba(0, 0, 0, 0.04)',
                borderRadius: 16,
                padding: '14px 18px 12px',
                transition: 'all 0.2s cubic-bezier(0.4, 0, 0.2, 1)',
                cursor: 'text',
              }}
            >
              {attachedContext && (
                <div style={{ marginBottom: 10 }}>
                  <Tag
                    closable
                    color="processing"
                    onClose={(e) => {
                      e.stopPropagation()
                      setAttachedContext(null)
                    }}
                    style={{
                      borderRadius: 12,
                      padding: '2px 10px',
                      fontSize: 12,
                    }}
                  >
                    针对商户: {attachedContext.title}
                  </Tag>
                </div>
              )}

              <Input.TextArea
                ref={textareaRef}
                autoSize={{ minRows: 3, maxRows: 8 }}
                placeholder={
                  attachedContext
                    ? `向 Food Agent 追问关于“${attachedContext.title}”的具体评价或排队避坑...`
                    : '向 Food Agent 提问，例如：“静安寺200元内正宗本帮菜”、“第一家排队严重吗”...'
                }
                value={inputText}
                onChange={(e) => setInputText(e.target.value)}
                onFocus={() => setIsInputFocused(true)}
                onBlur={() => setIsInputFocused(false)}
                onCompositionStart={() => setIsComposing(true)}
                onCompositionEnd={() => setIsComposing(false)}
                onKeyDown={handleKeyDown}
                variant="borderless"
                disabled={isRunning}
                style={{
                  resize: 'none',
                  padding: 0,
                  fontSize: 15,
                  lineHeight: 1.6,
                  boxShadow: 'none',
                  outline: 'none',
                }}
              />

              <Flex justify="space-between" align="center" style={{ marginTop: 12, paddingTop: 8, borderTop: '1px solid #f8f8f8' }}>
                <Space size={8} align="center">
                  {mcpServices.length > 0 ? (
                    <Tag
                      color={mcpServices.some((s) => s.is_active) ? 'green' : 'warning'}
                      variant="filled"
                      icon={<GlobalOutlined />}
                      style={{ borderRadius: 10, margin: 0, fontSize: 11, padding: '2px 8px' }}
                    >
                      {mcpServices.filter((s) => s.is_active).map((s) => s.name).join(' + ') || '数据源未激活'} 已连接
                    </Tag>
                  ) : (
                    <Tag
                      color="default"
                      variant="filled"
                      icon={<GlobalOutlined />}
                      style={{ borderRadius: 10, margin: 0, fontSize: 11, padding: '2px 8px', color: '#8c8c8c' }}
                    >
                      未接入外部数据源 (仅通用大模型)
                    </Tag>
                  )}
                  <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                    Shift + Enter 换行
                  </Typography.Text>
                </Space>

                {isRunning ? (
                  <Button
                    type="primary"
                    danger
                    shape="circle"
                    icon={<StopOutlined />}
                    onClick={(e) => {
                      e.stopPropagation()
                      handleStop()
                    }}
                    title="停止生成"
                    style={{ width: 34, height: 34, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
                  />
                ) : (
                  <Button
                    type="primary"
                    shape="circle"
                    icon={<ArrowUpOutlined style={{ fontSize: 16 }} />}
                    disabled={!inputText.trim()}
                    onClick={(e) => {
                      e.stopPropagation()
                      handleSendMessage()
                    }}
                    title="发送"
                    style={{
                      width: 34,
                      height: 34,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      backgroundColor: inputText.trim() ? '#1677ff' : '#f0f0f0',
                      borderColor: inputText.trim() ? '#1677ff' : '#d9d9d9',
                      color: inputText.trim() ? '#fff' : '#bfbfbf',
                      transition: 'all 0.2s ease',
                    }}
                  />
                )}
              </Flex>
            </div>

            <Typography.Text type="secondary" style={{ fontSize: 11, textAlign: 'center' }}>
              Food Agent 可能会提供不准确的商户信息，请核对重要餐饮与排队信息。
            </Typography.Text>
          </div>
        </div>
      </Layout>

      {/* 4. Right Inspector Drawer (Ant Design Drawer) */}
      <Drawer
        title="调研检查器"
        placement="right"
        size={480}
        onClose={() => setRightPanelOpen(false)}
        open={rightPanelOpen}
      >
        <Tabs
          activeKey={rightPanelTab}
          onChange={(key) => setRightPanelTab(key as RightPanelTab)}
          items={[
            {
              key: 'evidence',
              label: `评论证据 (${evidenceItems.length})`,
              children: (
                <EvidenceTimeline
                  evidenceItems={evidenceItems}
                  recommendations={recommendations}
                />
              ),
            },
            {
              key: 'controversies',
              label: `争议焦点 (${controversies.length})`,
              children: (
                <ControversyPanel
                  controversies={controversies}
                  evidenceItems={evidenceItems}
                  onVerifyControversy={(c) => {
                    setAttachedContext({ type: 'controversy', title: c.topic })
                    textareaRef.current?.focus()
                  }}
                />
              ),
            },
            {
              key: 'profile',
              label: '店铺档案',
              children: (
                <div>
                  {(() => {
                    const p = selectedProfile || (profiles.length > 0 ? profiles[0] : null)
                    if (!p) {
                      return (
                        <div style={{ textAlign: 'center', padding: '32px 0', color: '#8c8c8c' }}>
                          请在推荐列表中点击某家店铺以查看其大众点评事实档案
                        </div>
                      )
                    }
                    return (
                      <Card title={p.name || '精选门店'} size="small">
                        <Space direction="vertical" size="small" style={{ width: '100%' }}>
                          <div>地址：{p.address || '暂无详细街道'}</div>
                          <div>营业时间：{p.openingHours || '暂未收录'}</div>
                          <div>人均消费：{p.averagePrice ? `￥${p.averagePrice}` : '暂无'}</div>
                          <div>综合评分：{p.rating ? `${p.rating} 分` : '暂无'}</div>
                        </Space>
                      </Card>
                    )
                  })()}
                </div>
              ),
            },
          ]}
        />
      </Drawer>

      {/* Standalone Profile Drawer */}
      <ShopProfileDrawer
        isOpen={isProfileDrawerOpen}
        profile={selectedProfile}
        recommendation={selectedRec}
        onClose={() => setIsProfileDrawerOpen(false)}
        onFollowUp={(shop) => {
          setAttachedContext({ type: 'shop', title: shop })
          textareaRef.current?.focus()
        }}
      />

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
    </Layout>
  )
}
