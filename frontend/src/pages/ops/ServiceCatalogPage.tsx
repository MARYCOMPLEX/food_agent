import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, Table, Tag, Button, Space, Typography } from 'antd'
import {
  CloudServerOutlined,
  ReloadOutlined,
  ArrowRightOutlined,
  CheckCircleOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import { useToast } from '../../context/ToastContext'

interface ServiceRecord {
  serviceId: string
  name: string
  platform: string
  protocol: 'mcp' | 'http' | 'sse'
  discoveredTools: number
  allowedTools: number
  accountCount: number
  status: 'ready' | 'degraded' | 'unavailable'
  p95Latency: number
  lastRefreshed: string
}

export function ServiceCatalogPage() {
  const navigate = useNavigate()
  const { showToast } = useToast()
  const [testingId, setTestingId] = useState<string | null>(null)

  const [services] = useState<ServiceRecord[]>([
    {
      serviceId: 'service_xhs_comment_collector',
      name: '小红书评论与笔记深度采集适配器',
      platform: 'xhs_pc',
      protocol: 'mcp',
      discoveredTools: 6,
      allowedTools: 6,
      accountCount: 2,
      status: 'ready',
      p95Latency: 380,
      lastRefreshed: '2026-09-11 01:10:00',
    },
    {
      serviceId: 'service_dianping_poi_enricher',
      name: '大众点评店铺与菜品事实补充服务',
      platform: 'dianping',
      protocol: 'mcp',
      discoveredTools: 5,
      allowedTools: 4,
      accountCount: 2,
      status: 'degraded',
      p95Latency: 640,
      lastRefreshed: '2026-09-11 01:05:00',
    },
    {
      serviceId: 'service_geo_router',
      name: '商圈与地理编码辅助路由',
      platform: 'system',
      protocol: 'http',
      discoveredTools: 3,
      allowedTools: 2,
      accountCount: 1,
      status: 'ready',
      p95Latency: 120,
      lastRefreshed: '2026-09-11 00:30:00',
    },
  ])

  const handleTestConnection = (id: string, e: React.MouseEvent) => {
    e.stopPropagation()
    setTestingId(id)
    setTimeout(() => {
      setTestingId(null)
      showToast('通道连通性测试通过，Ping 延迟正常', 'success')
    }, 900)
  }

  const columns = [
    {
      title: '服务名称 / ID',
      key: 'name',
      render: (_: any, record: ServiceRecord) => (
        <Space direction="vertical" size={2}>
          <Typography.Text
            strong
            style={{ color: '#1677ff', cursor: 'pointer' }}
            onClick={() => navigate(`/ops/services/${record.serviceId}`)}
          >
            {record.name}
          </Typography.Text>
          <Typography.Text type="secondary" code style={{ fontSize: 11 }}>
            {record.serviceId}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: '协议类型',
      dataIndex: 'protocol',
      key: 'protocol',
      render: (val: string) => <Tag color="geekblue">{val.toUpperCase()}</Tag>,
    },
    {
      title: '工具目录放行',
      key: 'tools',
      render: (_: any, record: ServiceRecord) => (
        <Space>
          <span>{record.allowedTools} / {record.discoveredTools}</span>
          {record.allowedTools === record.discoveredTools ? (
            <Tag color="success">全量放行</Tag>
          ) : (
            <Tag color="warning">部分放行</Tag>
          )}
        </Space>
      ),
    },
    {
      title: '可用账号',
      dataIndex: 'accountCount',
      key: 'accountCount',
      render: (val: number) => `${val} 个`,
    },
    {
      title: 'P95 延迟',
      dataIndex: 'p95Latency',
      key: 'p95Latency',
      render: (val: number) => <Typography.Text code>{val}ms</Typography.Text>,
    },
    {
      title: '健康状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) =>
        status === 'ready' ? (
          <Tag icon={<CheckCircleOutlined />} color="success">
            READY
          </Tag>
        ) : (
          <Tag icon={<WarningOutlined />} color="warning">
            DEGRADED
          </Tag>
        ),
    },
    {
      title: '操作',
      key: 'actions',
      render: (_: any, record: ServiceRecord) => (
        <Space size={8}>
          <Button
            size="small"
            icon={<ReloadOutlined spin={testingId === record.serviceId} />}
            disabled={testingId === record.serviceId}
            onClick={(e) => handleTestConnection(record.serviceId, e)}
          >
            {testingId === record.serviceId ? '探测中...' : '测试连通性'}
          </Button>

          <Button
            type="primary"
            size="small"
            icon={<ArrowRightOutlined />}
            onClick={() => navigate(`/ops/services/${record.serviceId}`)}
          >
            工具详情
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <div>
        <Typography.Title level={4} style={{ margin: 0 }}>
          <CloudServerOutlined style={{ color: '#1677ff', marginRight: 8 }} />
          服务与 MCP 工具目录
        </Typography.Title>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          配置与观测上游数据源服务、MCP 工具暴露清单及管理层放行规则
        </Typography.Text>
      </div>

      <Card>
        <Table
          dataSource={services}
          columns={columns}
          rowKey="serviceId"
          pagination={false}
          size="middle"
        />
      </Card>
    </Space>
  )
}
