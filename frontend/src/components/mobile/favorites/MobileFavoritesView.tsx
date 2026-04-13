import { useEffect } from 'react'
import { Heart } from 'lucide-react'
import { useUserStore } from '@/stores/userStore'
import { RestaurantCard } from '@/components/restaurant/RestaurantCard'
import { EmptyState } from '@/components/shared/EmptyState'
import { MobilePage } from '@/components/mobile/MobilePage'

export function MobileFavoritesView() {
  const { favorites, fetchFavorites } = useUserStore()

  useEffect(() => {
    fetchFavorites()
  }, [fetchFavorites])

  const list = Array.from(favorites.values())

  return (
    <MobilePage subtitle={`${list.length} 家餐厅`}>
      {list.length === 0 ? (
        <EmptyState
          icon={<Heart size={24} />}
          title="还没有收藏"
          description="搜索时点击收藏按钮，把喜欢的餐厅保存在这里"
        />
      ) : (
        <div className="px-4 pb-6 space-y-3">
          {list.map((r, i) => (
            <RestaurantCard key={`${r.name}-${i}`} restaurant={r} index={i} />
          ))}
        </div>
      )}
    </MobilePage>
  )
}
