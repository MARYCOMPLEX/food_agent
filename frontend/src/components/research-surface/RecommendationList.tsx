import React, { useState } from 'react'
import {
  Sparkles,
  AlertTriangle,
  CheckCircle2,
  Bookmark,
  Layers,
  ArrowRight,
  ChevronDown,
  ChevronUp,
  Store,
  MapPin,
  TrendingUp,
  HelpCircle,
  Clock,
} from 'lucide-react'
import type {
  ResearchRecommendationViewV1,
  ResearchProfileViewV1,
  ResearchEvidenceItemV1,
  ResearchControversyViewV1,
} from '../../shared/contracts/research'
import type { Restaurant } from '../../shared/contracts'

interface RecommendationListProps {
  recommendations: ResearchRecommendationViewV1[]
  profiles?: ResearchProfileViewV1[]
  evidenceItems?: ResearchEvidenceItemV1[]
  controversies?: ResearchControversyViewV1[]
  favorites?: string[]
  onToggleFavorite?: (restaurantId: string, restaurantName: string) => void
  onSelectShopDetail?: (profile: ResearchProfileViewV1 | null, rec: ResearchRecommendationViewV1) => void
  onSelectForFollowUp?: (shopTitle: string) => void
  onAddToCompare?: (restaurant: Restaurant) => void
  comparedIds?: string[]
}

