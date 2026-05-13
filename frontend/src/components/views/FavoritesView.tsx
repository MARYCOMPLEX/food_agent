import { useEffect, useState } from 'react'
import { Heart } from 'lucide-react'
import { useUserStore } from '@/stores/userStore'
import { RestaurantCard } from '@/components/restaurant/RestaurantCard'
import { EmptyState } from '@/components/shared/EmptyState'
import { MobilePage } from '@/components/mobile/MobilePage'
import { Skeleton } from '@/components/ui/skeleton'

function FavoriteSkeletonCard() {
  return (
    <div className="rounded-xl border bg-card p-4 space-y-3">
      <div className="flex items-center gap-3">
        <Skeleton className="size-12 rounded-lg" />
        <div className="flex-1 space-y-2">
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="h-3 w-1/2" />
        </div>
      </div>
      <Skeleton className="h-3 w-full" />
      <Skeleton className="h-3 w-4/5" />
    </div>
  )
}

export function FavoritesView() {
  const { favorites, fetchFavorites } = useUserStore()
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    const load = async () => {
      setIsLoading(true)
      await fetchFavorites()
      setIsLoading(false)
    }
    load()
  }, [fetchFavorites])

  const list = Array.from(favorites.values())

  return (
    <MobilePage subtitle={`${list.length} 家餐厅`}>
      {isLoading ? (
        <div className="px-4 md:px-6 pb-6 space-y-3 md:grid md:grid-cols-2 md:gap-4 md:space-y-0 max-w-5xl mx-auto w-full">
          {Array.from({ length: 3 }).map((_, i) => (
            <FavoriteSkeletonCard key={i} />
          ))}
        </div>
      ) : list.length === 0 ? (
        <EmptyState
          icon={
            <Heart
              size={24}
              className="fill-current text-transparent bg-gradient-to-br from-orange-400 to-amber-500 bg-clip-text"
              style={{
                fill: 'url(#heart-gradient)',
              }}
            />
          }
          title="还没有收藏"
          description="搜索时点击收藏按钮，把喜欢的餐厅保存在这里"
        />
      ) : (
        <div className="px-4 md:px-6 pb-6 space-y-3 md:grid md:grid-cols-2 md:gap-4 md:space-y-0 max-w-5xl mx-auto w-full">
          {list.map((r, i) => (
            <RestaurantCard key={`${r.name}-${i}`} restaurant={r} index={i} />
          ))}
        </div>
      )}
      <svg width="0" height="0" className="absolute">
        <defs>
          <linearGradient id="heart-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#fb923c" />
            <stop offset="100%" stopColor="#f59e0b" />
          </linearGradient>
        </defs>
      </svg>
    </MobilePage>
  )
}
