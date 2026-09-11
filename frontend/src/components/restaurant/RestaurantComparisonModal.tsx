import React from 'react'
import { Modal, Table, Tag, Button, Space, Typography } from 'antd'
import {
  DiffOutlined,
  DeleteOutlined,
  SendOutlined,
  CheckCircleOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import type { Restaurant } from '../../shared/contracts'

interface RestaurantComparisonModalProps {
  isOpen: boolean
  restaurants: Restaurant[]
  onClose: () => void
  onRemoveRestaurant?: (id: string) => void
  onSelectForFollowUp?: (restaurant: Restaurant) => void
}

export function RestaurantComparisonModal({
  isOpen,
  restaurants,
  onClose,
  onRemoveRestaurant,
  onSelectForFollowUp,
}: RestaurantComparisonModalProps) {
  if (!isOpen || restaurants.length === 0) return null

  // Table Columns
  const columns = [
    {
      title: '对比维度',
      dataIndex: 'dimension',
      key: 'dimension',
      width: 140,
      render: (text: string) => <Typography.Text strong>{text}</Typography.Text>,
    },
    ...restaurants.map((shop) => ({
      title: (
        <Space direction="vertical" size={2} style={{ width: '100%' }}>
          <Space style={{ width: '100%', justifyContent: 'space-between' }}>
            <Typography.Text strong style={{ fontSize: 15 }}>{shop.name}</Typography.Text>
            {onRemoveRestaurant && (
              <Button
                type="text"
                danger
                size="small"
                icon={<DeleteOutlined />}
                onClick={(e) => {
                  e.stopPropagation()
                  onRemoveRestaurant(shop.id)
                }}
                title="移除"
              />
            )}
          </Space>
          {shop.price && <Tag color="blue">人均 ￥{shop.price}</Tag>}
        </Space>
      ),
      dataIndex: shop.id,
      key: shop.id,
      render: (content: React.ReactNode) => content,
    })),
  ]

  // Table Rows (Dimensions)
  const dataSource = [
    {
      key: 'oneLiner',
      dimension: '核心口碑评价',
      ...restaurants.reduce((acc, shop) => {
        acc[shop.id] = (
          <Typography.Paragraph ellipsis={{ rows: 3 }} style={{ marginBottom: 0 }}>
            {shop.oneLiner || '暂无总结'}
          </Typography.Paragraph>
        )
        return acc
      }, {} as Record<string, any>),
    },
    {
      key: 'pros',
      dimension: '推荐招牌 / 亮点',
      ...restaurants.reduce((acc, shop) => {
        acc[shop.id] = shop.pros && shop.pros.length > 0 ? (
          <Space direction="vertical" size={4}>
            {shop.pros.map((p, i) => (
              <span key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 6 }}>
                <CheckCircleOutlined style={{ color: '#52c41a', marginTop: 3 }} />
                <span>{p}</span>
              </span>
            ))}
          </Space>
        ) : (
          <span style={{ color: '#8c8c8c' }}>无突出亮点</span>
        )
        return acc
      }, {} as Record<string, any>),
    },
    {
      key: 'cons',
      dimension: '避坑预警 / 劣势',
      ...restaurants.reduce((acc, shop) => {
        acc[shop.id] = shop.cons && shop.cons.length > 0 ? (
          <Space direction="vertical" size={4}>
            {shop.cons.map((c, i) => (
              <span key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 6 }}>
                <WarningOutlined style={{ color: '#faad14', marginTop: 3 }} />
                <span style={{ color: '#d48806' }}>{c}</span>
              </span>
            ))}
          </Space>
        ) : (
          <Tag color="success">暂无严重避雷反映</Tag>
        )
        return acc
      }, {} as Record<string, any>),
    },
    {
      key: 'address',
      dimension: '位置与营业时间',
      ...restaurants.reduce((acc, shop) => {
        acc[shop.id] = (
          <Space direction="vertical" size={2} style={{ fontSize: 12 }}>
            <div>地址：{shop.address || '请查看大众点评档案'}</div>
            {shop.hours && <div>时间：{shop.hours}</div>}
          </Space>
        )
        return acc
      }, {} as Record<string, any>),
    },
    {
      key: 'actions',
      dimension: '操作',
      ...restaurants.reduce((acc, shop) => {
        acc[shop.id] = (
          <Button
            type="primary"
            size="small"
            icon={<SendOutlined />}
            onClick={() => {
              onSelectForFollowUp?.(shop)
              onClose()
            }}
          >
            就此店追问
          </Button>
        )
        return acc
      }, {} as Record<string, any>),
    },
  ]

  return (
    <Modal
      open={isOpen}
      onCancel={onClose}
      title={
        <Space>
          <DiffOutlined style={{ color: '#1677ff' }} />
          <span>候选餐厅多维横向对比 ({restaurants.length} 家)</span>
        </Space>
      }
      footer={[
        <Button key="close" onClick={onClose}>
          关闭
        </Button>,
      ]}
      width={980}
      centered
    >
      <Table
        dataSource={dataSource}
        columns={columns}
        pagination={false}
        bordered
        size="middle"
        style={{ marginTop: 16 }}
      />
    </Modal>
  )
}
