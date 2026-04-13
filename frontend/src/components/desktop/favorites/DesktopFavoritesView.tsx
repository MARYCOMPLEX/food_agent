import { useEffect } from 'react'
import { Typography, Empty, Flex } from 'antd'
import { useUserStore } from '@/stores/userStore'
import { DesktopRestaurantCard } from '@/components/desktop/search/DesktopRestaurantCard'

const { Title, Text } = Typography

export function DesktopFavoritesView() {
  const { favorites, fetchFavorites } = useUserStore()

  useEffect(() => {
    fetchFavorites()
  }, [fetchFavorites])

  const items = Array.from(favorites.values())

  return (
    <div style={{ padding: 24, maxWidth: 960, margin: '0 auto' }}>
      <Flex justify="space-between" align="center" style={{ marginBottom: 24 }}>
        <Title level={3} style={{ margin: 0 }}>我的收藏</Title>
        <Text type="secondary">{items.length} 家餐厅</Text>
      </Flex>

      {items.length === 0 ? (
        <Empty description="还没有收藏任何餐厅" style={{ marginTop: 80 }} />
      ) : (
        items.map((r) => (
          <DesktopRestaurantCard key={r.name} restaurant={r} />
        ))
      )}
    </div>
  )
}
