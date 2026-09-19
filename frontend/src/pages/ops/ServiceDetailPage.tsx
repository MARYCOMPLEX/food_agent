import React, { useState, useEffect, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Card,
  Table,
  Tag,
  Switch,
  Button,
  Space,
  Typography,
  Input,
  Radio,
  Modal,
  Alert,
  Spin,
  Descriptions,
  Empty,
  Tabs,
  Badge,
  Tooltip,
} from 'antd'
import {
  ArrowLeftOutlined,
  PlayCircleOutlined,
  ApiOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  ReloadOutlined,
  SearchOutlined,
  ThunderboltOutlined,
  CodeOutlined,
  PlusOutlined,
  CheckOutlined,
  StopOutlined,
} from '@ant-design/icons'
import { useToast } from '../../context/ToastContext'

interface ToolItem {
  tool_name: string
  standard_capability: string
  category?: string
  description: string
  side_effect: string
  is_read_only: boolean
  is_allowed: boolean
  call_success_rate: string
  schema_fields: string[]
  sample_arguments: Record<string, any>
  input_schema: Record<string, any>
  output_schema?: Record<string, any> | null
  annotations?: Record<string, any>
}

interface ServiceDetail {
  service_id: string
  name: string
  base_url: string
  mcp_url?: string
  protocol: string
  channels: string[]
  capabilities: string[]
  timeout_seconds: number
  enabled: boolean
  live_state: 'ready' | 'degraded' | 'disabled' | 'dependency-unavailable'
  live_detail?: string | null
  latency_ms: number
  discovered_tools_count: number
  allowed_tools_count: number
}

interface ServiceSummary {
  service_id: string
  name: string
  protocol: string
  channels: string[]
  enabled: boolean
  tools_count: number
}

