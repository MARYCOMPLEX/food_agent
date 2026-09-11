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
      <div className="p-8 rounded-2xl border border-dashed border-zinc-200 bg-zinc-50/50 text-center">
        <div className="w-10 h-10 mx-auto rounded-full bg-zinc-100 flex items-center justify-center text-zinc-400 mb-2">
          <HelpCircle className="w-5 h-5" />
        </div>
        <p className="text-sm font-medium text-zinc-700">暂未发现相互冲突的评论争议</p>
        <p className="text-xs text-zinc-400 mt-1">当多方评论存在体验分歧时将在此自动提炼对比</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h3 className="font-semibold text-zinc-900 text-sm">评论争议与反例辨析</h3>
          <span className="text-xs font-mono px-2 py-0.5 rounded-full bg-zinc-100 text-zinc-600 border border-zinc-200/50">
            {controversies.length} 项焦点
          </span>
        </div>
        <span className="text-xs text-zinc-400">点击观点可定位原声评论</span>
      </div>

      <div className="grid grid-cols-1 gap-3">
        {controversies.map((item) => {
          const isExpanded = expandedControversies[item.controversyId] ?? true
          const sides = item.sides || []

          let statusBadge = {
            text: '仍有分歧',
            class: 'bg-amber-50 text-amber-700 border-amber-200/60',
            icon: AlertTriangle,
          }
          if (item.status === 'resolved') {
            statusBadge = {
              text: '已核清',
              class: 'bg-emerald-50 text-[#10a37f] border-emerald-200/60',
              icon: CheckCircle2,
            }
          } else if (item.status === 'partially_resolved') {
            statusBadge = {
              text: '部分核清',
              class: 'bg-zinc-100 text-zinc-700 border-zinc-200',
              icon: Clock,
            }
          }

          const StatusIcon = statusBadge.icon

          return (
            <div
              key={item.controversyId}
              className="rounded-2xl border border-zinc-200 bg-white p-4.5 shadow-2xs hover:border-zinc-300 transition-all"
            >
              {/* Header */}
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1">
                  <div className="flex items-center gap-2 flex-wrap mb-1">
                    <span
                      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium border ${statusBadge.class}`}
                    >
                      <StatusIcon className="w-3 h-3" />
                      {statusBadge.text}
                    </span>
                    {item.confidence !== undefined && item.confidence !== null && (
                      <span className="text-[11px] text-zinc-400 font-mono">
                        置信度: {Math.round(item.confidence * 100)}%
                      </span>
                    )}
                  </div>
                  <h4 className="font-semibold text-zinc-900 text-sm leading-snug">{item.topic}</h4>
                  {item.summary && (
                    <p className="text-xs text-zinc-500 mt-1 leading-relaxed">{item.summary}</p>
                  )}
                </div>

                <div className="flex items-center gap-2 flex-shrink-0">
                  {onVerifyControversy && (
                    <button
                      onClick={() => onVerifyControversy(item)}
                      className="inline-flex items-center gap-1 px-3 py-1.5 rounded-full bg-zinc-900 hover:bg-zinc-800 text-white text-xs font-medium transition-colors shadow-2xs"
                      title="就此争议追问"
                    >
                      <span>核实争议</span>
                      <ArrowRight className="w-3 h-3" />
                    </button>
                  )}
                  <button
                    onClick={() => toggleExpand(item.controversyId)}
                    className="p-1 rounded-lg text-zinc-400 hover:text-zinc-600 hover:bg-zinc-100 transition-colors"
                    aria-label={isExpanded ? '收起详情' : '展开详情'}
                  >
                    {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                  </button>
                </div>
              </div>

              {/* Collapsible Content */}
              {isExpanded && (
                <div className="mt-4 pt-3 border-t border-zinc-100 space-y-3">
                  {/* Two/Multi-sided View */}
                  {sides.length > 0 && (
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                      {sides.map((side, idx) => {
                        const sideEvidenceRefs = side.evidenceRefs || []
                        const sideEvidence = evidenceItems.filter((e) =>
                          sideEvidenceRefs.includes(e.evidenceId),
                        )

                        return (
                          <div
                            key={side.sideId || idx}
                            className="p-3 rounded-xl border border-zinc-200 bg-zinc-50/70 flex flex-col justify-between"
                          >
                            <div>
                              <div className="flex items-center justify-between mb-1.5">
                                <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-white border border-zinc-200 text-zinc-800">
                                  {side.label}
                                </span>
                                <span className="text-[11px] text-zinc-400 font-mono">
                                  {sideEvidenceRefs.length} 条依据
                                </span>
                              </div>
                              {side.summary && (
                                <p className="text-xs text-zinc-600 leading-relaxed mb-2">
                                  {side.summary}
                                </p>
                              )}
                            </div>

                            {/* Evidence Quote Excerpts */}
                            {sideEvidence.length > 0 && (
                              <div className="mt-2 pt-2 border-t border-zinc-200/60 space-y-1.5">
                                {sideEvidence.slice(0, 2).map((ev) => (
                                  <div
                                    key={ev.evidenceId}
                                    onClick={() => onSelectEvidence?.(ev.evidenceId)}
                                    className="text-[11px] text-zinc-700 bg-white p-2 rounded-lg border border-zinc-200/80 cursor-pointer hover:border-zinc-400 transition-colors flex items-start gap-1.5 shadow-2xs"
                                  >
                                    <MessageSquareQuote className="w-3 h-3 text-zinc-400 flex-shrink-0 mt-0.5" />
                                    <span className="line-clamp-2">“{ev.excerpt}”</span>
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
                    <div className="bg-zinc-50 p-3 rounded-xl border border-zinc-100 text-xs space-y-1.5">
                      {item.resolution && (
                        <div className="text-zinc-800 leading-relaxed">
                          <span className="font-medium text-zinc-900">综合研判：</span>
                          {item.resolution}
                        </div>
                      )}
                      {item.remainingQuestion && (
                        <div className="text-zinc-600 leading-relaxed flex items-start gap-1.5">
                          <HelpCircle className="w-3.5 h-3.5 text-zinc-400 flex-shrink-0 mt-0.5" />
                          <span>
                            <strong className="font-medium text-zinc-800">待核实问题：</strong>
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

