import React from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { Layout, Menu, Button, Badge, Space, Typography, Tag, Card } from 'antd'
import {
  DashboardOutlined,
  CloudServerOutlined,
  HistoryOutlined,
  DatabaseOutlined,
  SettingOutlined,
  ArrowLeftOutlined,
  SafetyCertificateOutlined,
  CheckCircleOutlined,
  ControlOutlined,
} from '@ant-design/icons'

export function OpsShell() {
  const navigate = useNavigate()
  const location = useLocation()

  const menuItems = [
    { key: '/ops', label: '系统总览', icon: <DashboardOutlined /> },
    { key: '/ops/services', label: '服务与工具目录', icon: <CloudServerOutlined /> },
    { key: '/ops/tasks', label: '任务执行观测', icon: <HistoryOutlined /> },
    { key: '/ops/evidence', label: '证据数据观测', icon: <DatabaseOutlined /> },
    { key: '/ops/governance', label: '模型与策略治理', icon: <SettingOutlined /> },
  ]

  // Active key
  const selectedKey = menuItems.some((item) => item.key === location.pathname)
    ? location.pathname
    : location.pathname.startsWith('/ops/services')
    ? '/ops/services'
    : '/ops'

  return (
    <Layout style={{ minHeight: '100vh' }}>
      {/* Top Header */}
      <Layout.Header
        style={{
          background: '#fff',
          borderBottom: '1px solid #f0f0f0',
          padding: '0 24px',
          height: 56,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          lineHeight: '56px',
        }}
      >
        <Space size={16}>
          <Button
            icon={<ArrowLeftOutlined />}
            onClick={() => navigate('/')}
          >
            返回对话端
          </Button>

          <Space size={8}>
            <ControlOutlined style={{ fontSize: 18, color: '#1677ff' }} />
            <Typography.Text strong style={{ fontSize: 16 }}>
              Food Agent 运维管控中台
            </Typography.Text>
            <Tag color="blue">PROD</Tag>
          </Space>
        </Space>

        <Space size={16}>
          <Badge status="success" text="ALL SYSTEMS OPERATIONAL" style={{ fontSize: 12, fontWeight: 500 }} />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            MCP TOOLS: 14 DISCOVERED / 12 ACTIVE
          </Typography.Text>
        </Space>
      </Layout.Header>

      <Layout>
        {/* Sider Menu */}
        <Layout.Sider
          width={220}
          theme="light"
          style={{ borderRight: '1px solid #f0f0f0' }}
        >
          <div style={{ padding: '16px 12px 8px' }}>
            <Typography.Text type="secondary" style={{ fontSize: 11, textTransform: 'uppercase', paddingLeft: 8 }}>
              管理与观测中心
            </Typography.Text>
          </div>

          <Menu
            mode="inline"
            selectedKeys={[selectedKey]}
            items={menuItems}
            onClick={({ key }) => navigate(key)}
            style={{ borderRight: 0 }}
          />

          <div style={{ padding: 16, marginTop: 24 }}>
            <Card size="small" style={{ background: '#fafafa', fontSize: 11 }}>
              <Space direction="vertical" size={4}>
                <Space>
                  <SafetyCertificateOutlined style={{ color: '#52c41a' }} />
                  <Typography.Text strong style={{ fontSize: 11 }}>合规审计状态</Typography.Text>
                </Space>
                <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                  敏感字段脱敏与只读限权已生效。
                </Typography.Text>
              </Space>
            </Card>
          </div>
        </Layout.Sider>

        {/* Content Body */}
        <Layout.Content style={{ padding: '24px', background: '#f5f5f5', overflowY: 'auto' }}>
          <div style={{ maxWidth: 1200, margin: '0 auto' }}>
            <Outlet />
          </div>
        </Layout.Content>
      </Layout>
    </Layout>
  )
}
