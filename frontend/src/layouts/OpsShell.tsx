import React, { useState } from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { Layout, Menu, Button, Badge, Space, Typography, Tag, Card, Drawer } from 'antd'
import {
  DashboardOutlined,
  CloudServerOutlined,
  HistoryOutlined,
  DatabaseOutlined,
  SettingOutlined,
  ArrowLeftOutlined,
  SafetyCertificateOutlined,
  ControlOutlined,
  MenuOutlined,
} from '@ant-design/icons'
import { storage } from '../shared/utils/storage'
import { useIsMobile } from '../hooks/useIsMobile'

export function OpsShell() {
  const navigate = useNavigate()
  const location = useLocation()
  const isMobile = useIsMobile(768)
  const [drawerOpen, setDrawerOpen] = useState(false)

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
          padding: isMobile ? '0 12px' : '0 24px',
          height: isMobile ? 50 : 56,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          lineHeight: isMobile ? '50px' : '56px',
          position: 'sticky',
          top: 0,
          zIndex: 100,
        }}
      >
        {isMobile ? (
          <>
            <Space size={8} align="center">
              <Button
                type="text"
                size="small"
                icon={<ArrowLeftOutlined />}
                onClick={() => {
                  const lastSid = storage.get<string>('food_agent_last_active_session', '')
                  navigate(lastSid ? `/chat/${lastSid}` : '/chat')
                }}
                style={{ padding: '0 4px' }}
              />
              <ControlOutlined style={{ fontSize: 16, color: '#1677ff' }} />
              <Typography.Text strong style={{ fontSize: 14 }}>
                运维管控中台
              </Typography.Text>
              <Tag color="blue" style={{ fontSize: 10, margin: 0 }}>PROD</Tag>
            </Space>

            <Space size={8} align="center">
              <Badge status="success" title="ALL SYSTEMS OPERATIONAL" />
              <Button
                type="text"
                icon={<MenuOutlined style={{ fontSize: 17 }} />}
                onClick={() => setDrawerOpen(true)}
                style={{ padding: '0 4px' }}
              />
            </Space>
          </>
        ) : (
          <>
            <Space size={16}>
              <Button
                icon={<ArrowLeftOutlined />}
                onClick={() => {
                  const lastSid = storage.get<string>('food_agent_last_active_session', '')
                  navigate(lastSid ? `/chat/${lastSid}` : '/chat')
                }}
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
          </>
        )}
      </Layout.Header>

      {/* Mobile Horizontal Quick Tabs */}
      {isMobile && (
        <div
          style={{
            display: 'flex',
            overflowX: 'auto',
            whiteSpace: 'nowrap',
            gap: 6,
            padding: '8px 12px',
            background: '#fff',
            borderBottom: '1px solid #f0f0f0',
            scrollbarWidth: 'none',
            position: 'sticky',
            top: 50,
            zIndex: 90,
          }}
        >
          {menuItems.map((item) => {
            const active = selectedKey === item.key
            return (
              <button
                key={item.key}
                type="button"
                onClick={() => navigate(item.key)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 5,
                  padding: '5px 11px',
                  borderRadius: 14,
                  border: active ? '1px solid #1677ff' : '1px solid #e8e8e8',
                  backgroundColor: active ? '#e6f4ff' : '#fafafa',
                  color: active ? '#1677ff' : '#595959',
                  fontSize: 12,
                  fontWeight: active ? 600 : 400,
                  cursor: 'pointer',
                  flexShrink: 0,
                }}
              >
                {item.icon}
                <span>{item.label}</span>
              </button>
            )
          })}
        </div>
      )}

      {/* Mobile Left Drawer */}
      <Drawer
        title={
          <Space align="center">
            <ControlOutlined style={{ color: '#1677ff' }} />
            <span>运维管控中台</span>
          </Space>
        }
        placement="left"
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={270}
        styles={{ body: { padding: '12px 0' } }}
      >
        <Menu
          mode="inline"
          selectedKeys={[selectedKey]}
          items={menuItems}
          onClick={({ key }) => {
            navigate(key)
            setDrawerOpen(false)
          }}
          style={{ borderRight: 0 }}
        />

        <div style={{ padding: 16, marginTop: 16 }}>
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
      </Drawer>

      <Layout>
        {/* Desktop Sider Menu */}
        {!isMobile && (
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
        )}

        {/* Content Body */}
        <Layout.Content style={{ padding: isMobile ? '12px 10px' : '24px', background: '#f5f5f5', overflowY: 'auto' }}>
          <div style={{ maxWidth: 1200, margin: '0 auto' }}>
            <Outlet />
          </div>
        </Layout.Content>
      </Layout>
    </Layout>
  )
}
