import React from 'react'
import { X, AlertTriangle, Sparkles } from 'lucide-react'
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
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-xs animate-in fade-in">
      <div className="relative w-full max-w-5xl max-h-[90vh] bg-white rounded-2xl shadow-2xl border border-zinc-200 flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-zinc-100">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-full bg-zinc-100 text-zinc-800 flex items-center justify-center">
              <Sparkles className="w-4 h-4 text-[#10a37f]" />
            </div>
            <div>
              <h3 className="font-semibold text-zinc-900 text-base">候选餐厅多维横向对比</h3>
              <p className="text-xs text-zinc-500">基于真实评论证据、排队耗时与店铺档案</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-lg text-zinc-400 hover:text-zinc-600 hover:bg-zinc-100 transition-colors"
            aria-label="关闭"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Table Content */}
        <div className="overflow-x-auto overflow-y-auto flex-1 p-6">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr>
                <th className="w-36 p-3 text-left font-medium text-zinc-400 border-b border-zinc-200 text-xs uppercase tracking-wider">
                  对比维度
                </th>
                {restaurants.map((shop) => (
                  <th key={shop.id} className="p-3 text-left border-b border-zinc-200 min-w-[220px]">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <div className="font-semibold text-zinc-900 text-base">{shop.name}</div>
                        <div className="text-xs font-mono text-[#10a37f] mt-0.5">
                          {shop.price ? `人均 ￥${shop.price}` : '人均未知'}
                        </div>
                      </div>
                      {onRemoveRestaurant && (
                        <button
                          onClick={() => onRemoveRestaurant(shop.id)}
                          className="text-zinc-300 hover:text-zinc-600 p-1 rounded-md transition-colors"
                          title="从对比中移除"
                        >
                          <X className="w-3.5 h-3.5" />
                        </button>
                      )}
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100">
              {/* 核心结论 */}
              <tr className="hover:bg-zinc-50/60 transition-colors">
                <td className="p-3 font-medium text-zinc-500 bg-zinc-50/40 text-xs">核心评价结论</td>
                {restaurants.map((shop) => (
                  <td key={shop.id} className="p-3 text-zinc-700 leading-relaxed text-xs">
                    {shop.oneLiner || '正在整理该店口碑结论'}
                  </td>
                ))}
              </tr>

              {/* 口味与特色 */}
              <tr className="hover:bg-zinc-50/60 transition-colors">
                <td className="p-3 font-medium text-zinc-500 bg-zinc-50/40 text-xs">口味亮点</td>
                {restaurants.map((shop) => (
                  <td key={shop.id} className="p-3 text-xs">
                    {shop.pros && shop.pros.length > 0 ? (
                      <ul className="space-y-1">
                        {shop.pros.map((p, i) => (
                          <li key={i} className="text-zinc-800 flex items-start gap-1.5">
                            <span className="text-[#10a37f] font-bold">✓</span>
                            <span>{p}</span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <span className="text-zinc-400">未知</span>
                    )}
                  </td>
                ))}
              </tr>

              {/* 主要争议与风险 */}
              <tr className="hover:bg-zinc-50/60 transition-colors">
                <td className="p-3 font-medium text-zinc-500 bg-zinc-50/40 text-xs">避雷与争议点</td>
                {restaurants.map((shop) => (
                  <td key={shop.id} className="p-3 text-xs">
                    {shop.cons && shop.cons.length > 0 ? (
                      <ul className="space-y-1">
                        {shop.cons.map((c, i) => (
                          <li key={i} className="text-amber-900 flex items-start gap-1.5">
                            <AlertTriangle className="w-3.5 h-3.5 text-amber-500 flex-shrink-0 mt-0.5" />
                            <span>{c}</span>
                          </li>
                        ))}
                      </ul>
                    ) : shop.warning ? (
                      <div className="text-amber-900 flex items-start gap-1.5">
                        <AlertTriangle className="w-3.5 h-3.5 text-amber-500 flex-shrink-0 mt-0.5" />
                        <span>{shop.warning}</span>
                      </div>
                    ) : (
                      <span className="text-zinc-400">暂无强争议</span>
                    )}
                  </td>
                ))}
              </tr>

              {/* 排队与耗时 */}
              <tr className="hover:bg-zinc-50/60 transition-colors">
                <td className="p-3 font-medium text-zinc-500 bg-zinc-50/40 text-xs">排队与耗时</td>
                {restaurants.map((shop) => (
                  <td key={shop.id} className="p-3 text-xs text-zinc-700">
                    {shop.stats?.wait || '待评论进一步核实'}
                  </td>
                ))}
              </tr>

              {/* 必点推荐 */}
              <tr className="hover:bg-zinc-50/60 transition-colors">
                <td className="p-3 font-medium text-zinc-500 bg-zinc-50/40 text-xs">高频招牌菜</td>
                {restaurants.map((shop) => (
                  <td key={shop.id} className="p-3 text-xs">
                    {shop.mustTry && shop.mustTry.length > 0 ? (
                      <div className="flex flex-wrap gap-1.5">
                        {shop.mustTry.map((item, idx) => (
                          <span
                            key={idx}
                            className="inline-flex items-center px-2.5 py-0.5 rounded-full bg-zinc-100 text-zinc-800 text-[11px] border border-zinc-200/50"
                          >
                            {item.name}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <span className="text-zinc-400">未知</span>
                    )}
                  </td>
                ))}
              </tr>

              {/* 到店地址与资料 */}
              <tr className="hover:bg-zinc-50/60 transition-colors">
                <td className="p-3 font-medium text-zinc-500 bg-zinc-50/40 text-xs">地址与营业时间</td>
                {restaurants.map((shop) => (
                  <td key={shop.id} className="p-3 text-xs text-zinc-600">
                    <div>{shop.address || '地址待点评补充'}</div>
                    <div className="text-zinc-400 mt-0.5">{shop.hours || '营业时间待核实'}</div>
                  </td>
                ))}
              </tr>

              {/* 操作栏 */}
              <tr>
                <td className="p-3 bg-zinc-50/40"></td>
                {restaurants.map((shop) => (
                  <td key={shop.id} className="p-3">
                    <button
                      onClick={() => {
                        onSelectForFollowUp?.(shop)
                        onClose()
                      }}
                      className="w-full py-2 px-4 rounded-full bg-zinc-900 text-white text-xs font-medium hover:bg-zinc-800 transition-colors shadow-xs"
                    >
                      对此店追问
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

