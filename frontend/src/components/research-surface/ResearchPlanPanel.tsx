import React, { useState } from 'react'
import {
  CheckCircle2,
  Clock,
  AlertTriangle,
  RefreshCw,
  XCircle,
  CornerDownRight,
  ChevronDown,
  ChevronUp,
  Layers,
} from 'lucide-react'
import type { ResearchPlanStepViewV1, ResearchStepStatusV1 } from '../../shared/contracts/research'

interface ResearchPlanPanelProps {
  plan: ResearchPlanStepViewV1[]
  currentPhase?: string
  metrics?: {
    evidenceItems?: number
    profiles?: number
    controversies?: number
    gaps?: number
  }
}

export function ResearchPlanPanel({ plan, currentPhase, metrics }: ResearchPlanPanelProps) {
  const [collapsed, setCollapsed] = useState<boolean>(false)

  if (!plan || plan.length === 0) {
    return (
      <div className="p-4 rounded-xl bg-slate-50 border border-slate-200/80 text-xs text-slate-500">
        <div className="flex items-center gap-2">
          <RefreshCw className="w-3.5 h-3.5 animate-spin text-orange-500" />
          <span>Agent 正在根据需求制定调查步骤...</span>
        </div>
      </div>
    )
  }

  const completedCount = plan.filter((s) => s.status === 'succeeded').length
  const progressPercent = Math.round((completedCount / plan.length) * 100)

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-xs">
      {/* Header */}
      <div className="flex items-center justify-between cursor-pointer" onClick={() => setCollapsed(!collapsed)}>
        <div className="flex items-center gap-2">
          <Layers className="w-4 h-4 text-orange-600" />
          <span className="font-semibold text-slate-900 text-xs">调查计划与进度</span>
          <span className="text-[11px] font-mono px-2 py-0.5 rounded-full bg-slate-100 text-slate-600">
            {completedCount}/{plan.length} 步骤 ({progressPercent}%)
          </span>
        </div>

        <div className="flex items-center gap-2">
          {currentPhase && (
            <span className="text-[11px] text-slate-500 hidden sm:inline">
              当前阶段：<span className="font-medium text-slate-800">{currentPhase}</span>
            </span>
          )}
          <button className="text-slate-400 hover:text-slate-600 p-0.5">
            {collapsed ? <ChevronDown className="w-4 h-4" /> : <ChevronUp className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {/* Progress Bar */}
      <div className="w-full bg-slate-100 h-1.5 rounded-full overflow-hidden mt-3 mb-1">
        <div
          className="bg-orange-500 h-full rounded-full transition-all duration-300"
          style={{ width: `${progressPercent}%` }}
        />
      </div>

      {/* Plan Steps List */}
      {!collapsed && (
        <div className="mt-3 pt-3 border-t border-slate-100 space-y-2">
          {plan.map((step, idx) => {
            let statusIcon = <Clock className="w-3.5 h-3.5 text-slate-300" />
            let stepBg = 'text-slate-500'

            if (step.status === 'succeeded') {
              statusIcon = <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
              stepBg = 'text-slate-800'
            } else if (step.status === 'running') {
              statusIcon = <RefreshCw className="w-3.5 h-3.5 text-orange-500 animate-spin" />
              stepBg = 'text-orange-950 font-medium bg-orange-50/50 p-2 rounded-lg'
            } else if (step.status === 'partial') {
              statusIcon = <AlertTriangle className="w-3.5 h-3.5 text-amber-500" />
              stepBg = 'text-amber-900'
            } else if (step.status === 'failed') {
              statusIcon = <XCircle className="w-3.5 h-3.5 text-rose-500" />
              stepBg = 'text-rose-900'
            }

            return (
              <div key={step.stepId || idx} className={`flex items-start gap-2.5 text-xs ${stepBg}`}>
                <div className="mt-0.5 flex-shrink-0">{statusIcon}</div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate">{step.label}</span>
                    {step.status === 'running' && (
                      <span className="text-[10px] uppercase font-mono text-orange-600 bg-orange-100/60 px-1.5 py-0.5 rounded">
                        进行中
                      </span>
                    )}
                  </div>
                  {step.detail && (
                    <div className="text-[11px] text-slate-400 mt-0.5 leading-snug">{step.detail}</div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
