import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Bookmark,
  Search,
  Layers,
  Sparkles,
  MapPin,
  Trash2,
  ExternalLink,
  UtensilsCrossed,
  AlertTriangle,
  ArrowRight,
  Clock,
  Compass,
} from 'lucide-react'
import { storage } from '../../shared/utils/storage'
import { useToast } from '../../context/ToastContext'
import { RestaurantComparisonModal } from '../../components/restaurant/RestaurantComparisonModal'
import type { Restaurant } from '../../shared/contracts'

interface FavoriteRecord {
  id: string
  name: string
  address?: string
  price?: string
  oneLiner?: string
  pros?: string[]
  cons?: string[]
  savedAt: string
  sessionId?: string
  hasControversy?: boolean
  city?: string
}

export function FavoritesPage() {
  const navigate = useNavigate()
  const { showToast } = useToast()

  const [favoritesList, setFavoritesList] = useState<FavoriteRecord[]>([])
  const [searchQuery, setSearchQuery] = useState<string>('')
  const [compareList, setCompareList] = useState<Restaurant[]>([])
  const [isCompareModalOpen, setIsCompareModalOpen] = useState<boolean>(false)

  useEffect(() => {
    // Load favorites from local storage
    const rawIds = storage.get<string[]>('anyfast_user_favorites', [])
    const savedRecords = storage.get<FavoriteRecord[]>('anyfast_favorite_records', [])

    // Ensure we have mock items if user just started
    if (savedRecords.length === 0 && rawIds.length === 0) {
      const defaultFavorites: FavoriteRecord[] = [
        {
          id: 'shop_fav_1',
          name: '蜀九香老火锅 (百花潭总店)',
          address: '成都市青羊区百花潭路 10 号',
          price: '118',
          oneLiner: '评论一致赞誉牛油锅底醇厚、越煮越有回甘；周六晚需留意高峰排队分歧。',
          pros: ['牛油锅底香气持久', '鲜毛肚现撕脆嫩', '老店服务稳定'],
          cons: ['周末18:00后排队超1小时', '锅底偏辣'],
          savedAt: new Date(Date.now() - 86400000 * 2).toISOString(),
          sessionId: 'session_demo_cd_hotpot',
          hasControversy: true,
          city: '成都',
        },
        {
          id: 'shop_fav_2',
          name: '陶陶居酒家 (第十甫路总店)',
          address: '广州市荔湾区第十甫路 20 号',
          price: '88',
          oneLiner: '百年早茶老店，虾饺皮薄虾弹，招牌酥皮水牛奶菠萝包好评率极高。',
          pros: ['手打鲜虾饺饱满多汁', '经典水牛奶菠萝包', '岭南西关风情'],
          cons: ['老店大堂较喧闹', '节假日茶位费微调'],
          savedAt: new Date(Date.now() - 86400000 * 5).toISOString(),
          sessionId: 'session_demo_gz_morningtea',
          hasControversy: false,
          city: '广州',
        },
      ]
      setFavoritesList(defaultFavorites)
      storage.set('anyfast_favorite_records', defaultFavorites)
      storage.set('anyfast_user_favorites', defaultFavorites.map((f) => f.id))
    } else {
      setFavoritesList(savedRecords)
    }
  }, [])

  const handleRemoveFavorite = (id: string, name: string) => {
    const next = favoritesList.filter((f) => f.id !== id)
    setFavoritesList(next)
    storage.set('anyfast_favorite_records', next)
    storage.set('anyfast_user_favorites', next.map((f) => f.id))
    showToast(`已取消收藏 ${name}`, 'info')
  }

  const handleAddToCompare = (fav: FavoriteRecord) => {
    const restaurantObj: Restaurant = {
      id: fav.id,
      name: fav.name,
      oneLiner: fav.oneLiner,
      pros: fav.pros,
      cons: fav.cons,
      price: fav.price,
      address: fav.address,
    }
    if (compareList.some((c) => c.id === fav.id)) {
      setIsCompareModalOpen(true)
      return
    }
    if (compareList.length >= 4) {
      showToast('最多同时对比 4 家餐厅', 'warning')
      return
    }
    setCompareList([...compareList, restaurantObj])
    showToast(`已将 ${fav.name} 加入对比`, 'success')
  }

  const filteredFavorites = favoritesList.filter((f) => {
    if (!searchQuery.trim()) return true
    const q = searchQuery.toLowerCase()
    return (
      f.name.toLowerCase().includes(q) ||
      (f.address && f.address.toLowerCase().includes(q)) ||
      (f.oneLiner && f.oneLiner.toLowerCase().includes(q))
    )
  })

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight flex items-center gap-2">
            <Bookmark className="w-6 h-6 text-orange-600 fill-orange-600" />
            <span>我的收藏餐厅</span>
          </h1>
          <p className="text-xs text-slate-500 mt-1">
            记录收藏时的研究上下文与评论结论，可横向对比或基于当前偏好重新发起核实
          </p>
        </div>

        {/* Search & Compare Actions */}
        <div className="flex items-center gap-3">
          <div className="relative">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              placeholder="搜索收藏店名或地点..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-9 pr-3 py-2 bg-white border border-slate-200 rounded-xl text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-orange-500 w-48 sm:w-60 shadow-xs"
            />
          </div>

          {compareList.length > 0 && (
            <button
              onClick={() => setIsCompareModalOpen(true)}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-orange-600 hover:bg-orange-700 text-white text-xs font-semibold shadow-sm transition-colors"
            >
              <Layers className="w-4 h-4" />
              <span>开始对比 ({compareList.length})</span>
            </button>
          )}
        </div>
      </div>

      {/* Favorites List */}
      {filteredFavorites.length === 0 ? (
        <div className="bg-white rounded-3xl border border-dashed border-slate-200 p-12 text-center space-y-4 shadow-xs">
          <div className="w-12 h-12 rounded-2xl bg-orange-50 text-orange-600 flex items-center justify-center mx-auto">
            <UtensilsCrossed className="w-6 h-6" />
          </div>
          <div>
            <h3 className="text-base font-semibold text-slate-900">暂无收藏餐厅</h3>
            <p className="text-xs text-slate-500 mt-1 max-w-sm mx-auto">
              在调查工作台中点击餐厅卡片右上角的收藏图标，即可将认可的餐厅及其评论结论保存在此
            </p>
          </div>
          <button
            onClick={() => navigate('/app/explore')}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-orange-600 hover:bg-orange-700 text-white text-xs font-semibold shadow-md transition-colors"
          >
            <Compass className="w-4 h-4" />
            <span>发起一次美食调查</span>
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {filteredFavorites.map((fav) => {
            const isCompared = compareList.some((c) => c.id === fav.id)

            return (
              <div
                key={fav.id}
                className="bg-white rounded-2xl border border-slate-200/90 p-5 shadow-xs hover:shadow-md transition-all flex flex-col justify-between space-y-4"
              >
                <div>
                  {/* Top line: Name, Price, Remove */}
                  <div className="flex items-start justify-between gap-3 mb-2">
                    <div>
                      <h3 className="font-bold text-slate-900 text-base leading-snug">{fav.name}</h3>
                      {fav.address && (
                        <div className="flex items-center gap-1 text-xs text-slate-500 mt-0.5">
                          <MapPin className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />
                          <span className="line-clamp-1">{fav.address}</span>
                          {fav.price && (
                            <span className="text-orange-600 font-medium ml-1">· 人均 ￥{fav.price}</span>
                          )}
                        </div>
                      )}
                    </div>

                    <button
                      onClick={() => handleRemoveFavorite(fav.id, fav.name)}
                      className="text-slate-300 hover:text-rose-500 p-1.5 rounded-lg hover:bg-rose-50 transition-colors"
                      title="取消收藏"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>

                  {/* Conclusion from when it was saved */}
                  {fav.oneLiner && (
                    <div className="p-3 rounded-xl bg-slate-50 border border-slate-100 text-xs text-slate-700 leading-relaxed mb-3">
                      <span className="font-semibold text-slate-900">收藏时结论：</span>
                      {fav.oneLiner}
                    </div>
                  )}

                  {/* Pros & Cons */}
                  <div className="space-y-1.5 text-xs mb-3">
                    {fav.pros && fav.pros.slice(0, 2).map((p, idx) => (
                      <div key={idx} className="text-emerald-800 flex items-start gap-1.5">
                        <span className="text-emerald-500 font-bold">✓</span>
                        <span>{p}</span>
                      </div>
                    ))}
                    {fav.cons && fav.cons.slice(0, 1).map((c, idx) => (
                      <div key={idx} className="text-amber-800 flex items-start gap-1.5">
                        <AlertTriangle className="w-3.5 h-3.5 text-amber-500 flex-shrink-0 mt-0.5" />
                        <span>{c}</span>
                      </div>
                    ))}
                  </div>

                  {/* Controversy Tag */}
                  {fav.hasControversy && (
                    <div className="inline-flex items-center gap-1 text-[11px] text-amber-700 bg-amber-50 border border-amber-200 px-2 py-0.5 rounded-md">
                      <AlertTriangle className="w-3 h-3 text-amber-500" />
                      <span>存在未完全核清的评论争议</span>
                    </div>
                  )}
                </div>

                {/* Footer: Date, Compare Button, Return to Session */}
                <div className="pt-3 border-t border-slate-100 flex items-center justify-between text-xs">
                  <span className="text-[11px] text-slate-400 font-mono">
                    收藏于 {new Date(fav.savedAt).toLocaleDateString()}
                  </span>

                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => handleAddToCompare(fav)}
                      className={`px-3 py-1.5 rounded-xl border text-xs font-medium flex items-center gap-1 transition-colors ${
                        isCompared
                          ? 'bg-orange-50 text-orange-700 border-orange-200'
                          : 'bg-slate-50 text-slate-600 border-slate-200 hover:bg-slate-100'
                      }`}
                    >
                      <Layers className="w-3.5 h-3.5" />
                      <span>{isCompared ? '已加入对比' : '加入对比'}</span>
                    </button>

                    {fav.sessionId && (
                      <button
                        onClick={() => navigate(`/app/sessions/${fav.sessionId}`)}
                        className="px-3 py-1.5 rounded-xl bg-slate-900 hover:bg-orange-600 text-white font-medium transition-colors flex items-center gap-1"
                      >
                        <span>原会话</span>
                        <ArrowRight className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Comparison Modal */}
      <RestaurantComparisonModal
        isOpen={isCompareModalOpen}
        restaurants={compareList}
        onClose={() => setIsCompareModalOpen(false)}
        onRemoveRestaurant={(id) => setCompareList(compareList.filter((r) => r.id !== id))}
      />
    </div>
  )
}
