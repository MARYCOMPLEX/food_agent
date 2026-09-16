import React from 'react'
import { Card, Typography, Space, Tag, Button, Flex, Avatar } from 'antd'
import {
  ShopOutlined,
  DiffOutlined,
  ArrowRightOutlined,
  StarOutlined,
  StarFilled,
} from '@ant-design/icons'

interface MobileRestaurantCardProps {
  rec: any
  index: number
  profile: any
  isFavorite: boolean
  onToggleFavorite: () => void
  onOpenProfile: () => void
  onAddToCompare: () => void
  onFollowUp: () => void
}

export function MobileRestaurantCard({
  rec,
  index,
  profile,
  isFavorite,
  onToggleFavorite,
  onOpenProfile,
  onAddToCompare,
  onFollowUp,
}: MobileRestaurantCardProps) {
  return (
    <Card
      size="small"
      style={{
        borderRadius: 14,
        borderColor: '#e8e8e8',
        boxShadow: '0 2px 8px rgba(0,0,0,0.03)',
        overflow: 'hidden',
      }}
      styles={{
        body: { padding: '12px 14px' },
      }}
    >
      {/* 1. Header: Rank + Title + Price + Favorite */}
      <Flex justify="space-between" align="flex-start" style={{ marginBottom: 6 }}>
        <Space align="center" size={8} style={{ flex: 1, minWidth: 0 }}>
          <Avatar
            size={22}
            style={{
              backgroundColor: index === 0 ? '#fa8c16' : '#1677ff',
              fontSize: 12,
              fontWeight: 600,
              flexShrink: 0,
            }}
          >
            {rec.rank || index + 1}
          </Avatar>
          <Typography.Text
            strong
            ellipsis
            onClick={onOpenProfile}
            style={{
              fontSize: 15,
              color: '#1f1f1f',
              cursor: 'pointer',
              fontWeight: 600,
            }}
          >
            {rec.title}
          </Typography.Text>
          {profile?.averagePrice && (
            <Tag color="blue" style={{ margin: 0, fontSize: 11, padding: '0 4px', lineHeight: '18px' }}>
              ￥{profile.averagePrice}/人
            </Tag>
          )}
        </Space>

        <Button
          type="text"
          size="small"
          icon={isFavorite ? <StarFilled style={{ color: '#faad14', fontSize: 16 }} /> : <StarOutlined style={{ fontSize: 16 }} />}
          onClick={onToggleFavorite}
          style={{ padding: '0 4px' }}
        />
      </Flex>

      {/* 2. Recommendation Summary */}
      {rec.summary && (
        <Typography.Paragraph
          ellipsis={{ rows: 2 }}
          style={{
            margin: '4px 0 8px',
            fontSize: 13,
            lineHeight: 1.5,
            color: '#595959',
          }}
        >
          {rec.summary}
        </Typography.Paragraph>
      )}

      {/* 3. Tags: Highlights & Warnings */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 10 }}>
        {rec.highlights?.map((h: string, i: number) => (
          <Tag key={`h_${i}`} color="success" style={{ margin: 0, fontSize: 11, borderRadius: 4 }}>
            {h}
          </Tag>
        ))}
        {rec.warnings?.map((w: string, i: number) => (
          <Tag key={`w_${i}`} color="warning" style={{ margin: 0, fontSize: 11, borderRadius: 4 }}>
            避坑: {w}
          </Tag>
        ))}
      </div>

      {/* 4. Action Row */}
      <Flex justify="space-between" align="center" style={{ borderTop: '1px solid #f5f5f5', paddingTop: 8 }}>
        <Space size={4}>
          <Button
            size="small"
            icon={<ShopOutlined />}
            onClick={onOpenProfile}
            style={{ fontSize: 12 }}
          >
            档案
          </Button>
          <Button
            size="small"
            icon={<DiffOutlined />}
            onClick={onAddToCompare}
            style={{ fontSize: 12 }}
          >
            对比
          </Button>
        </Space>

        <Button
          type="primary"
          size="small"
          icon={<ArrowRightOutlined />}
          onClick={onFollowUp}
          style={{ fontSize: 12, borderRadius: 6 }}
        >
          就此店追问
        </Button>
      </Flex>
    </Card>
  )
}
