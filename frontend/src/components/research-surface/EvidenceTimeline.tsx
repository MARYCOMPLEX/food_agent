import React, { useState, useMemo } from 'react'
import { Card, Timeline, Tag, Input, Segmented, Empty, Typography, Space, Button } from 'antd'
import {
  MessageOutlined,
  LikeOutlined,
  DislikeOutlined,
  QuestionCircleOutlined,
  SearchOutlined,
} from '@ant-design/icons'
import type {
  ResearchEvidenceItemV1,
  ResearchRecommendationViewV1,
} from '../../shared/contracts/research'

interface EvidenceTimelineProps {
  evidenceItems: ResearchEvidenceItemV1[]
  recommendations?: ResearchRecommendationViewV1[]
  selectedEvidenceId?: string | null
  onSelectShop?: (shopName: string) => void
  onFocusEvidence?: (evidenceId: string) => void
}

export function EvidenceTimeline({
  evidenceItems,
  recommendations = [],
  selectedEvidenceId,
  onSelectShop,
  onFocusEvidence,
}: EvidenceTimelineProps) {
  const [stanceFilter, setStanceFilter] = useState<string>('all')
  const [searchQuery, setSearchQuery] = useState<string>('')

  // Filtered evidence items
  const filteredEvidence = useMemo(() => {
    return evidenceItems.filter((ev) => {
      if (stanceFilter !== 'all' && ev.stance !== stanceFilter) return false
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase()
        const excerpt = (ev.excerpt || '').toLowerCase()
        const title = (ev.title || '').toLowerCase()
        if (!excerpt.includes(q) && !title.includes(q)) return false
      }
      return true
    })
  }, [evidenceItems, stanceFilter, searchQuery])

  if (!evidenceItems || evidenceItems.length === 0) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description="暂无提取的评论证据，检索完成后将呈现于此"
      />
    )
  }

  const timelineItems = filteredEvidence.map((ev) => {
    let tagColor = 'blue'
    let stanceIcon = <QuestionCircleOutlined />
    let stanceLabel = '中立'

    if (ev.stance === 'positive') {
      tagColor = 'success'
      stanceIcon = <LikeOutlined />
      stanceLabel = '好评推荐'
    } else if (ev.stance === 'negative') {
      tagColor = 'error'
      stanceIcon = <DislikeOutlined />
      stanceLabel = '避坑吐槽'
    } else if (ev.stance === 'mixed') {
      tagColor = 'warning'
      stanceLabel = '褒贬不一'
    }

    const isXhs = (ev.source || '').toLowerCase().includes('xhs')

    return {
      dot: stanceIcon,
      color: tagColor,
      children: (
        <Card
          size="small"
          hoverable
          style={{
            marginBottom: 12,
            borderLeft: `3px solid ${tagColor === 'success' ? '#52c41a' : tagColor === 'error' ? '#ff4d4f' : '#1677ff'}`,
          }}
          onClick={() => onFocusEvidence?.(ev.evidenceId)}
        >
          <Space direction="vertical" size={4} style={{ width: '100%' }}>
            <Space style={{ width: '100%', justifyContent: 'space-between' }} wrap>
              <Space size={4}>
                <Tag color={isXhs ? 'magenta' : 'orange'}>
                  {isXhs ? '小红书笔记' : '大众点评评价'}
                </Tag>
                <Tag color={tagColor}>{stanceLabel}</Tag>
              </Space>
              {ev.confidence !== undefined && ev.confidence !== null && (
                <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                  置信度 {Math.round(ev.confidence * 100)}%
                </Typography.Text>
              )}
            </Space>

            {ev.title && (
              <Typography.Text strong style={{ fontSize: 13 }}>
                {ev.title}
              </Typography.Text>
            )}

            <Typography.Paragraph
              style={{
                fontSize: 12,
                color: '#262626',
                background: '#fafafa',
                padding: '8px 10px',
                borderRadius: 6,
                marginBottom: 4,
                border: '1px solid #f0f0f0',
              }}
            >
              "{ev.excerpt}"
            </Typography.Paragraph>

            <Space size={8} style={{ fontSize: 11, color: '#8c8c8c' }}>
              {ev.capturedAt && <span>采集时间: {ev.capturedAt}</span>}
              {ev.noteRef && <span>· 笔记: {ev.noteRef}</span>}
              {ev.commentRef && <span>· 评论: {ev.commentRef}</span>}
            </Space>
          </Space>
        </Card>
      ),
    }
  })

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Space direction="vertical" size="small" style={{ width: '100%' }}>
        <Input
          placeholder="按关键词搜索评论证据..."
          prefix={<SearchOutlined />}
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          allowClear
        />

        <Segmented
          block
          value={stanceFilter}
          onChange={(val) => setStanceFilter(val as string)}
          options={[
            { label: `全部 (${evidenceItems.length})`, value: 'all' },
            { label: '好评推荐', value: 'positive' },
            { label: '避坑吐槽', value: 'negative' },
            { label: '有争议', value: 'mixed' },
          ]}
        />
      </Space>

      <Timeline items={timelineItems} style={{ marginTop: 12, paddingLeft: 4 }} />
    </Space>
  )
}
