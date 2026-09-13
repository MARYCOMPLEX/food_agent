import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Card,
  Table,
  Tag,
  Button,
  Space,
  Typography,
  Modal,
  Alert,
  message,
  Switch,
  Form,
  Input,
  InputNumber,
  Select,
  Popconfirm,
  Tooltip,
} from 'antd'
import {
  CloudServerOutlined,
  ReloadOutlined,
  ArrowRightOutlined,
  CheckCircleOutlined,
  WarningOutlined,
  CloseCircleOutlined,
  BookOutlined,
  CopyOutlined,
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  ApiOutlined,
} from '@ant-design/icons'
import { useToast } from '../../context/ToastContext'

interface ServiceRecord {
  serviceId: string
  name: string
  baseUrl?: string
  mcpUrl?: string
  platform: string
  protocol: 'mcp' | 'http' | 'sse' | 'http+mcp'
  channels?: string[]
  capabilities?: string[]
  timeoutSeconds?: number
  enabled: boolean
  discoveredTools: number
  allowedTools: number
  accountCount: number
  status: 'ready' | 'degraded' | 'unavailable' | 'disabled'
  p95Latency: number
  lastRefreshed: string
}

export function ServiceCatalogPage() {
  const navigate = useNavigate()
  const { showToast } = useToast()
  const [testingId, setTestingId] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [isGuideModalOpen, setIsGuideModalOpen] = useState(false)
  const [services, setServices] = useState<ServiceRecord[]>([])

  // Add / Edit Modal state
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [editingService, setEditingService] = useState<ServiceRecord | null>(null)
  const [probeResult, setProbeResult] = useState<any | null>(null)
  const [probing, setProbing] = useState(false)
  const [form] = Form.useForm()

  const fetchServices = async (silent = false) => {
    setLoading(true)
    try {
      // 1. Fetch from persistent database ops endpoint
      const res = await fetch('/v1/platform/ops/mcp-services')
      if (res.ok) {
        const json = await res.json()
        const backendServices = json?.data
        if (Array.isArray(backendServices) && backendServices.length > 0) {
          const mapped: ServiceRecord[] = backendServices.map((s: any) => {
            const hasXhs = s.channels?.some((c: string) => c.startsWith('xhs'))
            const hasDp = s.channels?.includes('dianping')
            const displayName =
              s.name ||
              (hasXhs
                ? '小红书平台账号与采集服务'
                : hasDp
                  ? '大众点评商户事实增强服务'
                  : `数据服务 (${s.service_id})`)

            let status: ServiceRecord['status'] = 'unavailable'
            if (!s.enabled) {
              status = 'disabled'
            } else if (s.live_state === 'ready') {
              status = 'ready'
            } else if (s.live_state === 'degraded') {
              status = 'degraded'
            }

            const toolsCount = s.tools_count ?? (s.discovered_tools?.length || 0)

            return {
              serviceId: s.service_id,
              name: displayName,
              baseUrl: s.base_url,
              mcpUrl: s.mcp_url,
              platform: s.channels?.[0] || 'mcp',
              protocol: (s.protocol?.toLowerCase() || 'http+mcp') as any,
              channels: s.channels || [],
              capabilities: s.capabilities || [],
              timeoutSeconds: s.timeout_seconds || 30,
              enabled: Boolean(s.enabled),
              discoveredTools: toolsCount,
              allowedTools: toolsCount,
              accountCount: 1,
              status,
              p95Latency: s.latency_ms || 120,
              lastRefreshed: s.updated_at
                ? new Date(s.updated_at).toLocaleTimeString()
                : new Date().toLocaleTimeString(),
            }
          })
          setServices(mapped)
          if (!silent) showToast(`成功同步 ${mapped.length} 个 MCP 服务配置与运行时状态`, 'success')
          return
        }
      }

      // 2. Fallback to readiness endpoint if ops empty
      const readyRes = await fetch('/v1/platform/readiness')
      if (readyRes.ok) {
        const readyJson = await readyRes.json()
        const rServices = readyJson?.data?.services
        if (Array.isArray(rServices) && rServices.length > 0) {
          const mapped: ServiceRecord[] = rServices.map((s: any) => ({
            serviceId: s.service_id,
            name: s.service_id,
            platform: s.channels?.[0] || 'mcp',
            protocol: (s.protocol?.toLowerCase() || 'mcp') as any,
            channels: s.channels || [],
            enabled: true,
            discoveredTools: s.mcp_tools?.length || 0,
            allowedTools: s.mcp_tools?.length || 0,
            accountCount: 1,
            status: s.state === 'ready' ? 'ready' : 'degraded',
            p95Latency: 160,
            lastRefreshed: new Date().toLocaleTimeString(),
          }))
          setServices(mapped)
          return
        }
      }

      if (!silent) showToast('已连接本地服务目录（暂无注册服务）', 'info')
    } catch {
      setServices([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchServices(true)
  }, [])

  // Inline connection probe
  const handleTestConnection = async (record: ServiceRecord, e: React.MouseEvent) => {
    e.stopPropagation()
    setTestingId(record.serviceId)
    try {
      const res = await fetch('/v1/platform/ops/mcp-services/probe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          service_id: record.serviceId,
          base_url: record.baseUrl || 'http://127.0.0.1:8103',
          mcp_url: record.mcpUrl,
          protocol: record.protocol,
          channels: record.channels || [record.platform],
          timeout_seconds: 10.0,
        }),
      })
      const data = await res.json()
      if (data.success && data.data?.state === 'ready') {
        const count = data.data.tools?.length || 0
        showToast(`连通性正常！耗时 ${data.data.latency_ms}ms，发现 ${count} 个可用工具`, 'success')
      } else {
        const detail = data.data?.detail || data.error || '无法建立握手连接'
        showToast(`探测警告: ${detail}`, 'warning')
      }
    } catch (err: any) {
      showToast(`连接失败: ${err.message}`, 'error')
    } finally {
      setTestingId(null)
    }
  }

  // Inline toggle enable / disable
  const handleToggleEnable = async (record: ServiceRecord, checked: boolean) => {
    try {
      const res = await fetch(`/v1/platform/ops/mcp-services/${record.serviceId}/toggle`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: checked }),
      })
      if (res.ok) {
        showToast(`服务「${record.name}」已${checked ? '启用' : '禁用'}并即时热更新`, 'success')
        fetchServices(true)
      } else {
        showToast('切换服务状态失败', 'error')
      }
    } catch {
      showToast('网络错误，切换服务状态失败', 'error')
    }
  }

  // Delete service
  const handleDeleteService = async (serviceId: string) => {
    try {
      const res = await fetch(`/v1/platform/ops/mcp-services/${serviceId}`, {
        method: 'DELETE',
      })
      if (res.ok) {
        showToast('服务已成功从数据库移除并注销', 'success')
        fetchServices(true)
      } else {
        showToast('删除服务失败', 'error')
      }
    } catch {
      showToast('网络错误，删除失败', 'error')
    }
  }

  // Open modal for Create
  const handleOpenCreate = () => {
    setEditingService(null)
    setProbeResult(null)
    form.resetFields()
    form.setFieldsValue({
      service_id: '',
      name: '',
      base_url: 'http://127.0.0.1:8103',
      mcp_url: '',
      protocol: 'http+mcp',
      channels: ['dianping'],
      timeout_seconds: 30,
      enabled: true,
    })
    setIsModalOpen(true)
  }

  // Open modal for Edit
  const handleOpenEdit = (record: ServiceRecord, e: React.MouseEvent) => {
    e.stopPropagation()
    setEditingService(record)
    setProbeResult(null)
    form.resetFields()
    form.setFieldsValue({
      service_id: record.serviceId,
      name: record.name,
      base_url: record.baseUrl || '',
      mcp_url: record.mcpUrl || '',
      protocol: record.protocol || 'http+mcp',
      channels: record.channels || [record.platform],
      timeout_seconds: record.timeoutSeconds || 30,
      enabled: record.enabled,
    })
    setIsModalOpen(true)
  }

  // Probe from inside modal
  const handleModalProbe = async () => {
    try {
      const values = await form.validateFields(['base_url', 'protocol', 'channels'])
      setProbing(true)
      setProbeResult(null)
      const res = await fetch('/v1/platform/ops/mcp-services/probe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          service_id: form.getFieldValue('service_id') || 'probe-test',
          base_url: values.base_url,
          mcp_url: form.getFieldValue('mcp_url') || null,
          protocol: values.protocol,
          channels: values.channels,
          timeout_seconds: 10.0,
        }),
      })
      const data = await res.json()
      if (data.success) {
        setProbeResult(data.data)
      } else {
        setProbeResult({ state: 'error', detail: data.error || data.message })
      }
    } catch {
      // form validation failed
    } finally {
      setProbing(false)
    }
  }

  // Submit Modal Form (Save to DB & Hot Reload)
  const handleModalSubmit = async () => {
    try {
      const values = await form.validateFields()
      const isEdit = Boolean(editingService)
      const url = isEdit
        ? `/v1/platform/ops/mcp-services/${editingService!.serviceId}`
        : '/v1/platform/ops/mcp-services'
      const method = isEdit ? 'PUT' : 'POST'

      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          service_id: values.service_id,
          name: values.name,
          base_url: values.base_url,
          mcp_url: values.mcp_url || null,
          protocol: values.protocol,
          channels: values.channels,
          timeout_seconds: values.timeout_seconds || 30,
          enabled: values.enabled !== false,
        }),
      })

      if (res.ok) {
        showToast(
          isEdit ? '服务配置已持久化更新并热重载' : '新 MCP 服务已保存到数据库并即时加载！',
          'success'
        )
        setIsModalOpen(false)
        fetchServices(true)
      } else {
        const err = await res.json()
        showToast(`保存失败: ${err.message || err.error || '请求错误'}`, 'error')
      }
    } catch {
      // form error
    }
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
          <Space size={4}>
            <Typography.Text type="secondary" code style={{ fontSize: 11 }}>
              {record.serviceId}
            </Typography.Text>
            {record.baseUrl && (
              <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                ({record.baseUrl})
              </Typography.Text>
            )}
          </Space>
        </Space>
      ),
    },
    {
      title: '协议',
      dataIndex: 'protocol',
      key: 'protocol',
      render: (val: string) => <Tag color="geekblue">{val.toUpperCase()}</Tag>,
    },
    {
      title: '渠道',
      key: 'channels',
      render: (_: any, record: ServiceRecord) => (
        <Space size={4} wrap>
          {(record.channels && record.channels.length > 0 ? record.channels : [record.platform]).map(
            (c) => (
              <Tag key={c} color="purple">
                {c}
              </Tag>
            )
          )}
        </Space>
      ),
    },
    {
      title: '工具放行',
      key: 'tools',
      render: (_: any, record: ServiceRecord) => (
        <Space>
          <span>
            {record.allowedTools} / {record.discoveredTools}
          </span>
          {record.discoveredTools > 0 ? (
            <Tag color="success">已发现 {record.discoveredTools} 个</Tag>
          ) : (
            <Tag color="default">待探活</Tag>
          )}
        </Space>
      ),
    },
    {
      title: '健康状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: ServiceRecord['status']) => {
        if (status === 'ready') {
          return (
            <Tag icon={<CheckCircleOutlined />} color="success">
              READY
            </Tag>
          )
        }
        if (status === 'degraded') {
          return (
            <Tag icon={<WarningOutlined />} color="warning">
              DEGRADED
            </Tag>
          )
        }
        if (status === 'disabled') {
          return (
            <Tag icon={<CloseCircleOutlined />} color="default">
              DISABLED
            </Tag>
          )
        }
        return (
          <Tag icon={<WarningOutlined />} color="error">
            UNAVAILABLE
          </Tag>
        )
      },
    },
    {
      title: '在线状态',
      key: 'enabled',
      render: (_: any, record: ServiceRecord) => (
        <Tooltip title={record.enabled ? '点击禁用该服务' : '点击启用该服务'}>
          <Switch
            checked={record.enabled}
            onChange={(checked) => handleToggleEnable(record, checked)}
          />
        </Tooltip>
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
            onClick={(e) => handleTestConnection(record, e)}
          >
            {testingId === record.serviceId ? '探测中...' : '测试连通性'}
          </Button>

          <Button
            size="small"
            icon={<EditOutlined />}
            onClick={(e) => handleOpenEdit(record, e)}
          >
            编辑
          </Button>

          <Popconfirm
            title="确认删除该 MCP 服务？"
            description="删除后将从数据库彻底移除并在运行时注销。"
            onConfirm={() => handleDeleteService(record.serviceId)}
            okText="确认删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
          >
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>

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
            数据库持久化与实时在线热配置，支持即时接入大众点评、小红书等第三方 MCP 数据源
          </Typography.Text>
        </div>
        <Space size={10}>
          <Button icon={<BookOutlined />} onClick={() => setIsGuideModalOpen(true)}>
            接入对接规范
          </Button>
          <Button icon={<ReloadOutlined spin={loading} />} onClick={() => fetchServices(false)}>
            刷新探活
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={handleOpenCreate}>
            添加 MCP 数据源
          </Button>
        </Space>
      </div>

      <Card>
        <Table
          dataSource={services}
          columns={columns}
          rowKey="serviceId"
          pagination={false}
          loading={loading}
          locale={{ emptyText: '暂无注册的 MCP 数据源，点击右上角「添加 MCP 数据源」即可即时接入' }}
        />
      </Card>

      {/* Add / Edit MCP Service Modal */}
      <Modal
        title={
          <Space>
            <ApiOutlined style={{ color: '#1677ff' }} />
            <span>{editingService ? '编辑 MCP 数据源服务' : '添加 MCP 数据源服务'}</span>
          </Space>
        }
        open={isModalOpen}
        onCancel={() => setIsModalOpen(false)}
        onOk={handleModalSubmit}
        okText="保存并即时生效"
        cancelText="取消"
        width={650}
        destroyOnClose
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item
            name="service_id"
            label="服务唯一标识 (service_id)"
            rules={[
              { required: true, message: '请输入服务唯一标识' },
              { pattern: /^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/, message: '支持字母、数字、下划线、短横线' },
            ]}
            extra="如: dianping-service, xhs-crawler-service"
          >
            <Input disabled={Boolean(editingService)} placeholder="dianping-service" />
          </Form.Item>

          <Form.Item
            name="name"
            label="服务友好显示名称"
            rules={[{ required: true, message: '请输入服务名称' }]}
            extra="如: 大众点评商户与笔记深度数据源"
          >
            <Input placeholder="大众点评数据采集微服务" />
          </Form.Item>

          <Form.Item
            name="base_url"
            label="基础服务地址 (Base URL)"
            rules={[{ required: true, message: '请输入微服务 HTTP 访问根地址' }]}
            extra="如: http://127.0.0.1:8103"
          >
            <Input placeholder="http://127.0.0.1:8103" />
          </Form.Item>

          <Form.Item
            name="mcp_url"
            label="MCP 端点地址 (可选)"
            extra="留空默认使用 {Base URL}/mcp"
          >
            <Input placeholder="http://127.0.0.1:8103/mcp (选填)" />
          </Form.Item>

          <Space style={{ display: 'flex', width: '100%' }} align="start">
            <Form.Item
              name="protocol"
              label="接入协议"
              rules={[{ required: true }]}
              style={{ flex: 1 }}
            >
              <Select
                options={[
                  { label: 'http+mcp (推荐全功能模式)', value: 'http+mcp' },
                  { label: 'mcp (轻量工具模式)', value: 'mcp' },
                  { label: 'http (传统控制面模式)', value: 'http' },
                ]}
              />
            </Form.Item>

            <Form.Item
              name="timeout_seconds"
              label="超时时间 (秒)"
              rules={[{ required: true }]}
              style={{ width: 140 }}
            >
              <InputNumber min={1} max={120} style={{ width: '100%' }} />
            </Form.Item>
          </Space>

          <Form.Item
            name="channels"
            label="适配平台渠道 (Channels)"
            rules={[{ required: true, message: '请至少选择或输入一个平台渠道' }]}
            extra="数据源归属的平台标识。支持内置预设，也支持直接回车输入任意全新自定义平台（如 meituan、amap、douyin 等）"
          >
            <Select
              mode="tags"
              options={[
                { label: 'dianping (大众点评)', value: 'dianping' },
                { label: 'xhs_pc (小红书 PC端)', value: 'xhs_pc' },
                { label: 'xhs_creator (小红书创作者端)', value: 'xhs_creator' },
                { label: 'meituan (美团/外卖)', value: 'meituan' },
                { label: 'amap (高德地图/POI)', value: 'amap' },
                { label: 'douyin (抖音美食/探店)', value: 'douyin' },
              ]}
              placeholder="选择预设渠道，或直接键盘输入全新平台名按回车"
            />
          </Form.Item>

          <Form.Item name="enabled" label="立即启用" valuePropName="checked">
            <Switch defaultChecked />
          </Form.Item>

          <div style={{ borderTop: '1px solid #f0f0f0', paddingTop: 16, marginTop: 8 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <Typography.Text type="secondary">在保存前验证服务连接：</Typography.Text>
              <Button
                icon={<ReloadOutlined spin={probing} />}
                loading={probing}
                onClick={handleModalProbe}
              >
                测试连通性并探测工具
              </Button>
            </div>

            {probeResult && (
              <div style={{ marginTop: 12 }}>
                {probeResult.state === 'ready' ? (
                  <Alert
                    type="success"
                    showIcon
                    message={`连通成功！延迟: ${probeResult.latency_ms}ms`}
                    description={
                      <div>
                        <div>发现 {probeResult.tools?.length || 0} 个暴露的 MCP 工具:</div>
                        <ul style={{ margin: '4px 0 0 16px', padding: 0 }}>
                          {(probeResult.tools || []).map((t: any) => (
                            <li key={t.name}>
                              <Typography.Text code>{t.name}</Typography.Text> - {t.description || '无描述'}
                            </li>
                          ))}
                        </ul>
                      </div>
                    }
                  />
                ) : (
                  <Alert
                    type="warning"
                    showIcon
                    message="探测未就绪或无法握手"
                    description={
                      probeResult.detail ||
                      '请确认你的独立微服务（如大众点评或小红书服务）已启动并监听在指定端口。'
                    }
                  />
                )}
              </div>
            )}
          </div>
        </Form>
      </Modal>

      {/* Contract Integration Guide Modal */}
      <Modal
        title="Food Agent 外部数据源与 MCP 接入指南"
        open={isGuideModalOpen}
        onCancel={() => setIsGuideModalOpen(false)}
        footer={[
          <Button key="close" type="primary" onClick={() => setIsGuideModalOpen(false)}>
            我知道了
          </Button>,
        ]}
        width={720}
      >
        <Space direction="vertical" size="middle" style={{ width: '100%', marginTop: 8 }}>
          <Alert
            type="info"
            message="数据源微服务架构解耦说明"
            description="Food Agent 主系统已实现全面解耦，无需在主系统代码中编写爬虫逆向代码。现在支持通过本管理后台在线添加任意实现了 MCP 契约的微服务，配置将持久化保存在数据库中，并即时生效。"
          />

          <div>
            <Typography.Text strong>1. 快速接入步骤</Typography.Text>
            <ul style={{ marginTop: 6, paddingLeft: 20 }}>
              <li>
                启动你的独立微服务（如已为你实现好的大众点评仓库服务，监听在本地如 <Typography.Text code>http://127.0.0.1:8103</Typography.Text>）。
              </li>
              <li>
                点击右上角的「<b>添加 MCP 数据源</b>」按钮，输入 Base URL 与渠道（如 <Typography.Text code>dianping</Typography.Text>）。
              </li>
              <li>
                点击「<b>测试连通性并探测工具</b>」，确认工具探测成功后点击保存。
              </li>
              <li>
                Agent 规划引擎在下次推荐搜索时将自动调用新接入的 MCP 工具抓取数据！
              </li>
            </ul>
          </div>

          <div>
            <Typography.Text strong>2. 契约端点说明</Typography.Text>
            <ul style={{ marginTop: 6, paddingLeft: 20 }}>
              <li>
                <Typography.Text code>GET /health</Typography.Text>：基础健康检查
              </li>
              <li>
                <Typography.Text code>GET /v1/capabilities</Typography.Text>：服务能力清单与渠道声明
              </li>
              <li>
                <Typography.Text code>POST /mcp</Typography.Text>：标准 MCP JSON-RPC 端点（支持 initialize、tools/list、tools/call）
              </li>
            </ul>
          </div>

          <Alert
            type="warning"
            showIcon
            message="安全红线拦截"
            description="网关严禁接收或返回 cookie、token 等明文敏感字段，微服务内部自行管理会话，对外仅交互不透明引用标识。"
          />
        </Space>
      </Modal>
    </Space>
  )
}
export default ServiceCatalogPage
