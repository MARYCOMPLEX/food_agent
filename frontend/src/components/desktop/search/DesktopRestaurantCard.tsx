import { useState } from 'react'
import {
  Card, Tag, Progress, Typography, Space, Row, Col, Flex,
} from 'antd'
import {
  EnvironmentOutlined, PhoneOutlined, ClockCircleOutlined,
  StarOutlined, CheckCircleOutlined, CloseCircleOutlined,
  DownOutlined, UpOutlined, FireOutlined,
} from '@ant-design/icons'
import type { Restaurant } from '@/types/restaurant'
import { getWanghongLabel } from '@/utils/format'

const { Text, Title } = Typography

function statToPercent(value: string): number {
  const map: Record<string, number> = {
    A: 90, B: 65, C: 35, D: 15,
    '$': 90, '$$': 65, '$$$': 35, '$$$$': 15,
    '快': 90, '较快': 75, '一般': 50, '较慢': 30, '慢': 15,
    '好': 90, '较好': 75, '中等': 50, '较差': 30, '差': 15,
  }
  return map[value] ?? 50
}

function statColor(pct: number): string {
  if (pct >= 75) return '#52c41a'
  if (pct >= 50) return '#faad14'
  return '#ff4d4f'
}

interface Props {
  restaurant: Restaurant
}

export function DesktopRestaurantCard({ restaurant }: Props) {
  const [expanded, setExpanded] = useState(false)
  const r = restaurant
  const wanghong = r.wanghong_analysis
    ? getWanghongLabel(r.wanghong_analysis.score)
    : null

  const wanghongColorMap: Record<string, string> = {
    definitely_local: 'green',
    likely_local: 'cyan',
    unknown: 'default',
    likely_wanghong: 'orange',
    definitely_wanghong: 'red',
  }

  const statsEntries: { label: string; value: string }[] = [
    { label: '口味', value: r.stats.flavor },
    { label: '性价比', value: r.stats.cost },
    { label: '等候', value: r.stats.wait },
    { label: '环境', value: r.stats.env },
  ]

  return (
    <Card
      style={{ marginBottom: 16 }}
      bodyStyle={{ padding: '16px 20px' }}
    >
      {/* Header */}
      <Flex justify="space-between" align="center" wrap="wrap" gap={8}>
        <Space size={8} align="center">
          <Title level={5} style={{ margin: 0 }}>{r.name}</Title>
          {wanghong && r.wanghong_analysis && (
            <Tag color={wanghongColorMap[r.wanghong_analysis.score] ?? 'default'}>
              {wanghong.text}
            </Tag>
          )}
        </Space>
        {r.location && (
          <Text type="secondary">
            <EnvironmentOutlined style={{ marginRight: 4 }} />
            {r.location}
          </Text>
        )}
      </Flex>

      {/* Tags */}
      {r.tags.length > 0 && (
        <Flex wrap="wrap" gap={4} style={{ marginTop: 10 }}>
          {r.tags.map((tag) => (
            <Tag key={tag}>{tag}</Tag>
          ))}
        </Flex>
      )}

      {/* Confidence + features */}
      <Flex align="center" gap={12} style={{ marginTop: 12 }}>
        <Text type="secondary" style={{ whiteSpace: 'nowrap' }}>
          可信度
        </Text>
        <Progress
          percent={Math.round(r.confidence * 100)}
          size="small"
          style={{ flex: 1, maxWidth: 200 }}
          strokeColor={r.confidence >= 0.7 ? '#52c41a' : r.confidence >= 0.4 ? '#faad14' : '#ff4d4f'}
        />
      </Flex>

      {r.features.length > 0 && (
        <Text type="secondary" style={{ display: 'block', marginTop: 8, fontSize: 13 }}>
          {r.features.join(' / ')}
        </Text>
      )}

      {/* Expand toggle */}
      <div
        style={{ marginTop: 12, cursor: 'pointer', color: '#1677ff', fontSize: 13 }}
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? <UpOutlined /> : <DownOutlined />}
        <span style={{ marginLeft: 6 }}>{expanded ? '收起详情' : '展开详情'}</span>
      </div>

      {/* Expanded section */}
      {expanded && (
        <div style={{ marginTop: 16 }}>
          {/* Pros & Cons */}
          {(r.pros.length > 0 || r.cons.length > 0) && (
            <Row gutter={24} style={{ marginBottom: 16 }}>
              {[
                { items: r.pros, color: '#52c41a', icon: <CheckCircleOutlined />, title: '优点' },
                { items: r.cons, color: '#ff4d4f', icon: <CloseCircleOutlined />, title: '缺点' },
              ].map(({ items, color, icon, title }) => (
                <Col span={12} key={title}>
                  <Text strong style={{ color }}>{icon} {title}</Text>
                  <ul style={{ paddingLeft: 18, margin: '6px 0 0' }}>
                    {items.map((t, i) => <li key={i}><Text style={{ fontSize: 13 }}>{t}</Text></li>)}
                  </ul>
                </Col>
              ))}
            </Row>
          )}

          {/* Must-try & Blacklist */}
          {r.mustTry.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <Text strong><FireOutlined style={{ color: '#52c41a' }} /> 必点菜</Text>
              <Flex wrap="wrap" gap={4} style={{ marginTop: 6 }}>
                {r.mustTry.map((d) => <Tag color="green" key={d.name}>{d.name}</Tag>)}
              </Flex>
            </div>
          )}
          {r.blackList.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <Text strong><CloseCircleOutlined style={{ color: '#ff4d4f' }} /> 避雷菜</Text>
              <Flex wrap="wrap" gap={4} style={{ marginTop: 6 }}>
                {r.blackList.map((d) => <Tag color="red" key={d.name}>{d.name}</Tag>)}
              </Flex>
            </div>
          )}

          {/* Stats */}
          <Row gutter={[16, 8]} style={{ marginBottom: 16 }}>
            {statsEntries.map(({ label, value }) => {
              const pct = statToPercent(value)
              return (
                <Col span={6} key={label}>
                  <Text style={{ fontSize: 12 }} type="secondary">{label}</Text>
                  <Progress
                    percent={pct}
                    size="small"
                    format={() => value}
                    strokeColor={statColor(pct)}
                  />
                </Col>
              )
            })}
          </Row>

          {/* POI details */}
          {r.poi_details && (
            <Card size="small" style={{ background: '#fafafa' }}>
              <Space direction="vertical" size={4} style={{ width: '100%' }}>
                {([
                  [r.poi_details.address, EnvironmentOutlined],
                  [r.poi_details.tel, PhoneOutlined],
                  [r.poi_details.opentime, ClockCircleOutlined],
                  [r.poi_details.rating, StarOutlined],
                ] as const).map(([val, Icon]) => val ? (
                  <Text key={String(val)} style={{ fontSize: 13 }}>
                    <Icon style={{ marginRight: 6 }} />{val}
                  </Text>
                ) : null)}
              </Space>
            </Card>
          )}

          {/* Source notes count */}
          {r.source_notes.length > 0 && (
            <Text type="secondary" style={{ display: 'block', marginTop: 10, fontSize: 12 }}>
              参考了 {r.source_notes.length} 条笔记
            </Text>
          )}
        </div>
      )}
    </Card>
  )
}
