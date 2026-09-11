import React from 'react'
import {
  X,
  MapPin,
  Clock,
  Phone,
  Star,
  Tag,
  AlertCircle,
  ExternalLink,
  Utensils,
  CheckCircle2,
  Sparkles,
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
    <div className="fixed inset-0 z-50 flex justify-end bg-slate-900/40 backdrop-blur-xs animate-in fade-in">
      <div className="relative w-full max-w-lg h-full bg-white shadow-2xl flex flex-col overflow-hidden animate-in slide-in-from-right duration-200">
        {/* Drawer Header */}
        <div className="flex items-center justify-between p-5 border-b border-slate-100 bg-slate-50/50">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-xl bg-orange-100 text-orange-600 flex items-center justify-center font-bold">
              <Utensils className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-bold text-slate-900 text-lg leading-tight">{shopName}</h3>
              <div className="flex items-center gap-2 text-xs text-slate-500 mt-0.5">
                <span>大众点评补充档案</span>
                {profile?.updatedAt && (
                  <span className="font-mono text-[11px] text-slate-400">
                    更新于 {new Date(profile.updatedAt).toLocaleDateString()}
                  </span>
                )}
              </div>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
            aria-label="关闭抽屉"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Drawer Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {/* Completeness Badge */}
          {isPartial && (
            <div className="p-3 rounded-xl bg-amber-50 border border-amber-200 text-xs text-amber-800 flex items-start gap-2">
              <AlertCircle className="w-4 h-4 text-amber-600 flex-shrink-0 mt-0.5" />
              <div>
                <strong className="font-semibold">资料部分补齐：</strong>
                大众点评部分事实字段补充受限或需要交互验证，评论证据与主要结论保持有效。
              </div>
            </div>
          )}

          {isEnriched && (
            <div className="p-2.5 rounded-xl bg-emerald-50 border border-emerald-200 text-xs text-emerald-800 flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-600 flex-shrink-0" />
              <span>结构化事实档案完整（地址、人均、营业时间已核实）</span>
            </div>
          )}

          {/* Photos Carousel / Grid */}
          {profile?.images && profile.images.length > 0 ? (
            <div className="space-y-2">
              <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider">店铺实景与菜品</div>
              <div className="grid grid-cols-3 gap-2">
                {profile.images.slice(0, 3).map((img, i) => {
                  const url = typeof img === 'string' ? img : (img as any)?.url
                  return (
                    <div key={i} className="aspect-square rounded-xl bg-slate-100 overflow-hidden border border-slate-200">
                      {url ? (
                        <img src={url} alt={`${shopName} 图 ${i + 1}`} className="w-full h-full object-cover" />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center text-slate-400 text-xs">无图</div>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          ) : null}

          {/* Key Facts: Address, Hours, Price, Phone */}
          <div className="bg-slate-50 p-4 rounded-2xl border border-slate-100 space-y-3 text-xs">
            {/* Address */}
            <div className="flex items-start gap-2.5">
              <MapPin className="w-4 h-4 text-slate-400 flex-shrink-0 mt-0.5" />
              <div>
                <div className="font-semibold text-slate-700">门店地址</div>
                <div className="text-slate-900 mt-0.5">{profile?.address || '大众点评暂未提供详细地址'}</div>
                {profile?.businessArea && (
                  <div className="text-slate-500 text-[11px] mt-0.5">商圈：{profile.businessArea}</div>
                )}
              </div>
            </div>

            {/* Hours */}
            <div className="flex items-start gap-2.5">
              <Clock className="w-4 h-4 text-slate-400 flex-shrink-0 mt-0.5" />
              <div>
                <div className="font-semibold text-slate-700">营业时间</div>
                <div className="text-slate-900 mt-0.5">{profile?.openingHours || '暂无准确营业时间（请到店前电话确认）'}</div>
              </div>
            </div>

            {/* Price & Rating */}
            <div className="flex items-start gap-2.5">
              <Star className="w-4 h-4 text-amber-500 flex-shrink-0 mt-0.5" />
              <div>
                <div className="font-semibold text-slate-700">大众点评评分与人均</div>
                <div className="text-slate-900 mt-0.5 flex items-center gap-3">
                  <span>评分：{profile?.rating ? `${profile.rating} 分` : '暂无'}</span>
                  <span>人均：{profile?.averagePrice ? `￥${profile.averagePrice}` : '暂未录入'}</span>
                  {profile?.reviewCount && (
                    <span className="text-slate-400 text-[11px]">{profile.reviewCount} 条点评</span>
                  )}
                </div>
              </div>
            </div>

            {/* Phone */}
            {profile?.phone && (
              <div className="flex items-start gap-2.5">
                <Phone className="w-4 h-4 text-slate-400 flex-shrink-0 mt-0.5" />
                <div>
                  <div className="font-semibold text-slate-700">联系电话</div>
                  <div className="text-slate-900 mt-0.5 font-mono">{profile.phone}</div>
                </div>
              </div>
            )}
          </div>

          {/* Recommended Dishes */}
          {profile?.recommendedDishes && profile.recommendedDishes.length > 0 && (
            <div className="space-y-2">
              <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider">高频推荐菜品</div>
              <div className="flex flex-wrap gap-2">
                {profile.recommendedDishes.map((dish, idx) => {
                  const dishName = typeof dish === 'string' ? dish : (dish as any)?.name || '特色菜'
                  return (
                    <span
                      key={idx}
                      className="px-3 py-1.5 rounded-xl bg-orange-50 text-orange-800 text-xs font-medium border border-orange-100"
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
            <div className="space-y-2">
              <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider">本轮调查综合评定</div>
              <div className="p-4 rounded-xl bg-white border border-slate-200 text-xs text-slate-800 leading-relaxed shadow-xs">
                {recommendation.summary}
              </div>
            </div>
          )}
        </div>

        {/* Drawer Footer */}
        <div className="p-4 border-t border-slate-100 bg-slate-50 flex items-center gap-3">
          {onFollowUp && (
            <button
              onClick={() => {
                onFollowUp(shopName)
                onClose()
              }}
              className="flex-1 py-2.5 px-4 rounded-xl bg-slate-900 hover:bg-orange-600 text-white text-xs font-semibold transition-colors flex items-center justify-center gap-1.5 shadow-sm"
            >
              <span>针对 {shopName} 继续提问</span>
            </button>
          )}
          <button
            onClick={onClose}
            className="py-2.5 px-4 rounded-xl bg-white border border-slate-200 hover:bg-slate-100 text-slate-700 text-xs font-medium transition-colors"
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  )
}
