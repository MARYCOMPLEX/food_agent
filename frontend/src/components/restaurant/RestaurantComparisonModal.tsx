import React from 'react'
import { X, Check, AlertTriangle, HelpCircle, Star, Sparkles } from 'lucide-react'
import type { Restaurant } from '../../shared/contracts'

interface RestaurantComparisonModalProps {
  isOpen: boolean
  restaurants: Restaurant[]
  onClose: () => void
  onRemoveRestaurant?: (id: string) => void
  onSelectForFollowUp?: (restaurant: Restaurant) => void
}

export function RestaurantComparisonModal({
  isOpen,
  restaurants,
  onClose,
  onRemoveRestaurant,
  onSelectForFollowUp,
}: RestaurantComparisonModalProps) {
  if (!isOpen || restaurants.length === 0) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-in fade-in">
      <div className="relative w-full max-w-5xl max-h-[90vh] bg-white rounded-2xl shadow-2xl border border-slate-100 flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 bg-slate-50/50">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-orange-100 text-orange-600 flex items-center justify-center">
              <Sparkles className="w-4 h-4" />
            </div>
            <div>
              <h3 className="font-semibold text-slate-900 text-lg">候选餐厅深度多维对比</h3>
              <p className="text-xs text-slate-500">基于真实评论证据、争议焦点与店铺结构化档案多维对比</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
            aria-label="关闭"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Table Content */}
        <div className="overflow-x-auto overflow-y-auto flex-1 p-6">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr>
                <th className="w-36 p-3 text-left font-medium text-slate-400 border-b border-slate-200">
                  对比维度
                </th>
                {restaurants.map((shop) => (
                  <th key={shop.id} className="p-3 text-left border-b border-slate-200 min-w-[200px]">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <div className="font-semibold text-slate-900 text-base">{shop.name}</div>
                        <div className="text-xs text-orange-600 font-normal mt-0.5">
                          {shop.price ? `人均 ￥${shop.price}` : '人均: 未知'}
                        </div>
                      </div>
                      {onRemoveRestaurant && (
                        <button
                          onClick={() => onRemoveRestaurant(shop.id)}
                          className="text-slate-300 hover:text-slate-500 p-1"
                          title="从对比中移除"
                        >
                          <X className="w-4 h-4" />
                        </button>
                      )}
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {/* 核心结论 */}
              <tr className="hover:bg-slate-50/50">
                <td className="p-3 font-medium text-slate-500 bg-slate-50/30">核心结论</td>
                {restaurants.map((shop) => (
                  <td key={shop.id} className="p-3 text-slate-700 leading-relaxed text-xs">
                    {shop.oneLiner || '正在整理该店评论结论'}
                  </td>
                ))}
              </tr>

              {/* 口味与特色 */}
              <tr className="hover:bg-slate-50/50">
                <td className="p-3 font-medium text-slate-500 bg-slate-50/30">口味与一致性</td>
                {restaurants.map((shop) => (
                  <td key={shop.id} className="p-3 text-xs">
                    {shop.pros && shop.pros.length > 0 ? (
                      <ul className="space-y-1">
                        {shop.pros.map((p, i) => (
                          <li key={i} className="text-emerald-700 flex items-start gap-1">
                            <span className="text-emerald-500 font-bold">✓</span>
                            <span>{p}</span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <span className="text-slate-400">未知</span>
                    )}
                  </td>
                ))}
              </tr>

              {/* 主要争议与风险 */}
              <tr className="hover:bg-slate-50/50">
                <td className="p-3 font-medium text-slate-500 bg-slate-50/30">风险 / 争议点</td>
                {restaurants.map((shop) => (
                  <td key={shop.id} className="p-3 text-xs">
                    {shop.cons && shop.cons.length > 0 ? (
                      <ul className="space-y-1">
                        {shop.cons.map((c, i) => (
                          <li key={i} className="text-amber-700 flex items-start gap-1">
                            <AlertTriangle className="w-3.5 h-3.5 text-amber-500 flex-shrink-0 mt-0.5" />
                            <span>{c}</span>
                          </li>
                        ))}
                      </ul>
                    ) : shop.warning ? (
                      <div className="text-amber-700 flex items-start gap-1">
                        <AlertTriangle className="w-3.5 h-3.5 text-amber-500 flex-shrink-0 mt-0.5" />
                        <span>{shop.warning}</span>
                      </div>
                    ) : (
                      <span className="text-slate-400">暂无强争议</span>
                    )}
                  </td>
                ))}
              </tr>

              {/* 排队与到店成本 */}
              <tr className="hover:bg-slate-50/50">
                <td className="p-3 font-medium text-slate-500 bg-slate-50/30">排队与耗时</td>
                {restaurants.map((shop) => (
                  <td key={shop.id} className="p-3 text-xs text-slate-700">
                    {shop.stats?.wait || '未知（等待评论进一步核清）'}
                  </td>
                ))}
              </tr>

              {/* 必点推荐 */}
              <tr className="hover:bg-slate-50/50">
                <td className="p-3 font-medium text-slate-500 bg-slate-50/30">高频认可菜品</td>
                {restaurants.map((shop) => (
                  <td key={shop.id} className="p-3 text-xs">
                    {shop.mustTry && shop.mustTry.length > 0 ? (
                      <div className="flex flex-wrap gap-1.5">
                        {shop.mustTry.map((item, idx) => (
                          <span
                            key={idx}
                            className="inline-flex items-center px-2 py-0.5 rounded-md bg-orange-50 text-orange-700 text-[11px]"
                          >
                            {item.name}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <span className="text-slate-400">未知</span>
                    )}
                  </td>
                ))}
              </tr>

              {/* 到店地址与资料 */}
              <tr className="hover:bg-slate-50/50">
                <td className="p-3 font-medium text-slate-500 bg-slate-50/30">到店信息</td>
                {restaurants.map((shop) => (
                  <td key={shop.id} className="p-3 text-xs text-slate-600">
                    <div>{shop.address || '地址待点评补充'}</div>
                    <div className="text-slate-400 mt-1">{shop.hours || '营业时间待核实'}</div>
                  </td>
                ))}
              </tr>

              {/* 操作栏 */}
              <tr>
                <td className="p-3 bg-slate-50/30"></td>
                {restaurants.map((shop) => (
                  <td key={shop.id} className="p-3">
                    <button
                      onClick={() => {
                        onSelectForFollowUp?.(shop)
                        onClose()
                      }}
                      className="w-full py-1.5 px-3 rounded-lg bg-slate-900 text-white text-xs font-medium hover:bg-orange-600 transition-colors"
                    >
                      针对该店追问
                    </button>
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
