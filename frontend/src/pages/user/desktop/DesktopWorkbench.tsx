import React from 'react'
import { useNavigate } from 'react-router-dom'
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
  Flex,
} from 'antd'
import {
  PlusOutlined,
  SendOutlined,
  StopOutlined,
  LoadingOutlined,
  DeleteOutlined,
  ClockCircleOutlined,
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
  RobotOutlined,
  CheckOutlined,
} from '@ant-design/icons'
import { MarkdownContent } from '../../../shared/markdown/MarkdownContent'
import { EvidenceTimeline } from '../../../components/research-surface/EvidenceTimeline'
import { ControversyPanel } from '../../../components/research-surface/ControversyPanel'
import { RestaurantComparisonModal } from '../../../components/restaurant/RestaurantComparisonModal'
import { ShopProfileDrawer } from '../../../components/research-surface/ShopProfileDrawer'
import { ManusThoughtCard } from '../../../components/chat/ManusThoughtCard'
import { QrLoginModal } from '../../../components/auth/QrLoginModal'
import { platformAccountsApi } from '../../../features/platform-accounts/api/platformAccountsApi'
import type { SharedWorkbenchProps, RightPanelTab } from '../types'

export function DesktopWorkbench(props: SharedWorkbenchProps) {
  const {
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
    handleStopInvestigation,
    handleStartNewChat,
    handleRetryLastTurn,
    historyList,
    handleSelectSession,
    handleDeleteSession,
    selectedModel,
    setSelectedModel,
    modelOptions,
    mcpServices,
    onRefreshConnectors,
    compareList,
    setCompareList,
    favorites,
    isCompareModalOpen,
    setIsCompareModalOpen,
    handleAddToCompare,
    handleToggleFavorite,
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
    recommendations,
    evidenceItems,
    controversies,
    profiles,
    sidebarOpen,
    setSidebarOpen,
    chatBottomRef,
    textareaRef,
    handleKeyDown,
  } = props

  const navigate = useNavigate()

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
                      className="session-history-item"
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
                      <div style={{ minWidth: 0, flex: 1, marginRight: 6 }}>
                        <Typography.Text
                          ellipsis
                          style={{
                            fontSize: 13,
                            color: isSelected ? '#1677ff' : 'inherit',
                            fontWeight: isSelected ? 500 : 400,
                            display: 'block',
                          }}
                        >
                          {item.query || '未命名调研'}
                        </Typography.Text>
                      </div>
                      <Button
                        type="text"
                        size="small"
                        icon={<DeleteOutlined />}
                        onClick={(e) => handleDeleteSession(item.session_id, e)}
                        style={{ color: '#bfbfbf', opacity: isSelected ? 1 : 0.6 }}
                      />
                    </div>
                  )
                })
              )}
            </div>
          </div>

          {/* Sider Footer: Platform Accounts & System Entry */}
          <div style={{ padding: '12px', borderTop: '1px solid #f0f0f0', display: 'flex', flexDirection: 'column', gap: 8 }}>
            <Card
              size="small"
              style={{ background: '#fafafa', borderRadius: 8, borderColor: '#f0f0f0' }}
              styles={{ body: { padding: '8px 10px' } }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                <Space size={4}>
                  <GlobalOutlined style={{ fontSize: 12, color: '#8c8c8c' }} />
                  <Typography.Text style={{ fontSize: 11, color: '#595959', fontWeight: 500 }}>
                    探店数据连接器
                  </Typography.Text>
                </Space>
                <Tag
                  color="processing"
                  style={{ margin: 0, fontSize: 9, padding: '0 4px', lineHeight: '14px', borderRadius: 4, cursor: 'pointer' }}
                  title="点击立即检测并刷新连接状态"
                  onClick={() => onRefreshConnectors?.()}
                >
                  心跳检测
                </Tag>
              </div>

              {mcpServices.length === 0 ? (
                <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                  未检测到 MCP 探店工具接入
                </Typography.Text>
              ) : (
                <Space direction="vertical" size={4} style={{ width: '100%' }}>
                  {mcpServices.map((svc) => {
                    const sid = (svc.service_id || '').toLowerCase()
                    const sname = (svc.name || '').toLowerCase()
                    const isXhs = sid.includes('xhs') || sid.includes('xiaohongshu') || sname.includes('小红书')
                    const isCtrip = sid.includes('ctrip') || sid.includes('xiecheng') || sname.includes('携程')
                    const isDp = sid.includes('dianping') || sname.includes('大众点评') || sname.includes('点评')

                    const platform = isXhs ? 'xhs_pc' : (isCtrip ? 'ctrip' : 'dianping')
                    const isOnline = Boolean((svc as any).service_online ?? (svc as any).is_active ?? (svc.enabled && (svc.live_state === 'ready' || svc.live_state === 'healthy')))
                    const isAuth = Boolean((svc as any).is_authenticated ?? (isCtrip ? isOnline : false))

                    let dotColor = '#d9d9d9'
                    if (!isOnline) {
                      dotColor = '#bfbfbf'
                    } else if (isAuth) {
                      dotColor = '#52c41a'
                    } else {
                      dotColor = '#faad14'
                    }

                    return (
                      <div
                        key={svc.service_id}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          fontSize: 11,
                          padding: '3px 4px',
                          borderRadius: 4,
                          cursor: !isCtrip ? 'pointer' : 'default',
                          transition: 'background-color 0.2s',
                        }}
                        onMouseEnter={(e) => {
                          if (!isCtrip) e.currentTarget.style.backgroundColor = '#f5f5f5'
                        }}
                        onMouseLeave={(e) => {
                          if (!isCtrip) e.currentTarget.style.backgroundColor = 'transparent'
                        }}
                      >
                        <Space
                          size={4}
                          onClick={() => {
                            if (!isCtrip) setLoginModalPlatform(platform)
                          }}
                        >
                          <span
                            style={{
                              width: 6,
                              height: 6,
                              borderRadius: '50%',
                              backgroundColor: dotColor,
                              display: 'inline-block',
                            }}
                          />
                          <Typography.Text style={{ fontSize: 11 }}>{svc.name}</Typography.Text>
                        </Space>
                        <Space size={4}>
                          {isAuth ? (
                            <>
                              <Tag color="success" style={{ margin: 0, fontSize: 10, padding: '0 4px', lineHeight: '16px' }}>
                                已连通
                              </Tag>
                              {!isCtrip && (
                                <Button
                                  type="link"
                                  size="small"
                                  style={{ padding: 0, fontSize: 11, height: 'auto', color: '#1677ff' }}
                                  onClick={(e) => {
                                    e.stopPropagation()
                                    setLoginModalPlatform(platform)
                                  }}
                                >
                                  重新授权
                                </Button>
                              )}
                            </>
                          ) : isOnline ? (
                            <Button
                              type="link"
                              size="small"
                              style={{ padding: 0, fontSize: 11, height: 'auto', color: '#fa8c16' }}
                              onClick={(e) => {
                                e.stopPropagation()
                                setLoginModalPlatform(platform)
                              }}
                            >
                              扫码授权
                            </Button>
                          ) : (
                            <Tag color="default" style={{ margin: 0, fontSize: 10, padding: '0 4px', lineHeight: '16px' }}>
                              服务离线
                            </Tag>
                          )}
                        </Space>
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
                          {/* 1. Manus-style Intelligent Agent Thought & Investigation Card */}
                          {turnPlan.length > 0 && (
                            <ManusThoughtCard
                              plan={turnPlan}
                              isRunning={turnRunning}
                              statusMessage={turn.assistantMessage.statusMessage}
                            />
                          )}

                          {/* 2. Synthesis Summary or Single Loading State */}
                          {turnSummary ? (
                            <MarkdownContent content={turnSummary} streaming={turnRunning} />
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
                                            onClick={() => handleToggleFavorite(rec.recommendationId)}
                                          />
                                        </Space>
                                      }
                                    >
                                      <Space direction="vertical" size={10} style={{ width: '100%' }}>
                                        <Typography.Paragraph
                                          ellipsis={{ rows: 2 }}
                                          style={{ margin: 0, fontSize: 13, color: '#434343' }}
                                        >
                                          {rec.summary}
                                        </Typography.Paragraph>

                                        {/* Highlights & Warnings */}
                                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                                          {rec.highlights?.map((h: string, i: number) => (
                                            <Tag key={`h_${i}`} color="success" style={{ borderRadius: 4 }}>
                                              {h}
                                            </Tag>
                                          ))}
                                          {rec.warnings?.map((w: string, i: number) => (
                                            <Tag key={`w_${i}`} color="warning" style={{ borderRadius: 4 }}>
                                              {w}
                                            </Tag>
                                          ))}
                                        </div>

                                        {/* Action Row */}
                                        <Flex justify="space-between" align="center" style={{ paddingTop: 4 }}>
                                          <Space size={8}>
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
                                  }}
                                />
                              </Tooltip>
                              <Tooltip title="指出不足">
                                <Button
                                  type="text"
                                  size="small"
                                  icon={<DislikeOutlined style={{ color: feedbackRating === 'down' ? '#ff4d4f' : undefined }} />}
                                  onClick={() => {
                                    setFeedbackRating(feedbackRating === 'down' ? null : 'down')
                                  }}
                                />
                              </Tooltip>
                              {isLatest && !isRunning && (
                                <Tooltip title="重新生成">
                                  <Button
                                    type="text"
                                    size="small"
                                    icon={<ReloadOutlined />}
                                    onClick={handleRetryLastTurn}
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
                  {mcpServices.length > 0 ? (() => {
                    const xhsConnected = mcpServices.some((s) => {
                      const sid = (s.service_id || '').toLowerCase()
                      const plat = (s.platform || (s.channels && s.channels[0]) || '').toLowerCase()
                      return (plat.includes('xhs') || sid.includes('xhs')) && (s.is_authenticated || s.account_status === 'active')
                    })
                    const dpConnected = mcpServices.some((s) => {
                      const sid = (s.service_id || '').toLowerCase()
                      const plat = (s.platform || (s.channels && s.channels[0]) || '').toLowerCase()
                      return (plat.includes('dianping') || sid.includes('dianping')) && (s.is_authenticated || s.account_status === 'active')
                    })
                    const ctripConnected = mcpServices.some((s) => {
                      const sid = (s.service_id || '').toLowerCase()
                      const plat = (s.platform || (s.channels && s.channels[0]) || '').toLowerCase()
                      return (plat.includes('ctrip') || plat.includes('xiecheng') || sid.includes('ctrip') || sid.includes('xiecheng')) && (s.is_authenticated || s.service_online || s.is_active)
                    })

                    let tagColor = 'default'
                    let tagText = '○ 探店 MCP 服务离线'

                    if (xhsConnected && dpConnected && ctripConnected) {
                      tagColor = 'green'
                      tagText = '● 探店全数据源已连通 (大众点评/小红书/携程)'
                    } else if (xhsConnected && dpConnected) {
                      tagColor = 'green'
                      tagText = '● 探店双数据源已连通 (大众点评/小红书)'
                    } else if (xhsConnected) {
                      tagColor = 'green'
                      tagText = '● 小红书数据源已连通 (大众点评待授权)'
                    } else if (dpConnected) {
                      tagColor = 'green'
                      tagText = '● 大众点评数据源已连通 (小红书待授权)'
                    } else if (ctripConnected) {
                      tagColor = 'blue'
                      tagText = '● 携程公开数据已连通 (点评/小红书待授权)'
                    } else if (mcpServices.some((s) => (s as any).service_online ?? (s as any).is_active)) {
                      tagColor = 'warning'
                      tagText = '○ 探店 MCP 待扫码授权 (点击左侧授权)'
                    }

                    return (
                      <Tag
                        color={tagColor}
                        variant="filled"
                        style={{ fontSize: 12, borderRadius: 10, padding: '1px 8px' }}
                      >
                        {tagText}
                      </Tag>
                    )
                  })() : (
                    <Tag
                      color="default"
                      variant="filled"
                      style={{ fontSize: 12, borderRadius: 10, padding: '1px 8px' }}
                    >
                      ○ 大模型直连推理模式
                    </Tag>
                  )}
                </Space>

                {isRunning ? (
                  <Button
                    type="primary"
                    danger
                    shape="circle"
                    size="middle"
                    icon={<StopOutlined />}
                    onClick={handleStopInvestigation}
                    title="停止生成"
                  />
                ) : (
                  <Button
                    type="primary"
                    shape="circle"
                    size="middle"
                    icon={<SendOutlined />}
                    disabled={!inputText.trim()}
                    onClick={() => handleSendMessage()}
                    style={{
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
            onRefreshConnectors?.()
          }}
        />
      )}
    </Layout>
  )
}
