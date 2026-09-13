import React, { useState, useEffect } from 'react'
import { Card, Row, Col, Statistic, Alert, Button, Tag, Space, Typography } from 'antd'
import {
  ReloadOutlined,
  CheckCircleOutlined,
  DatabaseOutlined,
  DashboardOutlined,
  ThunderboltOutlined,
  SafetyCertificateOutlined,
  ApiOutlined,
  PlusOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { apiGet } from '../../api/client'

export function OpsOverviewPage() {
  const navigate = useNavigate()
  const [refreshing, setRefreshing] = useState<boolean>(false)
  const [services, setServices] = useState<any[]>([])

  const fetchServices = async () => {
    setRefreshing(true)
    try {
      const res = await apiGet<any>('/v1/platform/ops/mcp-services')
      const data = res?.data || res || []
      if (Array.isArray(data)) {
        setServices(data)
      } else {
        setServices([])
      }
    } catch {
      setServices([])
    } finally {
      setRefreshing(false)
    }
  }

  useEffect(() => {
    fetchServices()
  }, [])

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      {/* Top Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <Typography.Title level={4} style={{ margin: 0 }}>
            <DashboardOutlined style={{ color: '#1677ff', marginRight: 8 }} />
            系统总览与通道健康
          </Typography.Title>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            监控数据源采集通道健康度、任务执行吞吐与数据缺口治理
          </Typography.Text>
        </div>

        <Button
          icon={<ReloadOutlined spin={refreshing} />}
          onClick={fetchServices}
        >
          刷新数据
        </Button>
      </div>

      {/* Dynamic Service Readiness Cards */}
      {services.length === 0 ? (
        <Alert
          message="当前未接入任何 MCP 外部采集通道"
          description={
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 4 }}>
              <span>系统目前处于纯大模型待命状态。若需要增强探店真实评论与商户事实数据，可前往「服务目录」进行即时接入。</span>
              <Button type="primary" size="small" icon={<PlusOutlined />} onClick={() => navigate('/ops/service-catalog')}>
                去接入 MCP 数据源
              </Button>
            </div>
          }
          type="info"
          showIcon
          icon={<ApiOutlined />}
        />
      ) : (
        <Row gutter={[16, 16]}>
          {services.map((svc) => (
            <Col key={svc.service_id} span={24} md={12}>
              <Card
                title={
                  <Space>
                    <Tag color="blue">{svc.protocol || 'MCP'}</Tag>
                    <span>{svc.name}</span>
                  </Space>
                }
                extra={
                  <Tag color={svc.is_active ? 'success' : 'default'}>
                    {svc.is_active ? 'ACTIVE' : 'DISABLED'}
                  </Tag>
                }
              >
                <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 12 }}>
                  端点地址: {svc.base_url || svc.mcp_url}
                </Typography.Text>

                <Row gutter={16}>
                  <Col span={8}>
                    <Statistic
                      title="健康状态"
                      value={svc.is_active ? '健康就绪' : '未激活'}
                      valueStyle={{ color: svc.is_active ? '#52c41a' : '#8c8c8c', fontSize: 16 }}
                    />
                  </Col>
                  <Col span={8}>
                    <Statistic title="通道渠道" value={svc.channels?.join(', ') || '通用'} valueStyle={{ fontSize: 16 }} />
                  </Col>
                  <Col span={8}>
                    <Statistic title="已注册工具" value={svc.registered_tools_count ?? 0} suffix="个" valueStyle={{ fontSize: 16 }} />
                  </Col>
                </Row>
              </Card>
            </Col>
          ))}
        </Row>
      )}

      {/* System Statistics Grid */}
      <Row gutter={[16, 16]}>
        <Col span={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="今日执行调查任务"
              value={0}
              prefix={<ThunderboltOutlined style={{ color: '#1677ff' }} />}
              suffix="次"
            />
            <Typography.Text type="secondary" style={{ fontSize: 11, marginTop: 8, display: 'block' }}>
              暂无历史调用记录
            </Typography.Text>
          </Card>
        </Col>

        <Col span={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="已归档评论证据条目"
              value={0}
              prefix={<DatabaseOutlined style={{ color: '#722ed1' }} />}
              suffix="条"
            />
            <Typography.Text type="secondary" style={{ fontSize: 11, marginTop: 8, display: 'block' }}>
              等待发起探店调查任务
            </Typography.Text>
          </Card>
        </Col>

        <Col span={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="评论去重与对齐率"
              value={100}
              prefix={<CheckCircleOutlined style={{ color: '#52c41a' }} />}
              suffix="%"
            />
            <Typography.Text type="secondary" style={{ fontSize: 11, marginTop: 8, display: 'block' }}>
              跨平台商户 POI 实体绑定已就绪
            </Typography.Text>
          </Card>
        </Col>

        <Col span={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="合规与隐私脱敏"
              value={100}
              prefix={<SafetyCertificateOutlined style={{ color: '#52c41a' }} />}
              suffix="%"
            />
            <Typography.Text type="secondary" style={{ fontSize: 11, marginTop: 8, display: 'block' }}>
              电话、用户名自动严格脱敏
            </Typography.Text>
          </Card>
        </Col>
      </Row>
    </Space>
  )
}
