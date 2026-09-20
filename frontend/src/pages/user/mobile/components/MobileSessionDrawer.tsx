import React from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Drawer,
  Button,
  Typography,
  Space,
  Card,
  Tag,
  Avatar,
} from 'antd'
import {
  PlusOutlined,
  DeleteOutlined,
  GlobalOutlined,
  ControlOutlined,
  RobotOutlined,
} from '@ant-design/icons'

interface MobileSessionDrawerProps {
  open: boolean
  onClose: () => void
  currentSessionId: string
  historyList: any[]
  onSelectSession: (sid: string) => void
  onDeleteSession: (sid: string, e: React.MouseEvent) => void
  onStartNewChat: () => void
  mcpServices: any[]
  accounts: any
  onOpenLoginModal: (platform: 'xhs_pc' | 'dianping' | 'ctrip' | 'xiecheng') => void
}

export function MobileSessionDrawer({
  open,
  onClose,
  currentSessionId,
  historyList,
  onSelectSession,
  onDeleteSession,
  onStartNewChat,
  mcpServices,
  accounts,
  onOpenLoginModal,
}: MobileSessionDrawerProps) {
  const navigate = useNavigate()

  return (
    <Drawer
      open={open}
      onClose={onClose}
      placement="left"
      width="82%"
      styles={{
        header: { padding: '14px 16px', borderBottom: '1px solid #f0f0f0' },
        body: { padding: '12px 14px', display: 'flex', flexDirection: 'column', height: '100%' },
      }}
      title={
        <Space size={8} align="center">
          <Avatar
            shape="square"
            size="small"
            icon={<RobotOutlined />}
            style={{ backgroundColor: '#1677ff' }}
          />
          <Typography.Text strong style={{ fontSize: 15 }}>
            Food Agent 探店向导
          </Typography.Text>
        </Space>
      }
    >
      {/* 1. New Chat Button */}
      <Button
        type="primary"
        block
        size="large"
        icon={<PlusOutlined />}
        onClick={() => {
          onStartNewChat()
          onClose()
        }}
        style={{ borderRadius: 10, marginBottom: 14 }}
      >
        新建探店调研
      </Button>

      {/* 2. History Sessions */}
      <div style={{ flex: 1, overflowY: 'auto', marginBottom: 14 }}>
        <Typography.Text type="secondary" style={{ fontSize: 12, padding: '4px 0 8px', display: 'block' }}>
          历史对话 ({historyList.length})
        </Typography.Text>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {historyList.length === 0 ? (
            <div style={{ padding: '36px 0', textAlign: 'center' }}>
              <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                暂无历史对话记录
              </Typography.Text>
            </div>
          ) : (
            historyList.map((item) => {
              const isSelected = item.session_id === currentSessionId
              return (
                <div
                  key={item.session_id}
                  onClick={() => {
                    onSelectSession(item.session_id)
                    onClose()
                  }}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '10px 12px',
                    borderRadius: 10,
                    cursor: 'pointer',
                    backgroundColor: isSelected ? '#e6f4ff' : '#fafafa',
                    border: isSelected ? '1px solid #91caff' : '1px solid #f0f0f0',
                    transition: 'all 0.15s ease',
                  }}
                >
                  <Typography.Text
                    ellipsis
                    style={{
                      fontSize: 13,
                      fontWeight: isSelected ? 600 : 400,
                      color: isSelected ? '#1677ff' : '#262626',
                      flex: 1,
                      marginRight: 8,
                    }}
                  >
                    {item.query || '未命名调研'}
                  </Typography.Text>

                  <Button
                    type="text"
                    size="small"
                    icon={<DeleteOutlined style={{ fontSize: 14, color: '#bfbfbf' }} />}
                    onClick={(e) => onDeleteSession(item.session_id, e)}
                  />
                </div>
              )
            })
          )}
        </div>
      </div>

      {/* 3. Bottom MCP Status & Ops console */}
      <div style={{ borderTop: '1px solid #f0f0f0', paddingTop: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
        <Card
          size="small"
          style={{ background: '#fcfcfc', borderRadius: 10, borderColor: '#f0f0f0' }}
          styles={{ body: { padding: '8px 10px' } }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
            <Space size={4}>
              <GlobalOutlined style={{ fontSize: 12, color: '#8c8c8c' }} />
              <Typography.Text style={{ fontSize: 12, fontWeight: 500 }}>
                探店数据源连接
              </Typography.Text>
            </Space>
          </div>

          {mcpServices.length === 0 ? (
            <Typography.Text type="secondary" style={{ fontSize: 11 }}>
              未检测到探店 MCP 工具
            </Typography.Text>
          ) : (
            <Space direction="vertical" size={4} style={{ width: '100%' }}>
              {mcpServices.map((svc) => {
                const sid = (svc.service_id || '').toLowerCase()
                const sname = (svc.name || '').toLowerCase()
                const isXhs = sid.includes('xhs') || sid.includes('xiaohongshu') || sname.includes('小红书')
                const isCtrip = sid.includes('ctrip') || sid.includes('xiecheng') || sname.includes('携程')
                const platform = isXhs ? 'xhs_pc' : (isCtrip ? 'ctrip' : 'dianping')

                const isOnline = Boolean((svc as any).service_online ?? (svc as any).is_active ?? true)
                const isAuth = Boolean((svc as any).is_authenticated ?? (isCtrip ? isOnline : false))

                let dotColor = '#d9d9d9'
                if (!isOnline) {
                  dotColor = '#bfbfbf'
                } else if (isAuth) {
                  dotColor = '#52c41a'
                } else {
                  dotColor = '#faad14'
                }

                return (
                  <div
                    key={svc.service_id}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      fontSize: 11,
                      padding: '2px 0',
                    }}
                  >
                    <Space size={4}>
                      <span
                        style={{
                          width: 6,
                          height: 6,
                          borderRadius: '50%',
                          backgroundColor: dotColor,
                          display: 'inline-block',
                        }}
                      />
                      <Typography.Text style={{ fontSize: 11 }}>{svc.name}</Typography.Text>
                    </Space>

                    {isAuth ? (
                      <Space size={4}>
                        <Tag color="success" style={{ margin: 0, fontSize: 10, padding: '0 4px', lineHeight: '16px' }}>
                          已连通
                        </Tag>
                        {!isCtrip && (
                          <Button
                            type="link"
                            size="small"
                            style={{ padding: 0, fontSize: 11, height: 'auto', color: '#1677ff' }}
                            onClick={() => {
                              onOpenLoginModal(platform)
                              onClose()
                            }}
                          >
                            重新授权
                          </Button>
                        )}
                      </Space>
                    ) : isOnline ? (
                      <Button
                        type="link"
                        size="small"
                        style={{ padding: 0, fontSize: 11, height: 'auto', color: '#fa8c16' }}
                        onClick={() => {
                          onOpenLoginModal(platform)
                          onClose()
                        }}
                      >
                        授权
                      </Button>
                    ) : (
                      <Tag color="default" style={{ margin: 0, fontSize: 10, padding: '0 4px', lineHeight: '16px' }}>
                        服务离线
                      </Tag>
                    )}
                  </div>
                )
              })}
            </Space>
          )}
        </Card>

        <Button
          block
          icon={<ControlOutlined />}
          onClick={() => {
            navigate('/ops')
            onClose()
          }}
          style={{ fontSize: 13, borderRadius: 8 }}
        >
          运维管控平台
        </Button>
      </div>
    </Drawer>
  )
}
