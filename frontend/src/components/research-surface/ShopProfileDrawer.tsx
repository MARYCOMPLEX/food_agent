import React from 'react'
import { Drawer, Descriptions, Tag, Image, Button, Alert, Space, Typography } from 'antd'
import {
  ShopOutlined,
  SendOutlined,
  CheckCircleOutlined,
  InfoCircleOutlined,
  EnvironmentOutlined,
  ClockCircleOutlined,
  PhoneOutlined,
} from '@ant-design/icons'
import type {
  ResearchProfileViewV1,
  ResearchRecommendationViewV1,
} from '../../shared/contracts/research'

interface ShopProfileDrawerProps {
  isOpen: boolean
  profile: ResearchProfileViewV1 | null
  recommendation?: ResearchRecommendationViewV1 | null
  onClose: () => void
  onFollowUp?: (shopName: string) => void
}

export function ShopProfileDrawer({
  isOpen,
  profile,
  recommendation,
  onClose,
  onFollowUp,
}: ShopProfileDrawerProps) {
  if (!isOpen || (!profile && !recommendation)) return null

  const shopName = profile?.name || recommendation?.title || '店铺档案'
  const isEnriched = profile && profile.status === 'complete'
  const isPartial = profile && (profile.status === 'partial' || profile.status === 'pending')

  return (
    <Drawer
      open={isOpen}
      onClose={onClose}
      title={
        <Space>
          <ShopOutlined style={{ color: '#1677ff' }} />
          <span>{shopName}</span>
        </Space>
      }
      width={460}
      extra={
        onFollowUp && (
          <Button
            type="primary"
            size="small"
            icon={<SendOutlined />}
            onClick={() => {
              onFollowUp(shopName)
              onClose()
            }}
          >
            就此店追问
          </Button>
        )
      }
    >
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        {isPartial && (
          <Alert
            message="资料部分就绪"
            description="大众点评部分字段需二次核验，评论证据与核心分析正常生效。"
            type="warning"
            showIcon
            icon={<InfoCircleOutlined />}
          />
        )}

        {isEnriched && (
          <Alert
            message="结构化事实已完整核验"
            description="商户地址、营业时间、人均消费与招牌菜均已核对对齐。"
            type="success"
            showIcon
            icon={<CheckCircleOutlined />}
          />
        )}

        {profile?.images && profile.images.length > 0 && (
          <div>
            <Typography.Text strong style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
              店铺实景照片
            </Typography.Text>
            <Image.PreviewGroup>
              <Space wrap size={8}>
                {profile.images.map((img, i) => {
                  const url = typeof img === 'string' ? img : (img as any)?.url
                  return (
                    <Image
                      key={i}
                      width={120}
                      height={90}
                      src={url}
                      style={{ objectFit: 'cover', borderRadius: 6 }}
                    />
                  )
                })}
              </Space>
            </Image.PreviewGroup>
          </div>
        )}

        <Descriptions bordered column={1} size="small">
          <Descriptions.Item label="商户全称">
            <Typography.Text strong>{shopName}</Typography.Text>
          </Descriptions.Item>
          <Descriptions.Item label="人均消费">
            <Typography.Text type="danger" strong>
              {profile?.averagePrice ? `￥${profile.averagePrice} / 人` : '暂未标明'}
            </Typography.Text>
          </Descriptions.Item>
          <Descriptions.Item label="综合评分">
            <Tag color="gold">{profile?.rating ? `${profile.rating} 分` : '暂无'}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="精确地址">
            <Space align="start">
              <EnvironmentOutlined style={{ color: '#1677ff', marginTop: 3 }} />
              <span>{profile?.address || '暂无详细街道信息'}</span>
            </Space>
          </Descriptions.Item>
          <Descriptions.Item label="营业时间">
            <Space align="start">
              <ClockCircleOutlined style={{ color: '#52c41a', marginTop: 3 }} />
              <span>{profile?.openingHours || '暂未收录营业时间'}</span>
            </Space>
          </Descriptions.Item>
          {profile?.phone && (
            <Descriptions.Item label="联系电话">
              <Space align="start">
                <PhoneOutlined style={{ marginTop: 3 }} />
                <span>{profile.phone}</span>
              </Space>
            </Descriptions.Item>
          )}
        </Descriptions>

        {recommendation?.highlights && recommendation.highlights.length > 0 && (
          <div>
            <Typography.Text strong style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
              推荐亮点
            </Typography.Text>
            <Space wrap>
              {recommendation.highlights.map((h, i) => (
                <Tag key={i} color="blue">
                  {h}
                </Tag>
              ))}
            </Space>
          </div>
        )}

        {recommendation?.warnings && recommendation.warnings.length > 0 && (
          <div>
            <Typography.Text strong style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
              避雷提醒
            </Typography.Text>
            <Space wrap>
              {recommendation.warnings.map((w, i) => (
                <Tag key={i} color="volcano">
                  避雷: {w}
                </Tag>
              ))}
            </Space>
          </div>
        )}
      </Space>
    </Drawer>
  )
}
