import React, { useState } from 'react'
import { Card, Row, Col, Statistic, Table, Input, Tag, Space, Typography } from 'antd'
import {
  DatabaseOutlined,
  SearchOutlined,
  CheckCircleOutlined,
  SafetyCertificateOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons'

interface EvidenceBundleRecord {
  bundleId: string
  familyId: string
  version: string
  itemCount: number
  freshnessHours: number
  sourcesBreakdown: Record<string, number>
  dedupRate: string
  maskingCheck: 'passed' | 'warning'
  createdAt: string
}

export function EvidenceObservabilityPage() {
  const [searchQuery, setSearchQuery] = useState<string>('')

  const [bundles] = useState<EvidenceBundleRecord[]>([
    {
      bundleId: 'bundle_cd_hotpot_v1',
      familyId: 'family_cd_spicy_dining',
      version: '1.2.0',
      itemCount: 48,
      freshnessHours: 3.5,
      sourcesBreakdown: { xhs_pc: 36, dianping: 12 },
      dedupRate: '98.4%',
      maskingCheck: 'passed',
      createdAt: '2026-09-11 00:45:00',
    },
    {
      bundleId: 'bundle_gz_tea_v2',
      familyId: 'family_gz_morning_tea',
      version: '2.0.1',
      itemCount: 62,
      freshnessHours: 12.0,
      sourcesBreakdown: { xhs_pc: 48, dianping: 14 },
      dedupRate: '96.8%',
      maskingCheck: 'passed',
      createdAt: '2026-09-10 18:20:00',
    },
    {
      bundleId: 'bundle_sh_bistro_v1',
      familyId: 'family_sh_dating_scenes',
      version: '1.0.0',
      itemCount: 28,
      freshnessHours: 1.2,
      sourcesBreakdown: { xhs_pc: 22, dianping: 6 },
      dedupRate: '99.1%',
      maskingCheck: 'passed',
      createdAt: '2026-09-11 01:00:00',
    },
  ])

  const filteredBundles = bundles.filter(
    (b) =>
      b.bundleId.toLowerCase().includes(searchQuery.toLowerCase()) ||
      b.familyId.toLowerCase().includes(searchQuery.toLowerCase()),
  )

  const columns = [
    {
      title: 'Bundle ID / 版本',
      key: 'bundleId',
      render: (_: any, record: EvidenceBundleRecord) => (
        <Space direction="vertical" size={1}>
          <Typography.Text code strong style={{ fontSize: 13 }}>
            {record.bundleId}
          </Typography.Text>
          <Tag color="blue" style={{ fontSize: 10, margin: 0 }}>
            v{record.version}
          </Tag>
        </Space>
      ),
    },
    {
      title: '查询家族 (Family ID)',
      dataIndex: 'familyId',
      key: 'familyId',
      render: (val: string) => <span style={{ fontSize: 13 }}>{val}</span>,
    },
    {
      title: '条目容量与来源',
      key: 'items',
      render: (_: any, record: EvidenceBundleRecord) => (
        <Space direction="vertical" size={2}>
          <Typography.Text strong>{record.itemCount} 条评论</Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 11 }}>
            小红书: {record.sourcesBreakdown.xhs_pc} / 点评: {record.sourcesBreakdown.dianping}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: '时效窗口',
      dataIndex: 'freshnessHours',
      key: 'freshnessHours',
      render: (hours: number) => (
        <Space>
          <ClockCircleOutlined style={{ color: '#8c8c8c' }} />
          <span>{hours}h 前更新</span>
        </Space>
      ),
    },
    {
      title: '去重准确率',
      dataIndex: 'dedupRate',
      key: 'dedupRate',
      render: (rate: string) => (
        <Typography.Text strong style={{ color: '#52c41a' }}>
          {rate}
        </Typography.Text>
      ),
    },
    {
      title: '脱敏合规质检',
      dataIndex: 'maskingCheck',
      key: 'maskingCheck',
      render: (check: string) => (
        <Tag icon={<CheckCircleOutlined />} color="success">
          {check.toUpperCase()}
        </Tag>
      ),
    },
    {
      title: '生成时间',
      dataIndex: 'createdAt',
      key: 'createdAt',
      render: (val: string) => <Typography.Text type="secondary" style={{ fontSize: 11 }}>{val}</Typography.Text>,
    },
  ]

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
        <div>
          <Typography.Title level={4} style={{ margin: 0 }}>
            <DatabaseOutlined style={{ color: '#1677ff', marginRight: 8 }} />
            证据数据质量与 Bundle 观测
          </Typography.Title>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            监控 Evidence Bundle 版本游标、去重比率、隐私脱敏合规性与时效窗口
          </Typography.Text>
        </div>

        <Input
          placeholder="搜索 Bundle ID 或 Family..."
          prefix={<SearchOutlined />}
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          style={{ width: 260 }}
          allowClear
        />
      </div>

      <Row gutter={[16, 16]}>
        <Col span={24} sm={8}>
          <Card>
            <Statistic
              title="活动 Evidence Bundles"
              value={3}
              suffix="组"
              prefix={<DatabaseOutlined style={{ color: '#1677ff' }} />}
            />
            <Typography.Text type="success" style={{ fontSize: 11, display: 'block', marginTop: 4 }}>
              全量版本指针同步正常
            </Typography.Text>
          </Card>
        </Col>
        <Col span={24} sm={8}>
          <Card>
            <Statistic
              title="评论自动去重准确度"
              value={98.1}
              suffix="%"
              prefix={<CheckCircleOutlined style={{ color: '#52c41a' }} />}
            />
            <Typography.Text type="secondary" style={{ fontSize: 11, display: 'block', marginTop: 4 }}>
              多笔记重复评论实体归并
            </Typography.Text>
          </Card>
        </Col>
        <Col span={24} sm={8}>
          <Card>
            <Statistic
              title="隐私脱敏与敏感词过滤"
              value={100}
              suffix="%"
              prefix={<SafetyCertificateOutlined style={{ color: '#52c41a' }} />}
            />
            <Typography.Text type="secondary" style={{ fontSize: 11, display: 'block', marginTop: 4 }}>
              手机号/敏感词已严格掩码
            </Typography.Text>
          </Card>
        </Col>
      </Row>

      <Card>
        <Table
          dataSource={filteredBundles}
          columns={columns}
          rowKey="bundleId"
          pagination={false}
          size="middle"
        />
      </Card>
    </Space>
  )
}
