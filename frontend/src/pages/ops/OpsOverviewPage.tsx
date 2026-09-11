import React, { useState } from 'react'
import { Card, Row, Col, Statistic, Alert, Button, Tag, Space, Typography, Progress } from 'antd'
import {
  ReloadOutlined,
  CheckCircleOutlined,
  WarningOutlined,
  DatabaseOutlined,
  DashboardOutlined,
  ThunderboltOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons'

export function OpsOverviewPage() {
  const [refreshing, setRefreshing] = useState<boolean>(false)

  const handleRefresh = () => {
    setRefreshing(true)
    setTimeout(() => setRefreshing(false), 800)
  }

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
          onClick={handleRefresh}
        >
          刷新数据
        </Button>
      </div>

      {/* 1. High Impact Alert Banner */}
      <Alert
        message="关注事项：大众点评安全滑块拦截频次增加"
        description="最近 1 小时内有 2 起店铺档案抓取触发滑块验证，系统已自动降级为“部分就绪”状态并保留小红书评论证据，未对用户交互造成白屏阻塞。"
        type="warning"
        showIcon
        icon={<WarningOutlined />}
      />

      {/* 2. Platform Service Readiness Cards */}
      <Row gutter={[16, 16]}>
        {/* Xiaohongshu Channel */}
        <Col span={24} md={12}>
          <Card
            title={
              <Space>
                <Tag color="magenta">XHS</Tag>
                <span>小红书公开评论采集服务 (xhs_pc)</span>
              </Space>
            }
            extra={<Tag color="success">OPERATIONAL</Tag>}
          >
            <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 12 }}>
              通道协议: MCP SSE / HTTP Client
            </Typography.Text>

            <Row gutter={16}>
              <Col span={8}>
                <Statistic title="连通成功率" value={99.4} suffix="%" valueStyle={{ color: '#52c41a' }} />
              </Col>
              <Col span={8}>
                <Statistic title="P95 延迟" value={380} suffix="ms" />
              </Col>
              <Col span={8}>
                <Statistic title="可用会话号" value="2 / 2" />
              </Col>
            </Row>
          </Card>
        </Col>

        {/* Dazhong Dianping Channel */}
        <Col span={24} md={12}>
          <Card
            title={
              <Space>
                <Tag color="orange">DP</Tag>
                <span>大众点评商户事实服务 (dianping)</span>
              </Space>
            }
            extra={<Tag color="warning">DEGRADED</Tag>}
          >
            <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 12 }}>
              通道协议: MCP Tool API
            </Typography.Text>

            <Row gutter={16}>
              <Col span={8}>
                <Statistic title="连通成功率" value={92.1} suffix="%" valueStyle={{ color: '#faad14' }} />
              </Col>
              <Col span={8}>
                <Statistic title="P95 延迟" value={640} suffix="ms" />
              </Col>
              <Col span={8}>
                <Statistic title="可用会话号" value="1 / 2" />
              </Col>
            </Row>
          </Card>
        </Col>
      </Row>

      {/* 3. System Statistics Grid */}
      <Row gutter={[16, 16]}>
        <Col span={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="今日执行调查任务"
              value={128}
              prefix={<ThunderboltOutlined style={{ color: '#1677ff' }} />}
              suffix="次"
            />
            <div style={{ marginTop: 8 }}>
              <Progress percent={94} size="small" status="active" />
              <Typography.Text type="secondary" style={{ fontSize: 11 }}>成功率 94.5%</Typography.Text>
            </div>
          </Card>
        </Col>

        <Col span={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="已归档评论证据条目"
              value={1420}
              prefix={<DatabaseOutlined style={{ color: '#722ed1' }} />}
              suffix="条"
            />
            <Typography.Text type="secondary" style={{ fontSize: 11, marginTop: 8, display: 'block' }}>
              平均单次任务支撑 11.2 条原声
            </Typography.Text>
          </Card>
        </Col>

        <Col span={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="评论去重与对齐率"
              value={98.2}
              prefix={<CheckCircleOutlined style={{ color: '#52c41a' }} />}
              suffix="%"
            />
            <Typography.Text type="secondary" style={{ fontSize: 11, marginTop: 8, display: 'block' }}>
              跨平台商户 POI 唯一实体绑定
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
              电话、用户名自动严格掩码
            </Typography.Text>
          </Card>
        </Col>
      </Row>
    </Space>
  )
}
