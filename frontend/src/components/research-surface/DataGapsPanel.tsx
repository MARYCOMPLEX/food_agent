import React, { useState } from 'react'
import {
  AlertTriangle,
  RefreshCw,
  LogIn,
  CheckCircle2,
  HelpCircle,
  ShieldAlert,
  ChevronDown,
  ChevronUp,
} from 'lucide-react'
import type { ResearchGapViewV1 } from '../../shared/contracts/research'

interface DataGapsPanelProps {
  gaps: ResearchGapViewV1[]
  onRetryGap?: (gap: ResearchGapViewV1) => void
  onOpenLogin?: (platform: 'xhs_pc' | 'dianping') => void
}

export function DataGapsPanel({ gaps, onRetryGap, onOpenLogin }: DataGapsPanelProps) {
  const [retryingIds, setRetryingIds] = useState<Record<string, boolean>>({})

  const handleRetry = async (gap: ResearchGapViewV1) => {
    setRetryingIds((prev) => ({ ...prev, [gap.gapId]: true }))
    try {
      await onRetryGap?.(gap)
    } finally {
      setTimeout(() => {
        setRetryingIds((prev) => ({ ...prev, [gap.gapId]: false }))
      }, 1500)
    }
  }

  if (!gaps || gaps.length === 0) {
    return (
      <div className="p-4 rounded-xl bg-emerald-50/70 border border-emerald-200 text-emerald-800 text-xs flex items-center gap-2.5">
        <CheckCircle2 className="w-4 h-4 text-emerald-600 flex-shrink-0" />
        <span>调查数据源与链路完整，未出现阻断性缺口</span>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-amber-500" />
          <h4 className="font-semibold text-slate-800 text-xs">数据缺口与部分完成状态</h4>
          <span className="text-[11px] font-mono px-2 py-0.5 rounded-full bg-amber-50 text-amber-700 border border-amber-200">
            {gaps.length} 项需关注
          </span>
        </div>
        <span className="text-[11px] text-slate-400">已取得的评论证据不受缺口影响</span>
      </div>

      <div className="space-y-2.5">
        {gaps.map((gap) => {
          const isRetrying = retryingIds[gap.gapId] ?? false
          const isDianping = gap.source.toLowerCase().includes('dianping') || gap.operation.includes('profile')
          const isXhs = gap.source.toLowerCase().includes('xhs')

          // Severity styling
          let severityBadge = {
            label: '补充提示',
            class: 'bg-blue-50 text-blue-700 border-blue-200',
          }
          if (gap.severity === 'warning') {
            severityBadge = {
              label: '需关注',
              class: 'bg-amber-50 text-amber-700 border-amber-200',
            }
          } else if (gap.severity === 'error') {
            severityBadge = {
              label: '高影响缺口',
              class: 'bg-rose-50 text-rose-700 border-rose-200',
            }
          }

          const requiresLogin = gap.code.includes('auth') || gap.code.includes('verify') || gap.message.includes('登录') || gap.message.includes('验证')

          return (
            <div
              key={gap.gapId}
              className="p-3.5 rounded-xl border border-slate-200 bg-white shadow-xs flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs"
            >
              <div className="flex-1 space-y-1">
                <div className="flex items-center gap-2">
                  <span className={`px-2 py-0.5 rounded-md font-medium border text-[11px] ${severityBadge.class}`}>
                    {severityBadge.label}
                  </span>
                  <span className="font-medium text-slate-700">
                    {gap.source === 'dianping' ? '大众点评店铺资料补充' : gap.source === 'xhs_pc' ? '小红书评论采集' : gap.source}
                  </span>
                </div>

                <div className="text-slate-800 leading-relaxed font-normal">
                  {gap.message || '部分辅助数据未能顺利取得'}
                </div>

                {gap.affectedRefs && gap.affectedRefs.length > 0 && (
                  <div className="text-[11px] text-slate-400">
                    影响店铺：{gap.affectedRefs.map((r) => r.entityId).join(', ')}
                  </div>
                )}
              </div>

              {/* Action Buttons */}
              <div className="flex items-center gap-2 flex-shrink-0">
                {requiresLogin && onOpenLogin && (
                  <button
                    onClick={() => onOpenLogin(isDianping ? 'dianping' : 'xhs_pc')}
                    className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-orange-600 hover:bg-orange-700 text-white font-medium transition-colors shadow-xs"
                  >
                    <LogIn className="w-3.5 h-3.5" />
                    <span>重新认证账号</span>
                  </button>
                )}

                {gap.retryable !== false && onRetryGap && (
                  <button
                    disabled={isRetrying}
                    onClick={() => handleRetry(gap)}
                    className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 font-medium transition-colors disabled:opacity-50"
                  >
                    <RefreshCw className={`w-3.5 h-3.5 ${isRetrying ? 'animate-spin text-orange-600' : ''}`} />
                    <span>{isRetrying ? '重试中...' : isDianping ? '重试店铺资料' : '重试补充'}</span>
                  </button>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
