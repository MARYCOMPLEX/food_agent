import React, { useState, useEffect } from 'react'
import {
  Card,
  Table,
  Tag,
  Button,
  Space,
  Typography,
  Modal,
  Alert,
  Switch,
  Form,
  Input,
  InputNumber,
  Select,
  Popconfirm,
  Tooltip,
  Badge,
  Divider,
  Timeline,
} from 'antd'
import {
  SettingOutlined,
  PlusOutlined,
  ReloadOutlined,
  ApiOutlined,
  EditOutlined,
  DeleteOutlined,
  CheckCircleOutlined,
  StarOutlined,
  StarFilled,
  SafetyCertificateOutlined,
  KeyOutlined,
  ThunderboltOutlined,
  InfoCircleOutlined,
} from '@ant-design/icons'
import { useToast } from '../../context/ToastContext'
import { apiGet, apiPost, apiPut, apiDelete } from '../../api/client'

export interface LLMModelRecord {
  model_id: string
  model_name: string
  display_name: string
  provider: string
  base_url: string
  masked_api_key: string
  temperature: number
  max_tokens: number
  reasoning_effort?: string | null
  is_default: boolean
  is_user_selectable: boolean
  created_at?: string
  updated_at?: string
}

export function ModelGovernancePage() {
  const { showToast } = useToast()
  const [loading, setLoading] = useState<boolean>(false)
  const [models, setModels] = useState<LLMModelRecord[]>([])
  const [testingId, setTestingId] = useState<string | null>(null)
  const [testResults, setTestResults] = useState<Record<string, { reachable: boolean; latency_ms: number; reply_preview?: string; error?: string }>>({})

  // Add / Edit Modal
  const [isModalOpen, setIsModalOpen] = useState<boolean>(false)
  const [editingModel, setEditingModel] = useState<LLMModelRecord | null>(null)
  const [modalTesting, setModalTesting] = useState<boolean>(false)
  const [modalTestResult, setModalTestResult] = useState<{ reachable: boolean; latency_ms: number; reply_preview?: string; error?: string } | null>(null)
  const [form] = Form.useForm()

  // Real-time watch for Base URL concatenation preview
  const watchedBaseUrl = Form.useWatch('base_url', form) || ''
  const rawBaseUrl = (watchedBaseUrl || '').trim()
  const hasChatCompletionsSuffix = /\/chat\/completions\/?$/i.test(rawBaseUrl)
  const sanitizedBaseUrl = rawBaseUrl.replace(/\/chat\/completions\/?$/i, '').replace(/\/+$/, '')
  const resolvedEndpoint = sanitizedBaseUrl ? `${sanitizedBaseUrl}/chat/completions` : ''

  // Audit Logs
  const [auditLog, setAuditLog] = useState<string[]>([])

  const fetchModels = async () => {
    setLoading(true)
    try {
      const res = await apiGet<any>('/v1/platform/ops/llm-models')
      const data = res?.data || res || []
      if (Array.isArray(data)) {
        setModels(data)
      }
    } catch (err: any) {
      showToast('获取模型配置列表失败: ' + (err.message || '网络异常'), 'error')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchModels()
  }, [])

  // Test single model connectivity
  const handleTestConnection = async (record: Partial<LLMModelRecord>, isFromModal = false) => {
    if (isFromModal) {
      setModalTesting(true)
      setModalTestResult(null)
    } else if (record.model_id) {
      setTestingId(record.model_id)
    }

    try {
      const payload = {
        model_name: record.model_name,
        base_url: record.base_url,
        api_key: (record as any).api_key || undefined,
        model_id: record.model_id || undefined,
        reasoning_effort: record.reasoning_effort || undefined,
      }
      const res = await apiPost<any>('/v1/platform/ops/llm-models/test', payload)
      const data = res?.data || res
      if (isFromModal) {
        setModalTestResult(data)
      } else if (record.model_id) {
        setTestResults((prev) => ({ ...prev, [record.model_id!]: data }))
      }

      if (data.reachable) {
        showToast(`模型 ${record.model_name} 连通正常！往返耗时: ${data.latency_ms}ms`, 'success')
      } else {
        showToast(`模型 ${record.model_name} 连通失败: ${data.error || '无法建立连接'}`, 'warning')
      }
    } catch (err: any) {
      const failInfo = { reachable: false, latency_ms: 0, error: err.message || '调用异常' }
      if (isFromModal) {
        setModalTestResult(failInfo)
      } else if (record.model_id) {
        setTestResults((prev) => ({ ...prev, [record.model_id!]: failInfo }))
      }
      showToast('连通性测试请求失败: ' + err.message, 'error')
    } finally {
      if (isFromModal) {
        setModalTesting(false)
      } else {
        setTestingId(null)
      }
    }
  }

  // Set default model
  const handleSetDefault = async (modelId: string, modelName: string) => {
    try {
      await apiPost(`/v1/platform/ops/llm-models/${modelId}/set-default`, {})
      showToast(`已将 ${modelName} 设为全局默认推理大模型`, 'success')
      setAuditLog((prev) => [
        `${new Date().toLocaleString()} - 切换系统全局默认模型为: ${modelName} (${modelId})`,
        ...prev,
      ])
      await fetchModels()
    } catch (err: any) {
      showToast('设置默认模型失败: ' + err.message, 'error')
    }
  }

  // Delete model
  const handleDelete = async (modelId: string, modelName: string) => {
    try {
      await apiDelete(`/v1/platform/ops/llm-models/${modelId}`)
      showToast(`模型 ${modelName} 已成功移除`, 'info')
      setAuditLog((prev) => [
        `${new Date().toLocaleString()} - 删除模型配置: ${modelName} (${modelId})`,
        ...prev,
      ])
      await fetchModels()
    } catch (err: any) {
      showToast('删除失败: ' + err.message, 'error')
    }
  }

  // Open modal for Create / Edit
  const openEditModal = (model?: LLMModelRecord) => {
    setModalTestResult(null)
    if (model) {
      setEditingModel(model)
      form.setFieldsValue({
        model_id: model.model_id,
        provider: model.provider,
        model_name: model.model_name,
        display_name: model.display_name,
        base_url: model.base_url,
        api_key: '', // leave empty to retain
        temperature: model.temperature,
        max_tokens: model.max_tokens,
        reasoning_effort: model.reasoning_effort || undefined,
        is_default: model.is_default,
        is_user_selectable: model.is_user_selectable,
      })
    } else {
      setEditingModel(null)
      form.resetFields()
      form.setFieldsValue({
        provider: 'OpenAI',
        base_url: 'https://api.gojia.cloud/v1/',
        temperature: 0.2,
        max_tokens: 1024,
        reasoning_effort: 'medium',
        is_default: models.length === 0,
        is_user_selectable: true,
      })
    }
    setIsModalOpen(true)
  }

  // Submit Modal Form
  const handleModalSubmit = async () => {
    try {
      const values = await form.validateFields()
      const rawUrl = (values.base_url || '').trim()
      const cleanUrl = rawUrl.replace(/\/chat\/completions\/?$/i, '').replace(/\/+$/, '')
      const normalizedBaseUrl = cleanUrl ? `${cleanUrl}/` : rawUrl

      const payload: any = {
        model_name: values.model_name.trim(),
        display_name: values.display_name.trim(),
        provider: values.provider.trim(),
        base_url: normalizedBaseUrl,
        temperature: Number(values.temperature ?? 0.2),
        max_tokens: Number(values.max_tokens ?? 1024),
        reasoning_effort: values.reasoning_effort || null,
        is_default: Boolean(values.is_default),
        is_user_selectable: Boolean(values.is_user_selectable),
      }

      if (values.api_key && values.api_key.trim()) {
        payload.api_key = values.api_key.trim()
      }

      if (editingModel) {
        await apiPut(`/v1/platform/ops/llm-models/${editingModel.model_id}`, payload)
        showToast(`已成功更新大模型配置: ${payload.display_name}`, 'success')
        setAuditLog((prev) => [
          `${new Date().toLocaleString()} - 更新模型配置: ${payload.display_name} (${editingModel.model_id})`,
          ...prev,
        ])
      } else {
        if (values.model_id && values.model_id.trim()) {
          payload.model_id = values.model_id.trim()
        }
        await apiPost('/v1/platform/ops/llm-models', payload)
        showToast(`已成功接入新大模型: ${payload.display_name}`, 'success')
        setAuditLog((prev) => [
          `${new Date().toLocaleString()} - 新接入模型配置: ${payload.display_name} (${payload.model_name})`,
          ...prev,
        ])
      }

      setIsModalOpen(false)
      await fetchModels()
    } catch (err: any) {
      if (err?.errorFields) return
      showToast('保存模型配置失败: ' + err.message, 'error')
    }
  }

  const columns = [
    {
      title: '模型与显示名称',
      key: 'model_info',
      render: (_: any, record: LLMModelRecord) => (
        <Space direction="vertical" size={2}>
          <Space>
            <Typography.Text strong>{record.display_name}</Typography.Text>
            {record.is_default && (
              <Tag color="gold" icon={<StarFilled />} style={{ fontSize: 11 }}>
                默认模型
              </Tag>
            )}
          </Space>
          <Space size={6}>
            <Typography.Text code style={{ fontSize: 12 }}>
              {record.model_name}
            </Typography.Text>
            <Tag color="blue">{record.provider}</Tag>
          </Space>
        </Space>
      ),
    },
    {
      title: 'API 基础端点 (Base URL)',
      dataIndex: 'base_url',
      key: 'base_url',
      render: (url: string) => {
        const clean = (url || '').trim().replace(/\/chat\/completions\/?$/i, '').replace(/\/+$/, '')
        const full = clean ? `${clean}/chat/completions` : url
        return (
          <Tooltip title={`底层实际请求完整端点: POST ${full}`}>
            <Typography.Text code style={{ fontSize: 11, maxWidth: 220, display: 'inline-block' }} ellipsis>
              {url}
            </Typography.Text>
          </Tooltip>
        )
      },
    },
    {
      title: 'API 密钥保护',
      dataIndex: 'masked_api_key',
      key: 'masked_api_key',
      render: (key: string) => (
        <Space size={4}>
          <KeyOutlined style={{ color: '#8c8c8c' }} />
          <Typography.Text type="secondary" style={{ fontSize: 12, fontFamily: 'monospace' }}>
            {key}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: '推理超参',
      key: 'params',
      render: (_: any, record: LLMModelRecord) => (
        <Space direction="vertical" size={1} style={{ fontSize: 12 }}>
          <span>
            Temp: <strong>{record.temperature}</strong> | MaxTokens: <strong>{record.max_tokens}</strong>
          </span>
          {record.reasoning_effort && (
            <span style={{ color: '#595959' }}>
              Reasoning: <Tag color="purple">{record.reasoning_effort}</Tag>
            </span>
          )}
        </Space>
      ),
    },
    {
      title: '用户端自选',
      dataIndex: 'is_user_selectable',
      key: 'is_user_selectable',
      align: 'center' as const,
      render: (selectable: boolean) =>
        selectable ? (
          <Tag color="cyan">前台可见</Tag>
        ) : (
          <Tag color="default">仅后台治理</Tag>
        ),
    },
    {
      title: '连通健康状态',
      key: 'health',
      render: (_: any, record: LLMModelRecord) => {
        const res = testResults[record.model_id]
        if (!res) {
          return (
            <Tag color="default" style={{ cursor: 'default' }}>
              未探测
            </Tag>
          )
        }
        if (res.reachable) {
          return (
            <Tooltip title={`首字预览: ${res.reply_preview || 'OK'}`}>
              <Tag color="success" icon={<CheckCircleOutlined />}>
                连通正常 ({res.latency_ms}ms)
              </Tag>
            </Tooltip>
          )
        }
        return (
          <Tooltip title={res.error}>
            <Tag color="error">异常: {res.error?.slice(0, 18)}...</Tag>
          </Tooltip>
        )
      },
    },
    {
      title: '操作',
      key: 'actions',
      render: (_: any, record: LLMModelRecord) => (
        <Space size={6}>
          <Tooltip title="发送轻量级 Ping 探测实时往返延迟">
            <Button
              size="small"
              icon={<ApiOutlined />}
              loading={testingId === record.model_id}
              onClick={() => handleTestConnection(record)}
            >
              探测
            </Button>
          </Tooltip>

          {!record.is_default && (
            <Tooltip title="设为对话与研判默认调用的模型">
              <Button
                size="small"
                icon={<StarOutlined />}
                onClick={() => handleSetDefault(record.model_id, record.display_name)}
              >
                设为默认
              </Button>
            </Tooltip>
          )}

          <Button
            size="small"
            icon={<EditOutlined />}
            onClick={() => openEditModal(record)}
          >
            编辑
          </Button>

          <Popconfirm
            title="确认移除模型"
            description={`确定删除 ${record.display_name} 吗？如果此模型被设为默认，系统将回退到首个可用模型。`}
            onConfirm={() => handleDelete(record.model_id, record.display_name)}
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
          >
            <Button
              size="small"
              danger
              icon={<DeleteOutlined />}
              disabled={record.is_default && models.length > 1}
            />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      {/* Header Banner */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <Typography.Title level={4} style={{ margin: 0 }}>
            <SettingOutlined style={{ color: '#1677ff', marginRight: 8 }} />
            大模型推理与策略在线治理
          </Typography.Title>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            支持在线接入各大主流大模型（OpenAI, DeepSeek, GoJia, Claude, Qwen），数据库持久化，一键热重载即时生效
          </Typography.Text>
        </div>

        <Space>
          <Button icon={<ReloadOutlined />} onClick={fetchModels} loading={loading}>
            刷新配置
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => openEditModal()}>
            添加大模型
          </Button>
        </Space>
      </div>

      <Alert
        message="配置热重载与密钥安全说明"
        description="所有模型配置持久化保存在后端数据库（llm_models）。修改或切换默认模型后，后端 LLM 实例缓存将即刻自动失效并热重载；前台对话界面将实时从 /v1/chat/models 获取最新可选项。"
        type="info"
        showIcon
        icon={<SafetyCertificateOutlined />}
      />

      {/* Main Models Table */}
      <Card
        title={
          <Space>
            <span>大模型接入列表</span>
            <Badge count={models.length} overflowCount={99} style={{ backgroundColor: '#1677ff' }} />
          </Space>
        }
      >
        <Table
          rowKey="model_id"
          loading={loading}
          columns={columns}
          dataSource={models}
          pagination={false}
        />
      </Card>

      {/* Audit Log Card */}
      <Card title="配置热重载与策略变更审计日志">
        {auditLog.length === 0 ? (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            暂无模型配置变更记录
          </Typography.Text>
        ) : (
          <Timeline
            items={auditLog.map((log) => ({
              color: 'blue',
              children: (
                <Typography.Text code style={{ fontSize: 12 }}>
                  {log}
                </Typography.Text>
              ),
            }))}
          />
        )}
      </Card>

      {/* Create / Edit Modal */}
      <Modal
        title={
          <Space>
            <ThunderboltOutlined style={{ color: '#1677ff' }} />
            <span>{editingModel ? '编辑大模型配置' : '接入新大模型'}</span>
          </Space>
        }
        open={isModalOpen}
        onCancel={() => setIsModalOpen(false)}
        width={680}
        footer={[
          <Button
            key="test"
            icon={<ApiOutlined />}
            loading={modalTesting}
            onClick={async () => {
              try {
                const values = await form.validateFields(['model_name', 'base_url'])
                const rawUrl = (values.base_url || '').trim()
                const cleanUrl = rawUrl.replace(/\/chat\/completions\/?$/i, '').replace(/\/+$/, '')
                const normalizedUrl = cleanUrl ? `${cleanUrl}/` : rawUrl
                handleTestConnection(
                  {
                    model_name: values.model_name,
                    base_url: normalizedUrl,
                    model_id: editingModel?.model_id,
                    reasoning_effort: form.getFieldValue('reasoning_effort'),
                    ...((form.getFieldValue('api_key') ? { api_key: form.getFieldValue('api_key') } : {}) as any),
                  },
                  true,
                )
              } catch {
                showToast('请先填写模型名称与 API 端点以供探测', 'warning')
              }
            }}
          >
            测试连通性
          </Button>,
          <Button key="cancel" onClick={() => setIsModalOpen(false)}>
            取消
          </Button>,
          <Button key="submit" type="primary" onClick={handleModalSubmit}>
            保存配置
          </Button>,
        ]}
      >
        <Form form={form} layout="vertical">
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
            <Form.Item
              name="provider"
              label="模型服务商 (Provider)"
              rules={[{ required: true, message: '请选择或填写模型提供商' }]}
            >
              <Select
                showSearch
                options={[
                  { value: 'GoJia Cloud', label: 'GoJia Cloud' },
                  { value: 'OpenAI', label: 'OpenAI' },
                  { value: 'DeepSeek', label: 'DeepSeek (深度求索)' },
                  { value: 'Anthropic', label: 'Anthropic (Claude)' },
                  { value: 'Alibaba Cloud', label: '通义千问 (Qwen)' },
                  { value: 'Moonshot AI', label: 'Moonshot (Kimi)' },
                  { value: 'SiliconFlow', label: '硅基流动 (SiliconFlow)' },
                  { value: 'Ollama', label: '本地自建 (Ollama)' },
                ]}
              />
            </Form.Item>

            <Form.Item
              name="model_name"
              label="实际请求模型代号 (model_name)"
              extra="发送给 API 的底层实际参数，如 gpt-5.6-sol 或 deepseek-chat"
              rules={[{ required: true, message: '请输入模型标识' }]}
            >
              <Input placeholder="例如: gpt-5.6-sol" />
            </Form.Item>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
            <Form.Item
              name="display_name"
              label="前端友好显示名称 (display_name)"
              extra="在前端对话端下拉框中呈现的名字"
              rules={[{ required: true, message: '请输入显示名称' }]}
            >
              <Input placeholder="例如: GPT-5.6 Sol (默认推荐)" />
            </Form.Item>

            <Form.Item
              name="model_id"
              label="配置唯一 ID (可留空自动生成)"
            >
              <Input placeholder="model_gpt_5_6_sol" disabled={!!editingModel} />
            </Form.Item>
          </div>

          <Form.Item
            name="base_url"
            label="API 基础端点 (Base URL)"
            rules={[{ required: true, message: '请输入 Base URL' }]}
            extra="兼容 OpenAI API 的端点根路径，通常以 /v1/ 结尾（若误包含 /chat/completions 系统将自动校正）"
          >
            <Input placeholder="https://api.gojia.cloud/v1/" />
          </Form.Item>

          {/* 实时请求端点拼接效果预览 */}
          <div
            style={{
              marginTop: -10,
              marginBottom: 16,
              padding: '12px 14px',
              backgroundColor: '#f8fafc',
              border: '1px solid #e2e8f0',
              borderRadius: '8px',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
              <Space size={6}>
                <ApiOutlined style={{ color: '#0969da' }} />
                <Typography.Text strong style={{ fontSize: '13px', color: '#1e293b' }}>
                  实际请求完整端点预览 (Resolved Endpoint):
                </Typography.Text>
              </Space>
              <Tag color="processing" style={{ margin: 0, fontSize: '11px' }}>
                OpenAI Chat Completions 协议
              </Tag>
            </div>

            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                background: '#ffffff',
                border: '1px solid #cbd5e1',
                borderRadius: '6px',
                padding: '6px 12px',
              }}
            >
              <Tag color="green" style={{ fontWeight: 'bold', margin: 0 }}>
                POST
              </Tag>
              <Typography.Text
                code
                copyable={!!resolvedEndpoint}
                style={{
                  margin: 0,
                  fontSize: '12px',
                  color: resolvedEndpoint ? '#0f172a' : '#94a3b8',
                  wordBreak: 'break-all',
                  flex: 1,
                  fontFamily: 'monospace',
                }}
              >
                {resolvedEndpoint || 'https://<Base_URL>/chat/completions'}
              </Typography.Text>
            </div>

            {hasChatCompletionsSuffix && (
              <div
                style={{
                  marginTop: 8,
                  padding: '6px 10px',
                  background: '#fffbeb',
                  border: '1px solid #fef3c7',
                  borderRadius: '4px',
                  fontSize: '12px',
                  color: '#b45309',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                }}
              >
                <InfoCircleOutlined />
                <span>
                  检测到尾部包含 <code>/chat/completions</code>，系统已自动剔除冗余路径，保存时将规范化 Base URL，避免双重拼接 404。
                </span>
              </div>
            )}

            <div style={{ marginTop: 6, fontSize: '11px', color: '#64748b', lineHeight: 1.4 }}>
              说明：底层通过 LangChain <code>ChatOpenAI</code> 客户端以标准 Chat 协议通信，所有模型对话请求均向上述 <code>POST .../chat/completions</code> 端点发送。
            </div>
          </div>

          <Form.Item
            name="api_key"
            label="API 密钥 (API Key)"
            extra={
              editingModel
                ? `当前脱敏密钥: ${editingModel.masked_api_key}。若不需要更换密钥，此处留空即可。`
                : '请输入此服务商的 API 密钥'
            }
          >
            <Input.Password placeholder={editingModel ? '留空表示沿用现有密钥' : 'sk-...'} />
          </Form.Item>

          <Divider style={{ margin: '12px 0' }} />

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '16px' }}>
            <Form.Item
              name="temperature"
              label="采样温度 (Temperature)"
              extra="0.0 偏精准事实，1.0 偏发散创新"
            >
              <InputNumber min={0} max={2} step={0.1} style={{ width: '100%' }} />
            </Form.Item>

            <Form.Item
              name="max_tokens"
              label="单次最大 Token (Max Tokens)"
            >
              <InputNumber min={64} max={128000} step={256} style={{ width: '100%' }} />
            </Form.Item>

            <Form.Item
              name="reasoning_effort"
              label="推理深度 (Reasoning Effort)"
              extra="o/GPT-5 系列推理模型使用"
            >
              <Select
                allowClear
                options={[
                  { value: 'low', label: 'low (快速)' },
                  { value: 'medium', label: 'medium (均衡)' },
                  { value: 'high', label: 'high (深度)' },
                ]}
              />
            </Form.Item>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', background: '#fafafa', padding: '12px 16px', borderRadius: '6px' }}>
            <Form.Item
              name="is_default"
              valuePropName="checked"
              label="设为系统全局默认模型"
              style={{ marginBottom: 0 }}
            >
              <Switch />
            </Form.Item>

            <Form.Item
              name="is_user_selectable"
              valuePropName="checked"
              label="允许在对话端下拉框选择"
              style={{ marginBottom: 0 }}
            >
              <Switch />
            </Form.Item>
          </div>

          {modalTestResult && (
            <div style={{ marginTop: 16 }}>
              {modalTestResult.reachable ? (
                <Alert
                  type="success"
                  showIcon
                  message={`连通成功！往返耗时: ${modalTestResult.latency_ms}ms`}
                  description={`测试回复预览: ${modalTestResult.reply_preview || 'OK'}`}
                />
              ) : (
                <Alert
                  type="error"
                  showIcon
                  message="连通失败"
                  description={modalTestResult.error || '无法与该大模型端点建立连接'}
                />
              )}
            </div>
          )}
        </Form>
      </Modal>
    </Space>
  )
}
