import React from 'react'
import {
  X,
  MapPin,
  Clock,
  Phone,
  Star,
  AlertCircle,
  Utensils,
  CheckCircle2,
} from 'lucide-react'
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
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40 backdrop-blur-xs animate-in fade-in">
      <div className="relative w-full max-w-md h-full bg-white border-l border-zinc-200 shadow-2xl flex flex-col overflow-hidden animate-in slide-in-from-right duration-200">
        {/* Drawer Header */}
        <div className="flex items-center justify-between p-5 border-b border-zinc-100">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-full bg-zinc-100 text-zinc-800 flex items-center justify-center font-bold">
              <Utensils className="w-4 h-4 text-[#10a37f]" />
            </div>
            <div>
              <h3 className="font-semibold text-zinc-900 text-base leading-tight">{shopName}</h3>
              <div className="flex items-center gap-2 text-xs text-zinc-400 mt-0.5">
                <span>大众点评事实档案</span>
                {profile?.updatedAt && (
                  <span className="font-mono text-[11px]">
                    更新于 {new Date(profile.updatedAt).toLocaleDateString()}
                  </span>
                )}
              </div>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-lg text-zinc-400 hover:text-zinc-600 hover:bg-zinc-100 transition-colors"
            aria-label="关闭抽屉"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Drawer Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {/* Completeness Badge */}
          {isPartial && (
            <div className="p-3 rounded-xl bg-zinc-50 border border-zinc-200 text-xs text-zinc-700 flex items-start gap-2">
              <AlertCircle className="w-4 h-4 text-amber-500 flex-shrink-0 mt-0.5" />
              <div>
                <strong className="font-medium text-zinc-900">资料部分就绪：</strong>
                大众点评部分字段需二次核实，评论证据与核心分析正常生效。
              </div>
            </div>
          )}

          {isEnriched && (
            <div className="p-2.5 rounded-xl bg-emerald-50/60 border border-emerald-200/60 text-xs text-emerald-800 flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-[#10a37f] flex-shrink-0" />
              <span>结构化事实完整（地址、人均消费、营业时间已核清）</span>
            </div>
          )}

          {/* Photos Carousel / Grid */}
          {profile?.images && profile.images.length > 0 ? (
            <div className="space-y-2">
              <div className="text-xs font-medium text-zinc-400 uppercase tracking-wider">店铺实景</div>
              <div className="grid grid-cols-3 gap-2">
                {profile.images.slice(0, 3).map((img, i) => {
                  const url = typeof img === 'string' ? img : (img as any)?.url
                  return (
                    <div key={i} className="aspect-square rounded-xl bg-zinc-100 overflow-hidden border border-zinc-200">
                      {url ? (
                        <img src={url} alt={`${shopName} 图 ${i + 1}`} className="w-full h-full object-cover" />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center text-zinc-400 text-xs">无图</div>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          ) : null}

          {/* Key Facts: Address, Hours, Price, Phone */}
          <div className="bg-zinc-50/80 p-4 rounded-2xl border border-zinc-200 space-y-3 text-xs">
            {/* Address */}
            <div className="flex items-start gap-2.5">
              <MapPin className="w-4 h-4 text-zinc-400 flex-shrink-0 mt-0.5" />
              <div>
                <div className="font-medium text-zinc-500">门店地址</div>
                <div className="text-zinc-900 mt-0.5">{profile?.address || '大众点评暂未提供详细地址'}</div>
                {profile?.businessArea && (
                  <div className="text-zinc-400 text-[11px] mt-0.5">商圈：{profile.businessArea}</div>
                )}
              </div>
            </div>

            {/* Hours */}
            <div className="flex items-start gap-2.5">
              <Clock className="w-4 h-4 text-zinc-400 flex-shrink-0 mt-0.5" />
              <div>
                <div className="font-medium text-zinc-500">营业时间</div>
                <div className="text-zinc-900 mt-0.5">{profile?.openingHours || '以门店现场营业为准'}</div>
              </div>
            </div>

            {/* Price & Rating */}
            <div className="flex items-start gap-2.5">
              <Star className="w-4 h-4 text-amber-500 flex-shrink-0 mt-0.5" />
              <div>
                <div className="font-medium text-zinc-500">评分与消费参考</div>
                <div className="text-zinc-900 mt-0.5 flex items-center gap-3">
                  <span>评分：{profile?.rating ? `${profile.rating} 分` : '暂无'}</span>
                  <span>人均：{profile?.averagePrice ? `￥${profile.averagePrice}` : '待录入'}</span>
                  {profile?.reviewCount && (
                    <span className="text-zinc-400 text-[11px]">{profile.reviewCount} 条评价</span>
                  )}
                </div>
              </div>
            </div>

            {/* Phone */}
            {profile?.phone && (
              <div className="flex items-start gap-2.5">
                <Phone className="w-4 h-4 text-zinc-400 flex-shrink-0 mt-0.5" />
                <div>
                  <div className="font-medium text-zinc-500">联系电话</div>
                  <div className="text-zinc-900 mt-0.5 font-mono">{profile.phone}</div>
                </div>
              </div>
            )}
          </div>

          {/* Recommended Dishes */}
          {profile?.recommendedDishes && profile.recommendedDishes.length > 0 && (
            <div className="space-y-2">
              <div className="text-xs font-medium text-zinc-400 uppercase tracking-wider">招牌菜品</div>
              <div className="flex flex-wrap gap-1.5">
                {profile.recommendedDishes.map((dish, idx) => {
                  const dishName = typeof dish === 'string' ? dish : (dish as any)?.name || '特色菜'
                  return (
                    <span
                      key={idx}
                      className="px-2.5 py-1 rounded-full bg-zinc-100 text-zinc-800 text-xs font-medium border border-zinc-200/60"
                    >
                      {dishName}
                    </span>
                  )
                })}
              </div>
            </div>
          )}

          {/* Recommendation Summary Context */}
          {recommendation?.summary && (
            <div className="space-y-1.5">
              <div className="text-xs font-medium text-zinc-400 uppercase tracking-wider">本轮调研定论</div>
              <div className="p-3.5 rounded-xl bg-zinc-50 border border-zinc-200 text-xs text-zinc-700 leading-relaxed">
                {recommendation.summary}
              </div>
            </div>
          )}
        </div>

        {/* Drawer Footer */}
        <div className="p-4 border-t border-zinc-100 bg-white flex items-center gap-2.5">
          {onFollowUp && (
            <button
              onClick={() => {
                onFollowUp(shopName)
                onClose()
              }}
              className="flex-1 py-2 px-4 rounded-full bg-zinc-900 hover:bg-zinc-800 text-white text-xs font-medium transition-colors shadow-xs"
            >
              对此店追问
            </button>
          )}
          <button
            onClick={onClose}
            className="py-2 px-4 rounded-full bg-white border border-zinc-200 hover:bg-zinc-50 text-zinc-700 text-xs font-medium transition-colors"
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  )
}