export function ServiceDetailPage() {
  const { serviceId } = useParams<{ serviceId: string }>()
  const navigate = useNavigate()
  const { showToast } = useToast()

  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [service, setService] = useState<ServiceDetail | null>(null)
  const [allServices, setAllServices] = useState<ServiceSummary[]>([])
  const [tools, setTools] = useState<ToolItem[]>([])
  const [togglingTools, setTogglingTools] = useState<Record<string, boolean>>({})
  const [batchToggling, setBatchToggling] = useState(false)

  // Filters
  const [searchText, setSearchText] = useState('')
  const [permissionFilter, setPermissionFilter] = useState<'all' | 'allowed' | 'blocked'>('all')

  // Modals
  const [schemaModalTool, setSchemaModalTool] = useState<ToolItem | null>(null)
  const [testModalTool, setTestModalTool] = useState<ToolItem | null>(null)
  const [testArgsInput, setTestArgsInput] = useState('{}')
  const [testLoading, setTestLoading] = useState(false)
  const [testResult, setTestResult] = useState<any | null>(null)

  const fetchServiceDetail = async (silent = false) => {
    if (!serviceId) return
    if (!silent) setLoading(true)
    try {
      const res = await fetch(`/v1/platform/ops/mcp-services/${serviceId}`)
      if (res.ok) {
        const json = await res.json()
        if (json?.success && json?.data) {
          setService(json.data.service)
          setTools(json.data.tools || [])
          setAllServices(json.data.all_services || [])
          return
        }
      }
      showToast(`获取服务详情失败: 未找到服务 ${serviceId}`, 'error')
    } catch (err: any) {
      showToast(`网络请求异常: ${err.message}`, 'error')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  useEffect(() => {
    fetchServiceDetail()
  }, [serviceId])

  const handleRefresh = async () => {
    if (!serviceId) return
    setRefreshing(true)
    try {
      const res = await fetch(`/v1/platform/ops/mcp-services/${serviceId}/refresh`, {
        method: 'POST',
      })
      if (res.ok) {
        const json = await res.json()
        if (json?.success && json?.data) {
          setService(json.data.service)
          setTools(json.data.tools || [])
          showToast(`成功刷新 ${json.data.tools?.length || 0} 个 MCP 工具`, 'success')
          return
        }
      }
      showToast('刷新服务探测失败', 'error')
    } catch (err: any) {
      showToast(`刷新失败: ${err.message}`, 'error')
    } finally {
      setRefreshing(false)
    }
  }

  const toggleToolAllowed = async (toolName: string, currentAllowed: boolean) => {
    if (!serviceId) return
    const nextAllowed = !currentAllowed
    setTogglingTools((prev) => ({ ...prev, [toolName]: true }))
    try {
      const res = await fetch(
        `/v1/platform/ops/mcp-services/${serviceId}/tools/${encodeURIComponent(toolName)}/toggle`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ allowed: nextAllowed }),
        }
      )
      if (res.ok) {
        const json = await res.json()
        if (json?.success) {
          setTools((prev) =>
            prev.map((t) => (t.tool_name === toolName ? { ...t, is_allowed: nextAllowed } : t))
          )
          showToast(`已${nextAllowed ? '放行' : '拦截'}工具: ${toolName}`, 'info')
          return
        }
      }
      showToast(`更新工具权限失败`, 'error')
    } catch (err: any) {
      showToast(`切换失败: ${err.message}`, 'error')
    } finally {
      setTogglingTools((prev) => ({ ...prev, [toolName]: false }))
    }
  }

  // Service-level batch allow/block
  const handleBatchToggleService = async (allowed: boolean) => {
    if (!serviceId) return
    setBatchToggling(true)
    try {
      const res = await fetch(`/v1/platform/ops/mcp-services/${serviceId}/tools/batch-toggle`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ allowed }),
      })
      if (res.ok) {
        setTools((prev) => prev.map((t) => ({ ...t, is_allowed: allowed })))
        showToast(
          `已${allowed ? '一键放行' : '一键拦截'}服务「${service?.name || serviceId}」全部工具`,
          'success'
        )
        return
      }
      showToast('服务级批量更新权限失败', 'error')
    } catch (err: any) {
      showToast(`操作失败: ${err.message}`, 'error')
    } finally {
      setBatchToggling(false)
    }
  }

  const openTestModal = (tool: ToolItem) => {
    setTestModalTool(tool)
    const initialArgs =
      tool.sample_arguments && Object.keys(tool.sample_arguments).length > 0
        ? tool.sample_arguments
        : {}
    setTestArgsInput(JSON.stringify(initialArgs, null, 2))
    setTestResult(null)
  }

  const handleExecuteTest = async () => {
    if (!serviceId || !testModalTool) return
    let parsedArgs = {}
    try {
      parsedArgs = JSON.parse(testArgsInput)
    } catch {
      showToast('调用参数不是合法的 JSON 格式，请检查语法', 'error')
      return
    }

    setTestLoading(true)
    setTestResult(null)
    try {
      const res = await fetch(`/v1/platform/ops/mcp-services/${serviceId}/tools/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tool_name: testModalTool.tool_name,
          arguments: parsedArgs,
        }),
      })
      if (res.ok) {
        const json = await res.json()
        if (json?.success && json?.data) {
          setTestResult(json.data)
          if (json.data.is_error) {
            showToast(`工具返回错误 (耗时 ${json.data.latency_ms}ms)`, 'warning')
          } else {
            showToast(`测试调用成功 (耗时 ${json.data.latency_ms}ms)`, 'success')
          }
          return
        }
      }
      showToast('沙箱调用请求失败', 'error')
    } catch (err: any) {
      showToast(`调用执行异常: ${err.message}`, 'error')
    } finally {
      setTestLoading(false)
    }
  }

  // Filtered tools by search and permission
  const filteredTools = useMemo(() => {
    return tools.filter((t) => {
      if (permissionFilter === 'allowed' && !t.is_allowed) return false
      if (permissionFilter === 'blocked' && t.is_allowed) return false
      if (!searchText) return true
      const query = searchText.toLowerCase()
      return (
        t.tool_name.toLowerCase().includes(query) ||
        (t.description && t.description.toLowerCase().includes(query)) ||
        (t.standard_capability && t.standard_capability.toLowerCase().includes(query))
      )
    })
  }, [tools, permissionFilter, searchText])

  const allowedCount = useMemo(() => tools.filter((t) => t.is_allowed).length, [tools])

  const columns = [
    {
      title: '工具名称 / 能力标识',
      key: 'tool_name',
      width: 280,
      render: (_: any, record: ToolItem) => (
        <Space direction="vertical" size={2}>
          <Typography.Text code strong style={{ fontSize: 13, color: '#0958d9' }}>
            {record.tool_name}
          </Typography.Text>
          {record.annotations?.title && (
            <Tag color="geekblue" style={{ margin: 0, fontSize: 11 }}>
              {record.annotations.title}
            </Tag>
          )}
        </Space>
      ),
    },
    {
      title: '功能描述',
      dataIndex: 'description',
      key: 'description',
      render: (val: string) => (
        <span style={{ fontSize: 13, color: val ? '#262626' : '#8c8c8c' }}>
          {val || '服务未提供具体描述'}
        </span>
      ),
    },
    {
      title: '读写安全',
      dataIndex: 'side_effect',
      key: 'side_effect',
      width: 120,
      render: (sideEffect: string, record: ToolItem) => {
        if (record.is_read_only || sideEffect === 'read_only') {
          return <Tag color="blue">READ ONLY</Tag>
        }
        if (sideEffect === 'account_login') {
          return <Tag color="purple">LOGIN</Tag>
        }
        return <Tag color="orange">{sideEffect.toUpperCase()}</Tag>
      },
    },
    {
      title: '调用入参 Schema',
      key: 'schema_fields',
      width: 220,
      render: (_: any, record: ToolItem) => (
        <Space direction="vertical" size={4} style={{ width: '100%' }}>
          {record.schema_fields && record.schema_fields.length > 0 ? (
            <Space wrap size={[4, 4]}>
              {record.schema_fields.slice(0, 3).map((f, i) => (
                <Typography.Text code key={i} style={{ fontSize: 11 }}>
                  {f}
                </Typography.Text>
              ))}
              {record.schema_fields.length > 3 && (
                <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                  +{record.schema_fields.length - 3} 项
                </Typography.Text>
              )}
            </Space>
          ) : (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              无必填参数
            </Typography.Text>
          )}
          <Button
            type="link"
            size="small"
            style={{ padding: 0, height: 'auto', fontSize: 12 }}
            icon={<CodeOutlined />}
            onClick={() => setSchemaModalTool(record)}
          >
            完整 Schema
          </Button>
        </Space>
      ),
    },
    {
      title: '编排放行',
      key: 'is_allowed',
      width: 100,
      render: (_: any, record: ToolItem) => (
        <Switch
          checked={record.is_allowed}
          loading={Boolean(togglingTools[record.tool_name])}
          checkedChildren="放行"
          unCheckedChildren="拦截"
          onChange={() => toggleToolAllowed(record.tool_name, record.is_allowed)}
        />
      ),
    },
    {
      title: '调试',
      key: 'action',
      width: 100,
      render: (_: any, record: ToolItem) => (
        <Button
          size="small"
          type="primary"
          ghost
          icon={<PlayCircleOutlined />}
          onClick={() => openTestModal(record)}
        >
          测试
        </Button>
      ),
    },
  ]

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: '80px 0' }}>
        <Spin size="large" tip="正在从微服务实时加载工具清单..." />
      </div>
    )
  }

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      {/* 1. Top MCP Service Isolation Switcher Bar */}
      <div
        style={{
          background: '#fff',
          padding: '12px 16px',
          borderRadius: 8,
          border: '1px solid #f0f0f0',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: 12,
        }}
      >
        <Space size={12} align="center">
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/ops/services')}>
            返回服务目录
          </Button>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <ApiOutlined style={{ fontSize: 18, color: '#1677ff' }} />
            <Typography.Text strong style={{ fontSize: 14 }}>
              切换 MCP 服务:
            </Typography.Text>
          </div>
          <Tabs
            type="card"
            size="small"
            activeKey={serviceId}
            onChange={(key) => navigate(`/ops/services/${key}`)}
            style={{ marginBottom: -16 }}
            items={allServices.map((s) => ({
              key: s.service_id,
              label: (
                <Space size={6}>
                  <span>{s.name || s.service_id}</span>
                  <Badge
                    count={s.tools_count}
                    overflowCount={99}
                    style={{
                      backgroundColor: s.service_id === serviceId ? '#1677ff' : '#bfbfbf',
                      fontSize: 10,
                    }}
                  />
                </Space>
              ),
            }))}
          />
        </Space>

        <Space size={8}>
          <Button
            size="small"
            icon={<PlusOutlined />}
            onClick={() => navigate('/ops/services')}
          >
            接入新 MCP 服务
          </Button>
          <Button
            size="small"
            icon={<ReloadOutlined spin={refreshing} />}
            loading={refreshing}
            onClick={handleRefresh}
          >
            刷新工具
          </Button>
        </Space>
      </div>

      {/* 2. Service Summary & Service-Level Controls */}
      <Card
        styles={{ body: { padding: '16px 20px' } }}
        title={
          <Space align="center" size={10}>
            <span style={{ fontSize: 16, fontWeight: 600, color: '#1677ff' }}>
              {service?.name || serviceId}
            </span>
            <Tag color="purple">{service?.protocol?.toUpperCase() || 'MCP'}</Tag>
            {service?.live_state === 'ready' ? (
              <Tag color="success" icon={<CheckCircleOutlined />}>
                运行就绪 (Ready)
              </Tag>
            ) : (
              <Tag color="warning" icon={<CloseCircleOutlined />}>
                {service?.live_state || '异常'}
              </Tag>
            )}
          </Space>
        }
        extra={
          <Space size={10}>
            <Tooltip title="一键放行当前服务的全部工具">
              <Button
                size="small"
                icon={<CheckOutlined />}
                disabled={allowedCount === tools.length}
                loading={batchToggling}
                onClick={() => handleBatchToggleService(true)}
              >
                放行全部工具
              </Button>
            </Tooltip>

            <Tooltip title="一键拦截当前服务的全部工具">
              <Button
                size="small"
                danger
                icon={<StopOutlined />}
                disabled={allowedCount === 0}
                loading={batchToggling}
                onClick={() => handleBatchToggleService(false)}
              >
                拦截全部工具
              </Button>
            </Tooltip>
          </Space>
        }
      >
        <Descriptions size="small" column={{ xxl: 4, xl: 4, lg: 2, md: 2, sm: 1, xs: 1 }}>
          <Descriptions.Item label="服务唯一标识">
            <Typography.Text code>{service?.service_id}</Typography.Text>
          </Descriptions.Item>
          <Descriptions.Item label="网络探测延迟">
            <span style={{ fontWeight: 600, color: '#389e0d' }}>{service?.latency_ms || 0} ms</span>
          </Descriptions.Item>
          <Descriptions.Item label="工具放行配额">
            <span style={{ fontWeight: 600 }}>
              {allowedCount} 放行 / 共 {tools.length} 个
            </span>
          </Descriptions.Item>
          <Descriptions.Item label="平台渠道">
            <Space size={4}>
              {(service?.channels || []).map((c) => (
                <Tag key={c} color="purple">
                  {c}
                </Tag>
              ))}
            </Space>
          </Descriptions.Item>
          <Descriptions.Item label="服务端点地址" span={4}>
            <Typography.Text code copyable>
              {service?.mcp_url || service?.base_url || '未配置'}
            </Typography.Text>
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {/* 3. Dedicated Clean Tools Table */}
      <Card
        styles={{ body: { padding: '12px 16px' } }}
        title={
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontWeight: 600, fontSize: 14 }}>
              🛠️「{service?.name || serviceId}」工具清单
            </span>
            <Tag color="blue">{tools.length} 个独立工具</Tag>
          </div>
        }
        extra={
          <Space size={10} wrap>
            <Radio.Group
              size="small"
              value={permissionFilter}
              onChange={(e) => setPermissionFilter(e.target.value)}
            >
              <Radio.Button value="all">全部 ({tools.length})</Radio.Button>
              <Radio.Button value="allowed">仅放行 ({allowedCount})</Radio.Button>
              <Radio.Button value="blocked">已拦截 ({tools.length - allowedCount})</Radio.Button>
            </Radio.Group>

            <Input
              placeholder="搜索工具名或功能描述..."
              prefix={<SearchOutlined style={{ color: '#bfbfbf' }} />}
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              allowClear
              size="small"
              style={{ width: 220 }}
            />
          </Space>
        }
      >
        <Table
          dataSource={filteredTools}
          columns={columns}
          rowKey="tool_name"
          pagination={tools.length > 15 ? { pageSize: 15, showTotal: (total) => `共 ${total} 个工具` } : false}
          size="middle"
          scroll={{ x: 920 }}
          locale={{ emptyText: <Empty description="当前服务未发现匹配的 MCP 工具" /> }}
        />
      </Card>

      {/* JSON Schema Inspection Modal */}
      <Modal
        title={
          <span>
            <CodeOutlined style={{ color: '#1677ff', marginRight: 8 }} />
            工具 Schema 定义: <Typography.Text code>{schemaModalTool?.tool_name}</Typography.Text>
          </span>
        }
        open={Boolean(schemaModalTool)}
        onCancel={() => setSchemaModalTool(null)}
        footer={[
          <Button key="close" type="primary" onClick={() => setSchemaModalTool(null)}>
            关闭
          </Button>,
        ]}
        width={680}
      >
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <div>
            <Typography.Text strong>入参 Schema (Input Schema):</Typography.Text>
            <pre
              style={{
                marginTop: 6,
                padding: 12,
                backgroundColor: '#f5f5f5',
                borderRadius: 6,
                maxHeight: 260,
                overflow: 'auto',
                fontSize: 12,
              }}
            >
              {JSON.stringify(schemaModalTool?.input_schema || {}, null, 2)}
            </pre>
          </div>

          {schemaModalTool?.output_schema && (
            <div>
              <Typography.Text strong>出参 Schema (Output Schema):</Typography.Text>
              <pre
                style={{
                  marginTop: 6,
                  padding: 12,
                  backgroundColor: '#f5f5f5',
                  borderRadius: 6,
                  maxHeight: 200,
                  overflow: 'auto',
                  fontSize: 12,
                }}
              >
                {JSON.stringify(schemaModalTool.output_schema, null, 2)}
              </pre>
            </div>
          )}
        </Space>
      </Modal>

      {/* Sandbox Test Modal */}
      <Modal
        title={
          <span>
            <ThunderboltOutlined style={{ color: '#fa8c16', marginRight: 8 }} />
            沙箱测试调用: <Typography.Text code>{testModalTool?.tool_name}</Typography.Text>
          </span>
        }
        open={Boolean(testModalTool)}
        onCancel={() => setTestModalTool(null)}
        width={720}
        footer={[
          <Button key="cancel" onClick={() => setTestModalTool(null)}>
            关闭
          </Button>,
          <Button
            key="reset"
            onClick={() => {
              if (testModalTool) {
                setTestArgsInput(JSON.stringify(testModalTool.sample_arguments || {}, null, 2))
              }
            }}
          >
            重置默认入参
          </Button>,
          <Button
            key="submit"
            type="primary"
            icon={<PlayCircleOutlined />}
            loading={testLoading}
            onClick={handleExecuteTest}
          >
            执行沙箱调用
          </Button>,
        ]}
      >
        <Space direction="vertical" size="middle" style={{ width: '100%', marginTop: 8 }}>
          <Alert
            type="info"
            showIcon
            message={testModalTool?.description || '外部 MCP 工具调用'}
            description={
              <div>
                所属服务: <Tag color="purple">{service?.name || serviceId}</Tag> | 
                标准能力: <Typography.Text code>{testModalTool?.standard_capability}</Typography.Text> | 
                安全等级: <Tag color={testModalTool?.is_read_only ? 'blue' : 'orange'} style={{ marginLeft: 4 }}>
                  {testModalTool?.side_effect?.toUpperCase()}
                </Tag>
              </div>
            }
          />

          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
              <Typography.Text strong>调用入参 (JSON 格式):</Typography.Text>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                编辑 JSON 参数以发起测试
              </Typography.Text>
            </div>
            <Input.TextArea
              rows={6}
              value={testArgsInput}
              onChange={(e) => setTestArgsInput(e.target.value)}
              style={{ fontFamily: 'monospace', fontSize: 13 }}
            />
          </div>

          {testResult && (
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                <Space>
                  <Typography.Text strong>服务实际响应结果:</Typography.Text>
                  {testResult.is_error ? (
                    <Tag color="error">执行报错</Tag>
                  ) : (
                    <Tag color="success">调用成功</Tag>
                  )}
                </Space>
                <Tag color="cyan">耗时: {testResult.latency_ms} ms</Tag>
              </div>
              <pre
                style={{
                  padding: 12,
                  backgroundColor: '#1e1e1e',
                  color: '#4ec9b0',
                  borderRadius: 6,
                  maxHeight: 280,
                  overflow: 'auto',
                  fontSize: 12,
                  margin: 0,
                }}
              >
                {JSON.stringify(testResult.content, null, 2)}
              </pre>
            </div>
          )}
        </Space>
      </Modal>
    </Space>
  )
}

export default ServiceDetailPage

