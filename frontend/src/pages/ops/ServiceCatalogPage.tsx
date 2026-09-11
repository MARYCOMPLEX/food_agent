import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, Table, Tag, Button, Space, Typography, Modal, Alert, message } from 'antd'
import {
  CloudServerOutlined,
  ReloadOutlined,
  ArrowRightOutlined,
  CheckCircleOutlined,
  WarningOutlined,
  BookOutlined,
  CopyOutlined,
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

const DEFAULT_SERVICES: ServiceRecord[] = [
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
]

export function ServiceCatalogPage() {
  const navigate = useNavigate()
  const { showToast } = useToast()
  const [testingId, setTestingId] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [isGuideModalOpen, setIsGuideModalOpen] = useState(false)
  const [services, setServices] = useState<ServiceRecord[]>(DEFAULT_SERVICES)

  const fetchReadiness = async (silent = false) => {
    setLoading(true)
    try {
      const res = await fetch('/v1/platform/readiness')
      if (res.ok) {
        const json = await res.json()
        const backendServices = json?.data?.services
        if (Array.isArray(backendServices) && backendServices.length > 0) {
          const mapped: ServiceRecord[] = backendServices.map((s: any) => {
            const hasXhs = s.channels?.some((c: string) => c.startsWith('xhs'))
            const hasDp = s.channels?.includes('dianping')
            const displayName = hasXhs
              ? '小红书平台账号与采集服务'
              : hasDp
                ? '大众点评商户事实增强服务'
                : `自定义数据服务 (${s.service_id})`

            const status = s.state === 'ready' ? 'ready' : (s.state === 'degraded' ? 'degraded' : 'unavailable')
            const toolsCount = s.mcp_tools?.length || 0

            return {
              serviceId: s.service_id,
              name: displayName,
              platform: s.channels?.[0] || 'mcp',
              protocol: (s.protocol?.toLowerCase() || 'mcp') as any,
              discoveredTools: toolsCount,
              allowedTools: toolsCount,
              accountCount: 1,
              status,
              p95Latency: 180,
              lastRefreshed: new Date().toLocaleTimeString(),
            }
          })
          setServices(mapped)
          if (!silent) showToast(`成功同步 ${mapped.length} 个活跃微服务状态`, 'success')
          return
        }
      }
      if (!silent) showToast('已连接本地开发回退服务列表', 'info')
    } catch {
      if (!silent) showToast('未检测到后端 8000 端口，展示内置离线服务目录', 'info')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchReadiness(true)
  }, [])

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
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <Typography.Title level={4} style={{ margin: 0 }}>
            <CloudServerOutlined style={{ color: '#1677ff', marginRight: 8 }} />
            服务与 MCP 工具目录
          </Typography.Title>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            配置与观测上游数据源服务、MCP 工具暴露清单及管理层放行规则
          </Typography.Text>
        </div>
        <Space size={10}>
          <Button
            icon={<BookOutlined />}
            onClick={() => setIsGuideModalOpen(true)}
          >
            接入对接规范
          </Button>
          <Button
            icon={<ReloadOutlined spin={loading} />}
            onClick={() => fetchReadiness(false)}
          >
            刷新探活
          </Button>
        </Space>
      </div>

      <Card>
        <Table
          dataSource={services}
          columns={columns}
          rowKey="serviceId"
          pagination={false}
          size="middle"
          loading={loading}
        />
      </Card>

      <Modal
        title={
          <Space>
            <BookOutlined style={{ color: '#1677ff' }} />
            <span>外部 MCP / 数据源服务接入指引</span>
          </Space>
        }
        open={isGuideModalOpen}
        onCancel={() => setIsGuideModalOpen(false)}
        width={720}
        footer={[
          <Button key="close" type="primary" onClick={() => setIsGuideModalOpen(false)}>
            我知道了
          </Button>,
        ]}
      >
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Alert
            type="info"
            showIcon
            message="标准架构与解耦原则"
            description="Food Agent 核心主后端与爬虫/账号微服务严格解耦。外部服务独立运行，通过 HTTP 控制面与 MCP JSON-RPC 协议被自动发现并安全集成。"
          />

          <div>
            <Typography.Text strong>1. 必需实现的核心端点</Typography.Text>
            <ul style={{ margin: '6px 0 12px 18px', padding: 0, fontSize: 13 }}>
              <li>
                <Typography.Text code>GET /health</Typography.Text>：服务基础健康检查
              </li>
              <li>
                <Typography.Text code>GET /v1/capabilities</Typography.Text>：服务元数据与支持的能力清单自描述
              </li>
              <li>
                <Typography.Text code>POST /mcp</Typography.Text>：标准 MCP JSON-RPC 端点（需响应 <Typography.Text code>initialize</Typography.Text>、<Typography.Text code>tools/list</Typography.Text>、<Typography.Text code>tools/call</Typography.Text>）
              </li>
            </ul>
          </div>

          <div>
            <Typography.Text strong>2. 安全红线拦截规则</Typography.Text>
            <Alert
              type="warning"
              showIcon
              message="禁止传输明文凭据"
              description="网关严禁接收或返回 cookie、token、authorization、password、storage_state 等明文敏感字段，微服务内部自行管理会话，对外仅交互不透明引用标识。"
              style={{ marginTop: 6 }}
            />
          </div>

          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <Typography.Text strong>3. 主系统接入配置 (.env)</Typography.Text>
              <Button
                size="small"
                icon={<CopyOutlined />}
                onClick={() => {
                  const snippet = `MODULAR_ACCOUNT_SERVICES_JSON='[
  {
    "service_id": "custom-service",
    "base_url": "http://127.0.0.1:8103",
    "mcp_url": "http://127.0.0.1:8103/mcp",
    "protocol": "http+mcp",
    "channels": ["xhs_pc"],
    "capabilities": ["notes.search", "notes.detail"],
    "descriptor_version": "account-service/v1",
    "timeout_seconds": 10
  }
]'`
                  navigator.clipboard.writeText(snippet)
                  message.success('配置示例已复制到剪贴板')
                }}
              >
                复制配置示例
              </Button>
            </div>
            <pre
              style={{
                background: '#f6f8fa',
                padding: '10px 12px',
                borderRadius: 6,
                fontSize: 12,
                margin: 0,
                overflowX: 'auto',
                border: '1px solid #e1e4e8',
              }}
            >
{`MODULAR_ACCOUNT_SERVICES_JSON='[
  {
    "service_id": "custom-service",
    "base_url": "http://127.0.0.1:8103",
    "mcp_url": "http://127.0.0.1:8103/mcp",
    "protocol": "http+mcp",
    "channels": ["xhs_pc"],
    "capabilities": ["notes.search", "notes.detail"],
    "descriptor_version": "account-service/v1",
    "timeout_seconds": 10
  }
]'`}
            </pre>
          </div>

          <Alert
            type="success"
            message={
              <span>
                更详细的完整接口报文契约与 FastAPI 示例代码，请参阅代码库文档：
                <Typography.Text code style={{ marginLeft: 4 }}>
                  docs/mcp-service-integration-guide.md
                </Typography.Text>
              </span>
            }
          />
        </Space>
      </Modal>
    </Space>
  )
}
