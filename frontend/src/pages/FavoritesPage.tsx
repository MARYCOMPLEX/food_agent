import { useEffect } from 'react'
import { motion } from 'framer-motion'
import { useUserStore } from '../stores/userStore'
import { RestaurantCard } from '../components/restaurant/RestaurantCard'
import { EmptyState } from '../components/shared/EmptyState'
import { useNavigate } from 'react-router-dom'

export function FavoritesPage() {
  const { favorites, fetchFavorites } = useUserStore()
  const navigate = useNavigate()
  const items = Array.from(favorites.values())

  useEffect(() => {
    fetchFavorites()
  }, [fetchFavorites])

  return (
    <div className="px-4 py-4">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="font-display text-lg font-bold text-ink">我的收藏</h2>
          <p className="text-xs text-muted">{items.length} 家餐厅</p>
        </div>
      </div>

      {items.length === 0 ? (
        <EmptyState
          icon="💝"
          title="还没有收藏"
          description="搜索美食时，点击爱心收藏你喜欢的餐厅"
          action={{ label: '去探索', onClick: () => navigate('/') }}
        />
      ) : (
        <motion.div
          initial="hidden"
          animate="visible"
          variants={{
            hidden: {},
            visible: { transition: { staggerChildren: 0.06 } },
          }}
          className="space-y-3"
        >
          {items.map((r, i) => (
            <RestaurantCard key={r.name + i} restaurant={r} index={i} />
          ))}
        </motion.div>
      )}
    </div>
  )
}
