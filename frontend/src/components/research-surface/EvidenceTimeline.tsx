import React, { useState, useMemo } from 'react'
import {
  MessageSquare,
  Search,
  Filter,
  CheckCircle2,
  AlertCircle,
  Clock,
  Sparkles,
  ExternalLink,
  ChevronDown,
  ChevronUp,
} from 'lucide-react'
import type {
  ResearchEvidenceItemV1,
  EvidenceStanceV1,
  ResearchRecommendationViewV1,
} from '../../shared/contracts/research'

interface EvidenceTimelineProps {
  evidenceItems: ResearchEvidenceItemV1[]
  recommendations?: ResearchRecommendationViewV1[]
  selectedEvidenceId?: string | null
  onSelectShop?: (shopName: string) => void
  onFocusEvidence?: (evidenceId: string) => void
}

export function EvidenceTimeline({
  evidenceItems,
  recommendations = [],
  selectedEvidenceId,
  onSelectShop,
  onFocusEvidence,
}: EvidenceTimelineProps) {
  const [stanceFilter, setStanceFilter] = useState<string>('all')
  const [sourceFilter, setSourceFilter] = useState<string>('all')
  const [searchQuery, setSearchQuery] = useState<string>('')
  const [expandedItems, setExpandedItems] = useState<Record<string, boolean>>({})

  const toggleItemExpand = (id: string) => {
    setExpandedItems((prev) => ({
      ...prev,
      [id]: !prev[id],
    }))
  }

  // Filtered evidence items
  const filteredEvidence = useMemo(() => {
    return evidenceItems.filter((ev) => {
      if (stanceFilter !== 'all' && ev.stance !== stanceFilter) return false
      if (sourceFilter !== 'all') {
        const src = (ev.source || '').toLowerCase()
        if (sourceFilter === 'xhs' && !src.includes('xhs')) return false
        if (sourceFilter === 'dianping' && !src.includes('dianping') && !src.includes('dp')) return false
      }
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase()
        const excerpt = (ev.excerpt || '').toLowerCase()
        const title = (ev.title || '').toLowerCase()
        if (!excerpt.includes(q) && !title.includes(q)) return false
      }
      return true
    })
  }, [evidenceItems, stanceFilter, sourceFilter, searchQuery])

  // Count by stance
  const stanceCounts = useMemo(() => {
    const counts = { all: evidenceItems.length, positive: 0, negative: 0, mixed: 0, neutral: 0 }
    for (const ev of evidenceItems) {
      if (ev.stance && ev.stance in counts) {
        counts[ev.stance as keyof typeof counts]++
      }
    }
    return counts
  }, [evidenceItems])

  if (!evidenceItems || evidenceItems.length === 0) {
    return (
      <div className="p-8 rounded-2xl border border-dashed border-slate-200 bg-slate-50/50 text-center">
        <div className="w-10 h-10 mx-auto rounded-full bg-slate-100 flex items-center justify-center text-slate-400 mb-2">
          <MessageSquare className="w-5 h-5" />
        </div>
        <p className="text-sm font-medium text-slate-600">正在从小红书评论中搜集第一批真实体验证据...</p>
        <p className="text-xs text-slate-400 mt-1">首条有效评论产生后将立即在此呈现，无需等待整轮调查结束</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Header with Title & Filter Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-white p-3.5 rounded-2xl border border-slate-200/90 shadow-sm">
        <div className="flex items-center gap-2">
          <MessageSquare className="w-4 h-4 text-orange-600" />
          <h3 className="font-semibold text-slate-900 text-sm">评论真实证据库</h3>
          <span className="text-xs font-mono px-2 py-0.5 rounded-full bg-slate-100 text-slate-700">
            {filteredEvidence.length} / {evidenceItems.length} 条
          </span>
        </div>

        {/* Filters */}
        <div className="flex items-center gap-2 flex-wrap">
          {/* Stance Buttons */}
          <div className="flex items-center rounded-lg bg-slate-100 p-0.5 text-xs font-medium">
            <button
              onClick={() => setStanceFilter('all')}
              className={`px-2.5 py-1 rounded-md transition-colors ${stanceFilter === 'all' ? 'bg-white text-slate-900 shadow-xs' : 'text-slate-500 hover:text-slate-800'}`}
            >
              全部 ({stanceCounts.all})
            </button>
            <button
              onClick={() => setStanceFilter('positive')}
              className={`px-2.5 py-1 rounded-md transition-colors ${stanceFilter === 'positive' ? 'bg-white text-emerald-700 shadow-xs' : 'text-slate-500 hover:text-slate-800'}`}
            >
              正向 ({stanceCounts.positive})
            </button>
            <button
              onClick={() => setStanceFilter('negative')}
              className={`px-2.5 py-1 rounded-md transition-colors ${stanceFilter === 'negative' ? 'bg-white text-rose-700 shadow-xs' : 'text-slate-500 hover:text-slate-800'}`}
            >
              负向/反例 ({stanceCounts.negative})
            </button>
            <button
              onClick={() => setStanceFilter('mixed')}
              className={`px-2.5 py-1 rounded-md transition-colors ${stanceFilter === 'mixed' ? 'bg-white text-amber-700 shadow-xs' : 'text-slate-500 hover:text-slate-800'}`}
            >
              分歧 ({stanceCounts.mixed})
            </button>
          </div>

          {/* Search Box */}
          <div className="relative">
            <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              placeholder="搜索评论内容..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-8 pr-3 py-1 bg-slate-50 hover:bg-slate-100 focus:bg-white border border-slate-200 rounded-lg text-xs text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-orange-500 transition-all w-36 sm:w-44"
            />
          </div>
        </div>
      </div>

      {/* Evidence List */}
      <div className="space-y-3">
        {filteredEvidence.map((ev, idx) => {
          const isSelected = selectedEvidenceId === ev.evidenceId
          const isExpanded = expandedItems[ev.evidenceId] ?? false
          const isLongExcerpt = (ev.excerpt || '').length > 180

          // Stance styling
          let stanceTag = {
            label: '中立事实',
            class: 'bg-slate-100 text-slate-700 border-slate-200',
          }
          if (ev.stance === 'positive') {
            stanceTag = {
              label: '正向好评',
              class: 'bg-emerald-50 text-emerald-700 border-emerald-200',
            }
          } else if (ev.stance === 'negative') {
            stanceTag = {
              label: '负向踩雷',
              class: 'bg-rose-50 text-rose-700 border-rose-200',
            }
          } else if (ev.stance === 'mixed') {
            stanceTag = {
              label: '毁誉参半',
              class: 'bg-amber-50 text-amber-700 border-amber-200',
            }
          }

          const platformLabel = (ev.source || '').toLowerCase().includes('xhs')
            ? '小红书笔记评论'
            : (ev.source || '').toLowerCase().includes('dianping')
            ? '大众点评真实口碑'
            : ev.source || '公开采集源'

          return (
            <div
              key={ev.evidenceId || idx}
              id={`evidence-${ev.evidenceId}`}
              className={`rounded-2xl border bg-white p-4.5 transition-all ${
                isSelected
                  ? 'border-orange-500 ring-2 ring-orange-200/50 shadow-md'
                  : 'border-slate-200/90 shadow-sm hover:border-slate-300'
              }`}
            >
              {/* Card Header: Source, Stance, Time */}
              <div className="flex items-center justify-between gap-2 mb-2 flex-wrap text-xs">
                <div className="flex items-center gap-2">
                  <span className="inline-flex items-center px-2 py-0.5 rounded-md bg-orange-50 text-orange-700 font-medium border border-orange-100">
                    {platformLabel}
                  </span>
                  <span className={`inline-flex items-center px-2 py-0.5 rounded-md border font-medium ${stanceTag.class}`}>
                    {stanceTag.label}
                  </span>
                  {ev.confidence !== undefined && ev.confidence !== null && (
                    <span className="text-slate-400 font-mono text-[11px]">
                      可信度: {Math.round(ev.confidence * 100)}%
                    </span>
                  )}
                </div>

                <div className="flex items-center gap-2 text-slate-400 text-[11px]">
                  {ev.capturedAt && (
                    <span className="flex items-center gap-1 font-mono">
                      <Clock className="w-3 h-3" />
                      {new Date(ev.capturedAt).toLocaleDateString()}
                    </span>
                  )}
                  {ev.commentRef && (
                    <span className="font-mono text-slate-300">#{ev.commentRef.slice(0, 8)}</span>
                  )}
                </div>
              </div>

              {/* Note / Context Title */}
              {ev.title && (
                <div className="text-xs text-slate-500 font-medium mb-1.5 line-clamp-1">
                  来源笔记：{ev.title}
                </div>
              )}

              {/* Excerpt Body */}
              <div className="text-sm text-slate-800 leading-relaxed font-normal bg-slate-50/50 p-3 rounded-xl border border-slate-100">
                <p className={`whitespace-pre-line ${!isExpanded && isLongExcerpt ? 'line-clamp-3' : ''}`}>
                  “{ev.excerpt || '暂无文字摘录'}”
                </p>
                {isLongExcerpt && (
                  <button
                    onClick={() => toggleItemExpand(ev.evidenceId)}
                    className="mt-1.5 text-xs text-orange-600 hover:text-orange-700 font-medium inline-flex items-center gap-1"
                  >
                    {isExpanded ? (
                      <>
                        收起 <ChevronUp className="w-3 h-3" />
                      </>
                    ) : (
                      <>
                        展开完整评论 <ChevronDown className="w-3 h-3" />
                      </>
                    )}
                  </button>
                )}
              </div>

              {/* Associated Entity / Shop Link */}
              {ev.entityRefs && ev.entityRefs.length > 0 && (
                <div className="mt-2.5 pt-2 border-t border-slate-100 flex items-center justify-between text-xs">
                  <div className="flex items-center gap-1.5 text-slate-500">
                    <span>关联目标：</span>
                    {ev.entityRefs.map((ref, rIdx) => (
                      <button
                        key={rIdx}
                        onClick={() => onSelectShop?.(ref.entityId)}
                        className="px-2 py-0.5 rounded-md bg-slate-100 hover:bg-orange-50 hover:text-orange-700 text-slate-700 font-medium transition-colors"
                      >
                        {ref.entityId}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
