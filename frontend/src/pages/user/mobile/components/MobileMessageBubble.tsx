import React from 'react'
import {
  Flex,
  Card,
  Typography,
  Tag,
  Avatar,
  Collapse,
  Timeline,
  Space,
  Alert,
  Button,
} from 'antd'
import {
  RobotOutlined,
  LoadingOutlined,
  ClockCircleOutlined,
  CopyOutlined,
  CheckOutlined,
  LikeOutlined,
  DislikeOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import { MarkdownContent } from '../../../../shared/markdown/MarkdownContent'
import { MobileRestaurantCard } from './MobileRestaurantCard'
import type { ChatTurn } from '../../types'

interface MobileMessageBubbleProps {
  turn: ChatTurn
  isLatest: boolean
  isRunning: boolean
  favorites: string[]
  onToggleFavorite: (recId: string) => void
  onOpenProfile: (profile: any, rec: any) => void
  onAddToCompare: (rec: any, profile: any) => void
  onFollowUpShop: (title: string) => void
  onOpenInspector: (tab: 'evidence' | 'controversies') => void
  feedbackRating: 'up' | 'down' | null
  setFeedbackRating: (r: 'up' | 'down' | null) => void
  hasCopied: boolean
  onCopyResponse: (text: string, query: string) => void
  onRetryLastTurn: () => void
}

export function MobileMessageBubble({
  turn,
  isLatest,
  isRunning,
  favorites,
  onToggleFavorite,
  onOpenProfile,
  onAddToCompare,
  onFollowUpShop,
  onOpenInspector,
  feedbackRating,
  setFeedbackRating,
  hasCopied,
  onCopyResponse,
  onRetryLastTurn,
}: MobileMessageBubbleProps) {
  const turnRunning = turn.assistantMessage.isRunning
  const turnPlan = turn.assistantMessage.plan || []
  const turnSummary = turn.assistantMessage.summary
  const turnRecs = turn.assistantMessage.recommendations || []
  const turnControversies = turn.assistantMessage.controversies || []
  const turnProfiles = turn.assistantMessage.profiles || []

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {/* 1. User Message (Right-aligned) */}
      <Flex justify="flex-end">
        <div style={{ maxWidth: '88%', display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4 }}>
          {turn.userMessage.attachedContext && (
            <Tag color="blue" style={{ borderRadius: 10, margin: 0, fontSize: 11 }}>
              针对: {turn.userMessage.attachedContext.title}
            </Tag>
          )}
          <div
            style={{
              backgroundColor: '#1677ff',
              color: '#fff',
              padding: '10px 14px',
              borderRadius: '16px 16px 4px 16px',
              fontSize: 14,
              lineHeight: 1.5,
              wordBreak: 'break-word',
              boxShadow: '0 2px 6px rgba(22, 119, 255, 0.15)',
            }}
          >
            {turn.userMessage.content}
          </div>
        </div>
      </Flex>

      {/* 2. Assistant Answer Box (Card-First Layout) */}
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 10,
          backgroundColor: '#fff',
          borderRadius: 16,
          padding: '14px 14px',
          boxShadow: '0 2px 10px rgba(0,0,0,0.04)',
          border: '1px solid #f0f0f0',
        }}
      >
        {/* Assistant Header */}
        <Flex align="center" justify="space-between">
          <Space size={8} align="center">
            <Avatar
              size={24}
              icon={<RobotOutlined />}
              style={{ backgroundColor: '#1677ff' }}
            />
            <Typography.Text strong style={{ fontSize: 13, color: '#262626' }}>
              探店老饕 AI
            </Typography.Text>
          </Space>

          {turnRunning && (
            <Tag color="processing" style={{ margin: 0, borderRadius: 10, fontSize: 11 }}>
              <LoadingOutlined style={{ marginRight: 4 }} />
              调研推演中
            </Tag>
          )}
        </Flex>

        {/* 2.1 Investigation Step Timeline Accordion */}
        {turnPlan.length > 0 && (
          <Collapse
            ghost
            size="small"
            defaultActiveKey={turnRunning ? ['1'] : []}
            items={[
              {
                key: '1',
                label: (
                  <Space size={6}>
                    {turnRunning ? (
                      <LoadingOutlined style={{ color: '#1677ff', fontSize: 12 }} />
                    ) : (
                      <ClockCircleOutlined style={{ color: '#52c41a', fontSize: 12 }} />
                    )}
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {turnRunning ? '探店调查步骤推进中...' : `调查步骤记录 (${turnPlan.length} 步)`}
                    </Typography.Text>
                  </Space>
                ),
                children: (
                  <Timeline
                    style={{ marginTop: 6, paddingLeft: 4 }}
                    items={turnPlan.map((s) => ({
                      color: s.status === 'succeeded' ? 'green' : (turnRunning && s.status === 'running' ? 'blue' : 'gray'),
                      dot: (turnRunning && s.status === 'running') ? <LoadingOutlined style={{ fontSize: 11 }} /> : undefined,
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

        {/* 2.2 Text / Markdown Content */}
        {turnSummary ? (
          <div style={{ fontSize: 14 }}>
            <MarkdownContent content={turnSummary} streaming={turnRunning} fontSize={14} />
          </div>
        ) : turnRunning ? (
          <Space style={{ padding: '8px 0' }}>
            <LoadingOutlined style={{ color: '#1677ff' }} />
            <Typography.Text type="secondary" style={{ fontSize: 13 }}>
              {turn.assistantMessage.statusMessage || '正在调取真实口碑数据为您推演...'}
            </Typography.Text>
          </Space>
        ) : turn.assistantMessage.error ? (
          <Alert type="error" message={turn.assistantMessage.error} showIcon />
        ) : null}

        {/* 2.3 Embedded Recommendations List */}
        {turnRecs.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 4 }}>
            <Typography.Text strong style={{ fontSize: 13, color: '#8c8c8c' }}>
              精选推荐餐厅 ({turnRecs.length})
            </Typography.Text>

            {turnRecs.map((rec, idx) => {
              const matchedProfile = turnProfiles.find(
                (p) => p.name === rec.title || p.profileId === rec.profileRef,
              )
              const isFavorite = favorites.includes(rec.recommendationId)

              return (
                <MobileRestaurantCard
                  key={rec.recommendationId || `rec_${idx}`}
                  rec={rec}
                  index={idx}
                  profile={matchedProfile}
                  isFavorite={isFavorite}
                  onToggleFavorite={() => onToggleFavorite(rec.recommendationId)}
                  onOpenProfile={() => onOpenProfile(matchedProfile || null, rec)}
                  onAddToCompare={() => onAddToCompare(rec, matchedProfile)}
                  onFollowUp={() => onFollowUpShop(rec.title)}
                />
              )
            })}
          </div>
        )}

        {/* 2.4 Controversy Alert */}
        {turnControversies.length > 0 && (
          <Alert
            message={`发现 ${turnControversies.length} 项评论分歧争议焦点`}
            description="针对排队耗时、服务体验、招牌菜口味等存在口碑差异"
            type="warning"
            showIcon
            action={
              <Button
                size="small"
                type="primary"
                ghost
                onClick={() => onOpenInspector('controversies')}
              >
                查阅争议
              </Button>
            }
          />
        )}

        {/* 2.5 Action Bar */}
        {!turnRunning && turnSummary && (
          <Flex justify="space-between" align="center" style={{ borderTop: '1px solid #f8f8f8', paddingTop: 8 }}>
            <Space size={12}>
              <Button
                type="text"
                size="small"
                icon={hasCopied ? <CheckOutlined style={{ color: '#52c41a' }} /> : <CopyOutlined />}
                onClick={() => onCopyResponse(turnSummary, turn.userMessage.content)}
                style={{ fontSize: 12, padding: 0 }}
              >
                {hasCopied ? '已复制' : '复制'}
              </Button>

              <Button
                type="text"
                size="small"
                icon={<LikeOutlined style={{ color: feedbackRating === 'up' ? '#1677ff' : undefined }} />}
                onClick={() => setFeedbackRating(feedbackRating === 'up' ? null : 'up')}
                style={{ padding: 0 }}
              />

              <Button
                type="text"
                size="small"
                icon={<DislikeOutlined style={{ color: feedbackRating === 'down' ? '#ff4d4f' : undefined }} />}
                onClick={() => setFeedbackRating(feedbackRating === 'down' ? null : 'down')}
                style={{ padding: 0 }}
              />
            </Space>

            {isLatest && !isRunning && (
              <Button
                type="text"
                size="small"
                icon={<ReloadOutlined />}
                onClick={onRetryLastTurn}
                style={{ fontSize: 12, padding: 0 }}
              >
                重新生成
              </Button>
            )}
          </Flex>
        )}
      </div>
    </div>
  )
}