export function RecommendationList({
  recommendations,
  profiles = [],
  evidenceItems = [],
  controversies = [],
  favorites = [],
  onToggleFavorite,
  onSelectShopDetail,
  onSelectForFollowUp,
  onAddToCompare,
  comparedIds = [],
}: RecommendationListProps) {
  const [showFiltered, setShowFiltered] = useState<boolean>(false)

  // Segregate active recommendations vs filtered candidates
  const activeRecs = recommendations.filter((r) => r.status !== 'filtered')
  const filteredRecs = recommendations.filter((r) => r.status === 'filtered')

  if (!recommendations || recommendations.length === 0) {
    return (
      <div className="p-8 rounded-2xl border border-dashed border-slate-200 bg-slate-50/50 text-center">
        <div className="w-10 h-10 mx-auto rounded-full bg-slate-100 flex items-center justify-center text-slate-400 mb-2">
          <Sparkles className="w-5 h-5" />
        </div>
        <p className="text-sm font-medium text-slate-600">正在分析评论线索，提炼候选餐厅...</p>
        <p className="text-xs text-slate-400 mt-1">根据评论证据的一致性与排队、口味真实评价实时排序</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Active Recommendations */}
      <div className="space-y-4">
        {activeRecs.map((rec, index) => {
          const matchedProfile = profiles.find(
            (p) =>
              p.profileId === rec.profileRef ||
              p.name === rec.title ||
              (rec.entityRef && p.entityRef && p.entityRef.entityId === rec.entityRef.entityId),
          )

          const shopEvidenceCount = rec.evidenceRefs?.length || 0
          const shopControversyCount = rec.controversyRefs?.length || 0

          const isFavorite = favorites.includes(rec.recommendationId) || (matchedProfile && favorites.includes(matchedProfile.profileId))
          const isCompared = comparedIds.includes(rec.recommendationId)

          // Status Badge
          let statusBadge = {
            text: '重点推荐',
            class: 'bg-emerald-50 text-emerald-800 border-emerald-200',
            icon: CheckCircle2,
          }
          if (rec.status === 'candidate') {
            statusBadge = {
              text: '候选线索',
              class: 'bg-slate-100 text-slate-700 border-slate-200',
              icon: Clock,
            }
          } else if (rec.status === 'partial') {
            statusBadge = {
              text: '部分推荐 (资料补齐中)',
              class: 'bg-blue-50 text-blue-700 border-blue-200',
              icon: Clock,
            }
          }

          const StatusIcon = statusBadge.icon

          return (
            <div
              key={rec.recommendationId}
              className="rounded-2xl border border-slate-200 bg-white p-5 shadow-xs hover:shadow-md transition-all duration-200 relative group"
            >
              {/* Header: Rank + Title + Status + Confidence */}
              <div className="flex items-start justify-between gap-3 mb-2.5">
                <div className="flex items-start gap-3">
                  {/* Rank badge */}
                  <div className="w-8 h-8 rounded-xl bg-orange-500 text-white font-bold text-sm flex items-center justify-center flex-shrink-0 shadow-sm shadow-orange-500/20">
                    {rec.rank || index + 1}
                  </div>

                  <div>
                    <div className="flex items-center gap-2 flex-wrap mb-1">
                      <h4 className="font-bold text-slate-900 text-lg leading-tight hover:text-orange-600 transition-colors cursor-pointer"
                        onClick={() => onSelectShopDetail?.(matchedProfile || null, rec)}>
                        {rec.title}
                      </h4>
                      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium border ${statusBadge.class}`}>
                        <StatusIcon className="w-3 h-3" />
                        {statusBadge.text}
                      </span>
                      {rec.confidence !== undefined && rec.confidence !== null && (
                        <span className="text-[11px] text-slate-400 font-mono">
                          证据支撑度 {Math.round(rec.confidence * 100)}%
                        </span>
                      )}
                    </div>

                    {/* Address or Location hint from Dianping profile */}
                    {matchedProfile?.address && (
                      <div className="flex items-center gap-1 text-xs text-slate-500">
                        <MapPin className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />
                        <span className="line-clamp-1">{matchedProfile.address}</span>
                        {matchedProfile.averagePrice && (
                          <span className="text-orange-600 font-medium ml-1">· 人均 ￥{matchedProfile.averagePrice}</span>
                        )}
                      </div>
                    )}
                  </div>
                </div>

                {/* Top Actions: Bookmark, Compare */}
                <div className="flex items-center gap-1 flex-shrink-0">
                  {onAddToCompare && (
                    <button
                      onClick={() => {
                        const restaurantObj: Restaurant = {
                          id: rec.recommendationId,
                          name: rec.title,
                          oneLiner: rec.summary,
                          pros: rec.highlights,
                          cons: rec.warnings,
                          price: matchedProfile?.averagePrice ? String(matchedProfile.averagePrice) : undefined,
                          address: matchedProfile?.address || undefined,
                          hours: matchedProfile?.openingHours || undefined,
                        }
                        onAddToCompare(restaurantObj)
                      }}
                      className={`p-2 rounded-lg text-xs flex items-center gap-1 border transition-colors ${
                        isCompared
                          ? 'bg-orange-50 text-orange-700 border-orange-200'
                          : 'bg-slate-50 text-slate-600 border-slate-200 hover:bg-slate-100'
                      }`}
                      title={isCompared ? '已在对比栏中' : '加入对比'}
                    >
                      <Layers className="w-3.5 h-3.5" />
                      <span className="hidden sm:inline">{isCompared ? '已对比' : '对比'}</span>
                    </button>
                  )}

                  {onToggleFavorite && (
                    <button
                      onClick={() => onToggleFavorite(rec.recommendationId, rec.title)}
                      className={`p-2 rounded-lg border transition-colors ${
                        isFavorite
                          ? 'bg-amber-50 text-amber-600 border-amber-200'
                          : 'bg-slate-50 text-slate-400 border-slate-200 hover:text-amber-500 hover:bg-slate-100'
                      }`}
                      title={isFavorite ? '已收藏' : '收藏该店'}
                    >
                      <Bookmark className={`w-3.5 h-3.5 ${isFavorite ? 'fill-current' : ''}`} />
                    </button>
                  )}
                </div>
              </div>

              {/* One-Liner Conclusion */}
              {rec.summary && (
                <div className="bg-slate-50/80 p-3 rounded-xl border border-slate-100 text-slate-800 text-xs leading-relaxed mb-3">
                  <span className="font-semibold text-slate-900">核心评价：</span>
                  {rec.summary}
                </div>
              )}

              {/* Highlights (Pros) and Warnings (Cons) */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mb-3">
                {rec.highlights && rec.highlights.length > 0 && (
                  <div className="space-y-1">
                    {rec.highlights.map((h, i) => (
                      <div key={i} className="text-xs text-emerald-800 flex items-start gap-1.5 leading-snug">
                        <span className="text-emerald-500 font-bold">✓</span>
                        <span>{h}</span>
                      </div>
                    ))}
                  </div>
                )}

                {rec.warnings && rec.warnings.length > 0 && (
                  <div className="space-y-1">
                    {rec.warnings.map((w, i) => (
                      <div key={i} className="text-xs text-amber-800 flex items-start gap-1.5 leading-snug">
                        <AlertTriangle className="w-3.5 h-3.5 text-amber-500 flex-shrink-0 mt-0.5" />
                        <span>{w}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Card Footer: Evidence count, Controversy count, Detail & Follow-up Actions */}
              <div className="pt-3 border-t border-slate-100 flex items-center justify-between flex-wrap gap-2 text-xs">
                <div className="flex items-center gap-3 text-slate-500">
                  <span className="font-mono">{shopEvidenceCount} 条评论依据</span>
                  {shopControversyCount > 0 && (
                    <span className="text-amber-600 font-medium font-mono">
                      {shopControversyCount} 个未决争议
                    </span>
                  )}
                  {matchedProfile?.imageUrl && (
                    <span className="text-slate-400">含到店图片</span>
                  )}
                </div>

                <div className="flex items-center gap-2">
                  <button
                    onClick={() => onSelectShopDetail?.(matchedProfile || null, rec)}
                    className="px-2.5 py-1.5 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 font-medium transition-colors"
                  >
                    查看店铺档案
                  </button>

                  {onSelectForFollowUp && (
                    <button
                      onClick={() => onSelectForFollowUp(rec.title)}
                      className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-slate-900 hover:bg-orange-600 text-white font-medium transition-colors shadow-xs"
                    >
                      <span>针对该店追问</span>
                      <ArrowRight className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {/* Filtered Candidates Section (Collapsible - Section 16.1) */}
      {filteredRecs.length > 0 && (
        <div className="mt-6 pt-4 border-t border-slate-200">
          <button
            onClick={() => setShowFiltered(!showFiltered)}
            className="flex items-center justify-between w-full p-3 rounded-xl bg-slate-100/70 hover:bg-slate-100 text-slate-600 text-xs font-medium transition-colors"
          >
            <div className="flex items-center gap-2">
              <HelpCircle className="w-4 h-4 text-slate-400" />
              <span>为什么有 {filteredRecs.length} 家候选没有进入最终推荐？</span>
            </div>
            {showFiltered ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>

          {showFiltered && (
            <div className="mt-3 space-y-2 pl-2">
              {filteredRecs.map((fRec) => (
                <div
                  key={fRec.recommendationId}
                  className="p-3 rounded-xl border border-slate-200 bg-slate-50/50 text-xs"
                >
                  <div className="font-semibold text-slate-700">{fRec.title}</div>
                  <div className="text-slate-500 mt-1">
                    未入选原因：{fRec.summary || '因不满足硬限制（预算、排队超限或强负向反例证据）已过滤'}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
