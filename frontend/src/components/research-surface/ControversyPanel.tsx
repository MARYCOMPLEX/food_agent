import React from 'react'
import { Card, Collapse, Tag, Button, Empty, Typography, Space, Row, Col } from 'antd'
import {
  WarningOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  SearchOutlined,
  LikeOutlined,
  DislikeOutlined,
} from '@ant-design/icons'
import type {
  ResearchControversyViewV1,
  ResearchEvidenceItemV1,
} from '../../shared/contracts/research'

interface ControversyPanelProps {
  controversies: ResearchControversyViewV1[]
  evidenceItems?: ResearchEvidenceItemV1[]
  onVerifyControversy?: (controversy: ResearchControversyViewV1) => void
  onSelectEvidence?: (evidenceId: string) => void
}

export function ControversyPanel({
  controversies,
  evidenceItems = [],
  onVerifyControversy,
  onSelectEvidence,
}: ControversyPanelProps) {
  if (!controversies || controversies.length === 0) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description="暂未提炼出体验冲突的评论争议点"
      />
    )
  }

  const collapseItems = controversies.map((item) => {
    let statusTag = <Tag color="warning" icon={<WarningOutlined />}>仍有分歧</Tag>
    if (item.status === 'resolved') {
      statusTag = <Tag color="success" icon={<CheckCircleOutlined />}>已核清</Tag>
    } else if (item.status === 'partially_resolved') {
      statusTag = <Tag color="default" icon={<ClockCircleOutlined />}>部分核清</Tag>
    }

    const sides = item.sides || []

    return {
      key: item.controversyId,
      label: (
        <Space wrap>
          {statusTag}
          <Typography.Text strong style={{ fontSize: 13 }}>
            {item.topic}
          </Typography.Text>
        </Space>
      ),
      children: (
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          {item.summary && (
            <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 8 }}>
              争议综述：{item.summary}
            </Typography.Paragraph>
          )}

          <Row gutter={[12, 12]}>
            {sides.map((side, i) => {
              const isPro = i === 0
              return (
                <Col span={24} sm={12} key={side.sideId || i}>
                  <Card
                    size="small"
                    title={
                      <Space>
                        {isPro ? (
                          <LikeOutlined style={{ color: '#52c41a' }} />
                        ) : (
                          <DislikeOutlined style={{ color: '#ff4d4f' }} />
                        )}
                        <span style={{ fontSize: 12 }}>{side.label || (isPro ? '支持方立场' : '反对方立场')}</span>
                      </Space>
                    }
                    bordered
                    style={{
                      height: '100%',
                      background: isPro ? '#f6ffed' : '#fff1f0',
                      borderColor: isPro ? '#b7eb8f' : '#ffa39e',
                    }}
                  >
                    <Space direction="vertical" size={4} style={{ width: '100%' }}>
                      {side.summary && (
                        <Typography.Text style={{ fontSize: 12 }}>
                          {side.summary}
                        </Typography.Text>
                      )}

                      {side.evidenceRefs && side.evidenceRefs.length > 0 && (
                        <div style={{ marginTop: 6 }}>
                          <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                            引用 {side.evidenceRefs.length} 条评论证据
                          </Typography.Text>
                        </div>
                      )}
                    </Space>
                  </Card>
                </Col>
              )
            })}
          </Row>

          {onVerifyControversy && (
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 8 }}>
              <Button
                type="primary"
                ghost
                size="small"
                icon={<SearchOutlined />}
                onClick={() => onVerifyControversy(item)}
              >
                针对此争议向 Agent 追问核实
              </Button>
            </div>
          )}
        </Space>
      ),
    }
  })

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        共发现 {controversies.length} 项用户评论中的体验分歧焦点：
      </Typography.Text>
      <Collapse defaultActiveKey={controversies.map((c) => c.controversyId)} items={collapseItems} />
    </Space>
  )
}
