import React, { useState } from 'react'
import { Button, Space, Typography, Tag, Badge, Modal, Radio } from 'antd'
import {
  MenuOutlined,
  PlusOutlined,
  DiffOutlined,
  AuditOutlined,
  DownOutlined,
} from '@ant-design/icons'
import type { ModelOption } from '../../types'

interface MobileHeaderProps {
  selectedModel: string
  setSelectedModel: (m: string) => void
  modelOptions: ModelOption[]
  compareCount: number
  evidenceCount: number
  onOpenSidebar: () => void
  onStartNewChat: () => void
  onOpenCompare: () => void
  onOpenInspector: () => void
}

export function MobileHeader({
  selectedModel,
  setSelectedModel,
  modelOptions,
  compareCount,
  evidenceCount,
  onOpenSidebar,
  onStartNewChat,
  onOpenCompare,
  onOpenInspector,
}: MobileHeaderProps) {
  const [modelModalOpen, setModelModalOpen] = useState(false)

  const currentModelObj = modelOptions.find((m) => m.value === selectedModel)
  const displayModelName = currentModelObj?.label || (selectedModel ? selectedModel.split(/[-_]/)[0] : '默认大模型')

  return (
    <header
      style={{
        height: 50,
        backgroundColor: '#fff',
        borderBottom: '1px solid #f0f0f0',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 12px',
        position: 'sticky',
        top: 0,
        zIndex: 50,
        flexShrink: 0,
      }}
    >
      {/* Left: Sidebar trigger */}
      <Space size={8} align="center">
        <Button
          type="text"
          size="middle"
          icon={<MenuOutlined style={{ fontSize: 18 }} />}
          onClick={onOpenSidebar}
          style={{ padding: 4 }}
        />

        {/* Center/Left: App title + Model Pill */}
        <div
          onClick={() => setModelModalOpen(true)}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 4,
            padding: '4px 8px',
            borderRadius: 14,
            backgroundColor: '#f5f5f5',
            cursor: 'pointer',
            maxWidth: 160,
          }}
        >
          <span style={{ fontSize: 14 }}>🍜</span>
          <Typography.Text
            ellipsis
            style={{ fontSize: 12, fontWeight: 500, maxWidth: 100 }}
          >
            {displayModelName}
          </Typography.Text>
          <DownOutlined style={{ fontSize: 9, color: '#8c8c8c' }} />
        </div>
      </Space>

      {/* Right Actions: Compare + Inspector + New Chat */}
      <Space size={4} align="center">
        {compareCount > 0 && (
          <Badge count={compareCount} size="small" offset={[-2, 2]}>
            <Button
              type="text"
              icon={<DiffOutlined style={{ fontSize: 16 }} />}
              onClick={onOpenCompare}
              style={{ padding: 6 }}
            />
          </Badge>
        )}

        <Badge count={evidenceCount > 0 ? evidenceCount : 0} size="small" overflowCount={99} offset={[-2, 2]}>
          <Button
            type="text"
            icon={<AuditOutlined style={{ fontSize: 16, color: evidenceCount > 0 ? '#1677ff' : 'inherit' }} />}
            onClick={onOpenInspector}
            style={{ padding: 6 }}
          />
        </Badge>

        <Button
          type="primary"
          shape="circle"
          size="small"
          icon={<PlusOutlined style={{ fontSize: 12 }} />}
          onClick={onStartNewChat}
          style={{ marginLeft: 2 }}
        />
      </Space>

      {/* Model Selection Modal */}
      <Modal
        title="选择推演大模型"
        open={modelModalOpen}
        onCancel={() => setModelModalOpen(false)}
        footer={null}
        centered
        styles={{ body: { maxHeight: '60vh', overflowY: 'auto' } }}
      >
        <Radio.Group
          value={selectedModel}
          onChange={(e) => {
            setSelectedModel(e.target.value)
            setModelModalOpen(false)
          }}
          style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: 10 }}
        >
          {modelOptions.map((m) => (
            <Radio key={m.value} value={m.value} style={{ padding: '8px 4px', width: '100%' }}>
              <Space size={8}>
                <span style={{ fontWeight: m.value === selectedModel ? 600 : 400 }}>{m.label}</span>
                {m.is_default && <Tag color="blue">默认</Tag>}
              </Space>
            </Radio>
          ))}
        </Radio.Group>
      </Modal>
    </header>
  )
}
