import React, { useState } from 'react'
import { Card, Form, Select, Input, InputNumber, Switch, Button, Timeline, Tag, Alert, Space, Typography, Row, Col } from 'antd'
import {
  SettingOutlined,
  SaveOutlined,
  SafetyCertificateOutlined,
  KeyOutlined,
  CheckCircleOutlined,
} from '@ant-design/icons'
import { useToast } from '../../context/ToastContext'

interface ModelProviderConfig {
  id: string
  providerName: string
  modelName: string
  role: 'intent_parser' | 'evidence_critic' | 'poi_enricher' | 'recommender'
  reasoningEffort: 'low' | 'medium' | 'high'
  maxTokens: number
  temperature: number
  isUserSelectable: boolean
  maskedApiKey: string
  status: 'active' | 'testing' | 'disabled'
}

export function ModelGovernancePage() {
  const { showToast } = useToast()

  const [configs, setConfigs] = useState<ModelProviderConfig[]>([
    {
      id: 'cfg_intent',
      providerName: 'DeepSeek / Anthropic',
      modelName: 'claude-3-5-sonnet-20241022',
      role: 'intent_parser',
      reasoningEffort: 'medium',
      maxTokens: 2048,
      temperature: 0.2,
      isUserSelectable: false,
      maskedApiKey: 'sk-ant-api03-••••••••••••••••••••••••9A7B',
      status: 'active',
    },
    {
      id: 'cfg_critic',
      providerName: 'OpenAI',
      modelName: 'o3-mini',
      role: 'evidence_critic',
      reasoningEffort: 'high',
      maxTokens: 4096,
      temperature: 1.0,
      isUserSelectable: false,
      maskedApiKey: 'sk-proj-••••••••••••••••••••••••F14C',
      status: 'active',
    },
    {
      id: 'cfg_recommender',
      providerName: 'Google Gemini',
      modelName: 'gemini-1.5-pro',
      role: 'recommender',
      reasoningEffort: 'high',
      maxTokens: 8192,
      temperature: 0.4,
      isUserSelectable: true,
      maskedApiKey: 'AIzaSy••••••••••••••••••••••••Z4X8',
      status: 'active',
    },
  ])

  const [auditLog, setAuditLog] = useState<string[]>([
    '2026-09-11 00:30:00 - 管理员发布新版本策略配置 v1.4.0（调高 Evidence Critic 的 reasoning effort 至 high）',
    '2026-09-10 16:15:00 - 接入 Gemini 1.5 Pro 模型并在灰度集群通过并发负载测试',
  ])

  const handleSave = () => {
    showToast('模型治理策略已成功部署生效 (配置版本: v1.4.1)', 'success')
    setAuditLog([
      `${new Date().toISOString().replace('T', ' ').slice(0, 19)} - 管理员更新并发布模型策略配置 (v1.4.1)`,
      ...auditLog,
    ])
  }

  const roleLabelMap = {
    intent_parser: '意图拆解与地点约束解析',
    evidence_critic: '真实评论证据质检与争议提炼',
    poi_enricher: '大众点评 POI 实体消歧与档案对齐',
    recommender: '最终综合推荐与论据合成',
  }

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <Typography.Title level={4} style={{ margin: 0 }}>
            <SettingOutlined style={{ color: '#1677ff', marginRight: 8 }} />
            模型与调查策略治理
          </Typography.Title>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            配置模型目录、角色推理强度 (Reasoning Effort)、参数放行规则与 API Key 掩码安全保护
          </Typography.Text>
        </div>

        <Button
          type="primary"
          icon={<SaveOutlined />}
          onClick={handleSave}
        >
          保存并发布策略
        </Button>
      </div>

      <Alert
        message="模型 Key 加密与参数防漂移规范"
        description="API Key 保存后单向掩码化存储，永远不可再次逆向查阅明文。模型 temperature 与 reasoning effort 受后端 Hard Limit 约束，客户端不得绕过安全策略。"
        type="info"
        showIcon
        icon={<SafetyCertificateOutlined />}
      />

      {/* Model Configurations Cards */}
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        {configs.map((cfg) => (
          <Card
            key={cfg.id}
            title={
              <Space>
                <Typography.Text strong>{cfg.providerName}</Typography.Text>
                <Tag color="blue">{cfg.modelName}</Tag>
                <Tag color="success">ACTIVE</Tag>
              </Space>
            }
            extra={
              <Space>
                <span style={{ fontSize: 12, color: '#595959' }}>用户端可选</span>
                <Switch
                  checked={cfg.isUserSelectable}
                  onChange={(checked) => {
                    setConfigs(
                      configs.map((c) => (c.id === cfg.id ? { ...c, isUserSelectable: checked } : c)),
                    )
                  }}
                />
              </Space>
            }
          >
            <div style={{ marginBottom: 16 }}>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                承担角色能力：<strong>{roleLabelMap[cfg.role]}</strong>
              </Typography.Text>
            </div>

            <Row gutter={[16, 16]}>
              <Col span={24} sm={8}>
                <Form.Item label="Reasoning Effort (推理深度)" style={{ marginBottom: 0 }}>
                  <Select
                    value={cfg.reasoningEffort}
                    onChange={(val) => {
                      setConfigs(
                        configs.map((c) => (c.id === cfg.id ? { ...c, reasoningEffort: val } : c)),
                      )
                    }}
                    options={[
                      { value: 'low', label: 'low (快速筛选)' },
                      { value: 'medium', label: 'medium (常规均衡)' },
                      { value: 'high', label: 'high (深度交叉核验)' },
                    ]}
                  />
                </Form.Item>
              </Col>

              <Col span={24} sm={8}>
                <Form.Item label="Max Tokens 限制" style={{ marginBottom: 0 }}>
                  <InputNumber
                    value={cfg.maxTokens}
                    onChange={(val) => {
                      if (val) {
                        setConfigs(
                          configs.map((c) => (c.id === cfg.id ? { ...c, maxTokens: val } : c)),
                        )
                      }
                    }}
                    style={{ width: '100%' }}
                  />
                </Form.Item>
              </Col>

              <Col span={24} sm={8}>
                <Form.Item
                  label={
                    <Space>
                      <KeyOutlined style={{ color: '#1677ff' }} />
                      <span>凭据状态 (只读掩码)</span>
                    </Space>
                  }
                  style={{ marginBottom: 0 }}
                >
                  <Input disabled value={cfg.maskedApiKey} />
                </Form.Item>
              </Col>
            </Row>
          </Card>
        ))}
      </Space>

      {/* Audit Log Card */}
      <Card title="策略版本审计与回滚日志">
        <Timeline
          items={auditLog.map((log) => ({
            color: 'blue',
            children: <Typography.Text code style={{ fontSize: 12 }}>{log}</Typography.Text>,
          }))}
        />
      </Card>
    </Space>
  )
}
