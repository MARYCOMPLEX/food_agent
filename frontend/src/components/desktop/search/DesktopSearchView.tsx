import { useState } from 'react'
import { Input, Tag, Descriptions, Typography, Flex, Spin, Empty } from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import { useSearchStore } from '@/stores/searchStore'
import { DesktopPipeline } from './DesktopPipeline'
import { DesktopRestaurantCard } from './DesktopRestaurantCard'

const { Title, Text } = Typography

const SUGGESTIONS = [
  '上海本地人爱去的小笼包',
  '北京胡同里的地道涮肉',
  '成都本地人推荐的火锅',
  '广州老城区早茶',
  '西安回民街周边面馆',
  '杭州西湖附近本帮菜',
]

export function DesktopSearchView() {
  const {
    status, pipeline, intent, restaurants, summary, search, followUp,
  } = useSearchStore()
  const [followUpText, setFollowUpText] = useState('')

  const isIdle = status === 'idle'

  const handleSearch = (value: string) => {
    const q = value.trim()
    if (!q) return
    search(q)
  }

  const handleFollowUp = () => {
    const q = followUpText.trim()
    if (!q) return
    followUp(q)
    setFollowUpText('')
  }

  /* ---------- Idle State ---------- */
  if (isIdle) {
    return (
      <div style={{ maxWidth: 640, margin: '120px auto 0', textAlign: 'center', padding: '0 24px' }}>
        <Title level={2} style={{ marginBottom: 8 }}>
          <SearchOutlined style={{ marginRight: 8 }} />
          食探
        </Title>
        <Text type="secondary" style={{ display: 'block', marginBottom: 32, fontSize: 15 }}>
          发现本地人真正爱去的餐厅，远离网红雷区
        </Text>

        <Input.Search
          placeholder="输入你想搜索的美食，例如：上海本地人爱吃的生煎"
          enterButton="搜索"
          size="large"
          onSearch={handleSearch}
          style={{ marginBottom: 28 }}
        />

        <Flex wrap="wrap" gap={8} justify="center">
          {SUGGESTIONS.map((s) => (
            <Tag
              key={s}
              style={{ cursor: 'pointer', padding: '4px 12px', fontSize: 13 }}
              onClick={() => handleSearch(s)}
            >
              {s}
            </Tag>
          ))}
        </Flex>
      </div>
    )
  }

  /* ---------- Searching / Completed State ---------- */
  return (
    <Flex gap={24} style={{ padding: 24, minHeight: '100%' }} align="flex-start">
      {/* Left sidebar */}
      <div style={{ width: 320, flexShrink: 0 }}>
        <Title level={5} style={{ marginBottom: 16 }}>搜索进度</Title>
        <DesktopPipeline steps={pipeline} />

        {intent && (
          <Descriptions
            size="small"
            column={1}
            bordered
            style={{ marginTop: 20 }}
            title="解析意图"
          >
            <Descriptions.Item label="地点">{intent.location}</Descriptions.Item>
            {intent.food_type && (
              <Descriptions.Item label="类型">{intent.food_type}</Descriptions.Item>
            )}
            {intent.requirements.length > 0 && (
              <Descriptions.Item label="要求">
                {intent.requirements.join('、')}
              </Descriptions.Item>
            )}
            {intent.exclude_keywords.length > 0 && (
              <Descriptions.Item label="排除">
                {intent.exclude_keywords.join('、')}
              </Descriptions.Item>
            )}
          </Descriptions>
        )}

        {status === 'completed' && (
          <div style={{ marginTop: 24 }}>
            <Text type="secondary" style={{ display: 'block', marginBottom: 8, fontSize: 13 }}>
              继续追问
            </Text>
            <Input.Search
              placeholder="还想了解什么？"
              enterButton="发送"
              value={followUpText}
              onChange={(e) => setFollowUpText(e.target.value)}
              onSearch={handleFollowUp}
            />
          </div>
        )}
      </div>

      {/* Right content */}
      <div style={{ flex: 1, minWidth: 0 }}>
        {summary && (
          <Text style={{ display: 'block', marginBottom: 20, fontSize: 14, lineHeight: 1.6 }}>
            {summary}
          </Text>
        )}

        {status === 'searching' && restaurants.length === 0 && (
          <Flex justify="center" style={{ marginTop: 80 }}>
            <Spin size="large" tip="正在搜索中..." />
          </Flex>
        )}

        {status === 'completed' && restaurants.length === 0 && (
          <Empty description="暂未找到符合条件的餐厅" style={{ marginTop: 80 }} />
        )}

        {restaurants.map((r) => (
          <DesktopRestaurantCard key={r.name} restaurant={r} />
        ))}
      </div>
    </Flex>
  )
}
