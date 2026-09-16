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
import { MarkdownContent } from '../../shared/markdown/MarkdownContent'
import { EvidenceTimeline } from '../../components/research-surface/EvidenceTimeline'
import { ControversyPanel } from '../../components/research-surface/ControversyPanel'
import { RestaurantComparisonModal } from '../../components/restaurant/RestaurantComparisonModal'
import { ShopProfileDrawer } from '../../components/research-surface/ShopProfileDrawer'
import { QrLoginModal } from '../../components/auth/QrLoginModal'
import { useIsMobile } from '../../hooks/useIsMobile'
import { DesktopWorkbench } from './desktop/DesktopWorkbench'
import { MobileWorkbench } from './mobile/MobileWorkbench'
import type { SharedWorkbenchProps } from './types'
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

  // Current session ID (restore last active session if opening without route parameter)
  const [currentSessionId, setCurrentSessionId] = useState<string>(() => {
    if (routeSessionId) return routeSessionId
    const lastSid = storage.get<string>('food_agent_last_active_session', '')
    return lastSid || ''
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

  // Track last active session ID in storage
  useEffect(() => {
    if (currentSessionId) {
      storage.set('food_agent_last_active_session', currentSessionId)
    }
  }, [currentSessionId])

  // Synchronize route
  useEffect(() => {
    if (routeSessionId && routeSessionId !== currentSessionId) {
      setCurrentSessionId(routeSessionId)
    } else if (!routeSessionId) {
      const lastSid = storage.get<string>('food_agent_last_active_session', '')
      if (lastSid && lastSid !== currentSessionId) {
        setCurrentSessionId(lastSid)
        navigate(`/chat/${lastSid}`, { replace: true })
      }
    }
  }, [routeSessionId, currentSessionId, navigate])

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
    storage.remove('food_agent_last_active_session')
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
      storage.remove('food_agent_last_active_session')
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

      if (eventName === 'chunk' || eventName === 'text_chunk') {
        const text = typeof data === 'string' ? data : (data?.text || data?.chunk || data?.delta || data?.content || '')
        if (text) {
          assistant.summary = (assistant.summary || '') + text
          assistant.statusMessage = undefined
        }
      } else if (eventName === 'step_start') {
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
      if (eventName !== 'chunk' && eventName !== 'text_chunk') {
        storage.set(`food_agent_turns_${sessionId}`, nextTurns)
      }
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

  const isMobile = useIsMobile()

  const sharedProps: SharedWorkbenchProps = {
    currentSessionId,
    sessionTurns,
    isRunning,
    isNewSession,
    inputText,
    setInputText,
    isInputFocused,
    setIsInputFocused,
    attachedContext,
    setAttachedContext,
    handleSendMessage,
    handleStopInvestigation: handleStop,
    handleStartNewChat,
    handleRetryLastTurn: handleRegenerate,
    historyList,
    handleSelectSession,
    handleDeleteSession,
    selectedModel,
    setSelectedModel,
    modelOptions,
    mcpServices,
    compareList,
    setCompareList,
    favorites,
    isCompareModalOpen,
    setIsCompareModalOpen,
    handleAddToCompare,
    handleRemoveFromCompare: (id: string) => setCompareList((prev) => prev.filter((r) => r.id !== id)),
    handleToggleFavorite: (recId: string, title?: string) => handleToggleFavorite(recId, title || ''),
    accounts,
    setAccounts,
    loginModalPlatform,
    setLoginModalPlatform,
    rightPanelOpen,
    setRightPanelOpen,
    rightPanelTab,
    setRightPanelTab,
    openInspector,
    selectedProfile,
    selectedRec,
    isProfileDrawerOpen,
    setIsProfileDrawerOpen,
    openStandaloneProfile,
    feedbackRating,
    setFeedbackRating,
    hasCopied,
    handleCopyResponse,
    suggestions,
    isQrModalOpen: false,
    setIsQrModalOpen: () => {},
    recommendations,
    evidenceItems,
    controversies,
    profiles,
    plan,
    sidebarOpen,
    setSidebarOpen,
    chatBottomRef,
    textareaRef,
    handleKeyDown,
  }

  return isMobile ? <MobileWorkbench {...sharedProps} /> : <DesktopWorkbench {...sharedProps} />
}
