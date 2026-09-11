import React, { useState } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  HelpCircle,
  Clock,
  ArrowRight,
  MessageSquareQuote,
  ChevronDown,
  ChevronUp,
} from 'lucide-react'
import type { ResearchControversyViewV1, ResearchEvidenceItemV1 } from '../../shared/contracts/research'

interface ControversyPanelProps {
  controversies: ResearchControversyViewV1[]
  evidenceItems?: ResearchEvidenceItemV1[]
  onVerifyControversy?: (controversy: ResearchControversyViewV1) => void
  onSelectEvidence?: (evidenceId: string) => void
}

export function ControversyPanel({
  controversies,
  evidenceItems = [],
  onVerifyControversy,
  onSelectEvidence,
}: ControversyPanelProps) {
  const [expandedControversies, setExpandedControversies] = useState<Record<string, boolean>>({})

  const toggleExpand = (id: string) => {
    setExpandedControversies((prev) => ({
      ...prev,
      [id]: !prev[id],
    }))
  }

  if (!controversies || controversies.length === 0) {
    return (
      <div className="p-8 rounded-2xl border border-dashed border-slate-200 bg-slate-50/50 text-center">
        <div className="w-10 h-10 mx-auto rounded-full bg-slate-100 flex items-center justify-center text-slate-400 mb-2">
          <HelpCircle className="w-5 h-5" />
        </div>
        <p className="text-sm font-medium text-slate-600">暂未发现相互冲突的评论争议</p>
        <p className="text-xs text-slate-400 mt-1">当评论区针对同一餐厅或体验存在矛盾评价时，系统将在此处自动提炼对比</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-amber-500" />
          <h3 className="font-semibold text-slate-900 text-sm">评论争议与反例辨析</h3>
          <span className="text-xs font-mono px-2 py-0.5 rounded-full bg-amber-50 text-amber-700 border border-amber-200">
            {controversies.length} 项焦点
          </span>
        </div>
        <span className="text-xs text-slate-400">点击观点可定位支撑评论</span>
      </div>

      <div className="grid grid-cols-1 gap-4">
        {controversies.map((item) => {
          const isExpanded = expandedControversies[item.controversyId] ?? true
          const sides = item.sides || []

          let statusBadge = {
            text: '仍有分歧',
            class: 'bg-amber-50 text-amber-700 border-amber-200',
            icon: AlertTriangle,
          }
          if (item.status === 'resolved') {
            statusBadge = {
              text: '已核清',
              class: 'bg-emerald-50 text-emerald-700 border-emerald-200',
              icon: CheckCircle2,
            }
          } else if (item.status === 'partially_resolved') {
            statusBadge = {
              text: '部分核清',
              class: 'bg-blue-50 text-blue-700 border-blue-200',
              icon: Clock,
            }
          }

          const StatusIcon = statusBadge.icon

          return (
            <div
              key={item.controversyId}
              className="rounded-2xl border border-slate-200/90 bg-white p-5 shadow-sm hover:shadow transition-shadow"
            >
              {/* Header */}
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1">
                  <div className="flex items-center gap-2 flex-wrap mb-1">
                    <span
                      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium border ${statusBadge.class}`}
                    >
                      <StatusIcon className="w-3.5 h-3.5" />
                      {statusBadge.text}
                    </span>
                    {item.confidence !== undefined && item.confidence !== null && (
                      <span className="text-[11px] text-slate-400 font-mono">
                        证据支撑度: {Math.round(item.confidence * 100)}%
                      </span>
                    )}
                  </div>
                  <h4 className="font-semibold text-slate-900 text-base leading-snug">{item.topic}</h4>
                  {item.summary && (
                    <p className="text-xs text-slate-500 mt-1 leading-relaxed">{item.summary}</p>
                  )}
                </div>

                <div className="flex items-center gap-2 flex-shrink-0">
                  {onVerifyControversy && (
                    <button
                      onClick={() => onVerifyControversy(item)}
                      className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-orange-50 text-orange-700 hover:bg-orange-100 text-xs font-medium transition-colors"
                      title="就此争议向 Agent 追问核实"
                    >
                      <span>核实此争议</span>
                      <ArrowRight className="w-3.5 h-3.5" />
                    </button>
                  )}
                  <button
                    onClick={() => toggleExpand(item.controversyId)}
                    className="p-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
                    aria-label={isExpanded ? '收起详情' : '展开详情'}
                  >
                    {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                  </button>
                </div>
              </div>

              {/* Collapsible Content */}
              {isExpanded && (
                <div className="mt-4 pt-4 border-t border-slate-100 space-y-3">
                  {/* Two/Multi-sided View */}
                  {sides.length > 0 && (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      {sides.map((side, idx) => {
                        const sideEvidenceRefs = side.evidenceRefs || []
                        const sideEvidence = evidenceItems.filter((e) =>
                          sideEvidenceRefs.includes(e.evidenceId),
                        )

                        const bgBorder =
                          idx === 0
                            ? 'bg-orange-50/40 border-orange-200/80 text-orange-950'
                            : 'bg-indigo-50/40 border-indigo-200/80 text-indigo-950'
                        const tagColor =
                          idx === 0
                            ? 'bg-orange-100/80 text-orange-800'
                            : 'bg-indigo-100/80 text-indigo-800'

                        return (
                          <div
                            key={side.sideId || idx}
                            className={`p-3.5 rounded-xl border ${bgBorder} flex flex-col justify-between`}
                          >
                            <div>
                              <div className="flex items-center justify-between mb-1.5">
                                <span className={`text-xs font-semibold px-2 py-0.5 rounded-md ${tagColor}`}>
                                  {side.label}
                                </span>
                                <span className="text-[11px] text-slate-400 font-mono">
                                  {sideEvidenceRefs.length} 条依据
                                </span>
                              </div>
                              {side.summary && (
                                <p className="text-xs text-slate-700 leading-relaxed mb-2">
                                  {side.summary}
                                </p>
                              )}
                            </div>

                            {/* Evidence Quote Excerpts */}
                            {sideEvidence.length > 0 && (
                              <div className="mt-2 pt-2 border-t border-slate-200/50 space-y-1.5">
                                {sideEvidence.slice(0, 2).map((ev) => (
                                  <div
                                    key={ev.evidenceId}
                                    onClick={() => onSelectEvidence?.(ev.evidenceId)}
                                    className="text-[11px] text-slate-600 bg-white/80 p-2 rounded-lg border border-slate-200/60 cursor-pointer hover:border-orange-300 transition-colors flex items-start gap-1.5"
                                  >
                                    <MessageSquareQuote className="w-3 h-3 text-slate-400 flex-shrink-0 mt-0.5" />
                                    <span className="line-clamp-2 italic">“{ev.excerpt}”</span>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  )}

                  {/* Resolution & Remaining Questions */}
                  {(item.resolution || item.remainingQuestion) && (
                    <div className="bg-slate-50 p-3.5 rounded-xl border border-slate-100 text-xs space-y-1.5">
                      {item.resolution && (
                        <div className="text-slate-800 leading-relaxed">
                          <span className="font-semibold text-slate-900">综合研判：</span>
                          {item.resolution}
                        </div>
                      )}
                      {item.remainingQuestion && (
                        <div className="text-amber-800 leading-relaxed flex items-start gap-1.5">
                          <HelpCircle className="w-3.5 h-3.5 text-amber-500 flex-shrink-0 mt-0.5" />
                          <span>
                            <strong className="font-semibold">尚待核实：</strong>
                            {item.remainingQuestion}
                          </span>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
