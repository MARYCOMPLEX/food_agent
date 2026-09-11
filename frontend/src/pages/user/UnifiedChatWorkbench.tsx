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
    stop,
    appendEvent,
  } = useResearchSessionReact(currentSessionId, { autoStart: true })

  // UI States
  const [sidebarOpen, setSidebarOpen] = useState<boolean>(true)
  const [rightPanelOpen, setRightPanelOpen] = useState<boolean>(false)
  const [rightPanelTab, setRightPanelTab] = useState<RightPanelTab>('evidence')
  const [selectedProfile, setSelectedProfile] = useState<ResearchProfileViewV1 | null>(null)
  const [selectedRec, setSelectedRec] = useState<ResearchRecommendationViewV1 | null>(null)
  const [isProfileDrawerOpen, setIsProfileDrawerOpen] = useState<boolean>(false)

  // Model Selection
  const [selectedModel, setSelectedModel] = useState<string>('food-agent-4o')

  // Follow-up context
  const [attachedContext, setAttachedContext] = useState<{
    type: 'shop' | 'controversy'
    title: string
  } | null>(null)

  // Text Composer
  const [inputText, setInputText] = useState<string>('')
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
    setFeedbackRating(null)
    navigate(`/chat/${newId}`)
  }

  // Switch session
  const handleSelectSession = (sid: string) => {
    setCurrentSessionId(sid)
    setRightPanelOpen(false)
    setFeedbackRating(null)
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

  // Copy response
  const handleCopyResponse = async () => {
    const textToCopy = `${currentQuery}\n\n${projection?.summary || ''}`
    try {
      await navigator.clipboard.writeText(textToCopy)
      setHasCopied(true)
      showToast('已复制回答内容至剪贴板', 'success')
      setTimeout(() => setHasCopied(false), 2000)
    } catch {
      showToast('复制失败，请手动选择文本', 'warning')
    }
  }

  // Regenerate / Retry response
  const handleRegenerate = () => {
    showToast('正在重新综合研判评论与档案...', 'info')
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
        summary: '已重新调取小红书与大众点评多源证据，正在二次核验口碑交叉点...',
      },
    })
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
    <Layout style={{ height: '100vh', width: '100vw', overflow: 'hidden' }}>
      {/* 1. Left Sider: Ant Design Sider with Menu & Session History */}
      <Layout.Sider
        width={270}
        theme="light"
        collapsible
        collapsed={!sidebarOpen}
        trigger={null}
        style={{
          borderRight: '1px solid #f0f0f0',
          display: 'flex',
          flexDirection: 'column',
          height: '100vh',
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
              <Tag color="blue" bordered={false} style={{ fontSize: 11 }}>
                4o
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
            <List
              dataSource={historyList}
              renderItem={(item) => {
                const isSelected = item.session_id === currentSessionId
                return (
                  <List.Item
                    key={item.session_id}
                    onClick={() => handleSelectSession(item.session_id)}
                    style={{
                      padding: '8px 10px',
                      borderRadius: 6,
                      marginBottom: 3,
                      cursor: 'pointer',
                      background: isSelected ? '#e6f4ff' : 'transparent',
                      border: 'none',
                      transition: 'background 0.2s',
                    }}
                    actions={[
                      <Button
                        key="del"
                        type="text"
                        danger
                        size="small"
                        icon={<DeleteOutlined />}
                        onClick={(e) => handleDeleteSession(item.session_id, e)}
                        title="删除会话"
                      />,
                    ]}
                  >
                    <Space size={8} style={{ overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis' }}>
                      <MessageOutlined style={{ color: isSelected ? '#1677ff' : '#8c8c8c' }} />
                      <Typography.Text
                        ellipsis
                        style={{
                          fontSize: 12,
                          color: isSelected ? '#1677ff' : '#262626',
                          fontWeight: isSelected ? 500 : 400,
                          maxWidth: 160,
                        }}
                      >
                        {item.query}
                      </Typography.Text>
                    </Space>
                  </List.Item>
                )
              }}
            />
          </div>

          {/* Sider Footer */}
          <div style={{ padding: 12, borderTop: '1px solid #f0f0f0' }}>
            <Card size="small" style={{ marginBottom: 8, background: '#fafafa' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                <Typography.Text strong style={{ fontSize: 11 }}>探店数据源</Typography.Text>
                <Tag color="success" style={{ margin: 0, fontSize: 10 }}>LIVE</Tag>
              </div>
              <Space direction="vertical" size={4} style={{ width: '100%' }}>
                <Button
                  size="small"
                  block
                  onClick={() => setLoginModalPlatform('xhs_pc')}
                  style={{ textAlign: 'left', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}
                >
                  <Space size={6}>
                    <Badge status={xhsDegraded ? 'warning' : 'success'} />
                    <span style={{ fontSize: 11 }}>小红书</span>
                  </Space>
                  <Typography.Text type="secondary" style={{ fontSize: 10 }}>扫码登录</Typography.Text>
                </Button>
                <Button
                  size="small"
                  block
                  onClick={() => setLoginModalPlatform('dianping')}
                  style={{ textAlign: 'left', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}
                >
                  <Space size={6}>
                    <Badge status={dpDegraded ? 'warning' : 'success'} />
                    <span style={{ fontSize: 11 }}>大众点评</span>
                  </Space>
                  <Typography.Text type="secondary" style={{ fontSize: 10 }}>扫码登录</Typography.Text>
                </Button>
              </Space>
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
              value={selectedModel}
              onChange={setSelectedModel}
              style={{ width: 220 }}
              options={[
                { value: 'food-agent-4o', label: 'Food Agent 4o (默认推荐)' },
                { value: 'food-agent-o3-mini', label: 'Food Agent o3-mini (深度推理)' },
                { value: 'food-agent-4o-mini', label: 'Food Agent 4o-mini (极速轻量)' },
              ]}
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
            {/* User Message Bubble */}
            <Flex justify="flex-end">
              <Card
                size="small"
                style={{
                  maxWidth: '85%',
                  backgroundColor: '#f5f5f5',
                  borderRadius: 16,
                  borderColor: '#e8e8e8',
                }}
              >
                <Typography.Text style={{ fontSize: 14 }}>{currentQuery}</Typography.Text>
              </Card>
            </Flex>

            {/* Assistant Answer Box */}
            <Flex align="flex-start" gap={12}>
              <Avatar
                icon={<RobotOutlined />}
                style={{ backgroundColor: '#1677ff', flexShrink: 0, marginTop: 2 }}
              />

              <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 14 }}>
                {/* 1. Thought Accordion (Ant Design Collapse) */}
                {plan.length > 0 && (
                  <Collapse
                    ghost
                    size="small"
                    items={[
                      {
                        key: '1',
                        label: (
                          <Space>
                            {isRunning ? (
                              <LoadingOutlined style={{ color: '#1677ff' }} />
                            ) : (
                              <ClockCircleOutlined style={{ color: '#52c41a' }} />
                            )}
                            <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                              {isRunning ? '正在分阶段搜集分析...' : `思考与调查步骤 (${plan.length} 步)`}
                            </Typography.Text>
                          </Space>
                        ),
                        children: (
                          <Timeline
                            style={{ marginTop: 8 }}
                            items={plan.map((s) => ({
                              color: s.status === 'succeeded' ? 'green' : s.status === 'running' ? 'blue' : 'gray',
                              dot: s.status === 'running' ? <LoadingOutlined /> : undefined,
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

                {/* 2. Synthesis Summary */}
                {projection?.summary ? (
                  <Typography.Paragraph style={{ fontSize: 14, lineHeight: 1.8, marginBottom: 0, whiteSpace: 'pre-line' }}>
                    {projection.summary}
                  </Typography.Paragraph>
                ) : (
                  <Space style={{ padding: '12px 0' }}>
                    <LoadingOutlined style={{ color: '#1677ff' }} />
                    <Typography.Text type="secondary">
                      正在全网检索小红书与大众点评真实评论数据...
                    </Typography.Text>
                  </Space>
                )}

                {/* 3. Embedded Recommendation Cards */}
                {recommendations.length > 0 && (
                  <div>
                    <Typography.Text strong style={{ fontSize: 13, color: '#8c8c8c', display: 'block', marginBottom: 10 }}>
                      精选候选餐厅 ({recommendations.length})
                    </Typography.Text>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                      {recommendations.map((rec, idx) => {
                        const matchedProfile = profiles.find(
                          (p) => p.name === rec.title || p.profileId === rec.profileRef,
                        )
                        const isFavorite = favorites.includes(rec.recommendationId)

                        return (
                          <Card
                            key={rec.recommendationId}
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
                                {rec.highlights?.map((h, i) => (
                                  <Tag key={i} color="success">
                                    {h}
                                  </Tag>
                                ))}
                                {rec.warnings?.map((w, i) => (
                                  <Tag key={i} color="warning">
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
                {controversies.length > 0 && (
                  <Alert
                    message={`发现 ${controversies.length} 项评论分歧争议焦点（如排队耗时、服务体验）`}
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
                <Space size={8}>
                  <Tooltip title="复制回答">
                    <Button
                      type="text"
                      size="small"
                      icon={hasCopied ? <CheckOutlined style={{ color: '#52c41a' }} /> : <CopyOutlined />}
                      onClick={handleCopyResponse}
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
                  <Tooltip title="重新生成">
                    <Button
                      type="text"
                      size="small"
                      icon={<ReloadOutlined />}
                      onClick={handleRegenerate}
                    />
                  </Tooltip>
                </Space>

                {/* 6. Quick Suggestions */}
                <Space wrap size={6} style={{ paddingTop: 4 }}>
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
              </div>
            </Flex>

            <div ref={chatBottomRef} style={{ height: 16 }} />
          </div>
        </Layout.Content>

        {/* 3. Composer Input Bar */}
        <div style={{ padding: '12px 24px 20px', background: '#fff', borderTop: '1px solid #f5f5f5' }}>
          <div style={{ maxWidth: 840, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 6 }}>
            {attachedContext && (
              <Tag
                closable
                color="processing"
                onClose={() => setAttachedContext(null)}
                style={{ width: 'fit-content' }}
              >
                针对：{attachedContext.title}
              </Tag>
            )}

            <Card
              size="small"
              style={{
                borderRadius: 12,
                boxShadow: '0 2px 10px rgba(0,0,0,0.05)',
                borderColor: '#d9d9d9',
              }}
              bodyStyle={{ padding: '8px 12px' }}
            >
              <Input.TextArea
                ref={textareaRef}
                autoSize={{ minRows: 2, maxRows: 6 }}
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
                bordered={false}
                disabled={isRunning}
                style={{ resize: 'none', padding: 0 }}
              />

              <Flex justify="space-between" align="center" style={{ marginTop: 8 }}>
                <Space size={6}>
                  <Tag color="green" icon={<GlobalOutlined />}>
                    小红书 + 大众点评已连接
                  </Tag>
                </Space>

                {isRunning ? (
                  <Button
                    type="primary"
                    danger
                    shape="circle"
                    icon={<StopOutlined />}
                    onClick={stop}
                    title="停止生成"
                  />
                ) : (
                  <Button
                    type="primary"
                    shape="circle"
                    icon={<ArrowUpOutlined />}
                    disabled={!inputText.trim()}
                    onClick={() => handleSendMessage()}
                    title="发送"
                  />
                )}
              </Flex>
            </Card>

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
        width={480}
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
