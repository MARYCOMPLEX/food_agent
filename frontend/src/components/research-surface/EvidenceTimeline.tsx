import React, { useState, useMemo } from 'react'
import {
  MessageSquare,
  Search,
  Clock,
  ChevronDown,
  ChevronUp,
} from 'lucide-react'
import type {
  ResearchEvidenceItemV1,
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
      <div className="p-8 rounded-2xl border border-dashed border-zinc-200 bg-zinc-50/50 text-center">
        <div className="w-10 h-10 mx-auto rounded-full bg-zinc-100 flex items-center justify-center text-zinc-400 mb-2">
          <MessageSquare className="w-5 h-5" />
        </div>
        <p className="text-sm font-medium text-zinc-700">正在检索各平台真实探店评价...</p>
        <p className="text-xs text-zinc-400 mt-1">首条有效证据提取后将实时呈现于此</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Header with Title & Filter Bar */}
      <div className="space-y-3 bg-white p-3.5 rounded-2xl border border-zinc-200">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <h3 className="font-semibold text-zinc-900 text-sm">真实评论证据库</h3>
            <span className="text-xs font-mono px-2 py-0.5 rounded-full bg-zinc-100 text-zinc-600 border border-zinc-200/50">
              {filteredEvidence.length} / {evidenceItems.length}
            </span>
          </div>

          {/* Search Box */}
          <div className="relative">
            <Search className="w-3.5 h-3.5 text-zinc-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              placeholder="搜索评论..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-8 pr-3 py-1 bg-zinc-50 focus:bg-white border border-zinc-200 rounded-lg text-xs text-zinc-800 placeholder-zinc-400 focus:outline-none focus:ring-1 focus:ring-zinc-400 transition-all w-36 sm:w-44"
            />
          </div>
        </div>

        {/* Stance Filter Pills */}
        <div className="flex items-center gap-1 overflow-x-auto pb-0.5 text-xs font-medium">
          <button
            onClick={() => setStanceFilter('all')}
            className={`px-2.5 py-1 rounded-full transition-colors ${stanceFilter === 'all' ? 'bg-zinc-900 text-white' : 'bg-zinc-100 text-zinc-600 hover:bg-zinc-200'}`}
          >
            全部 ({stanceCounts.all})
          </button>
          <button
            onClick={() => setStanceFilter('positive')}
            className={`px-2.5 py-1 rounded-full transition-colors ${stanceFilter === 'positive' ? 'bg-zinc-900 text-white' : 'bg-zinc-100 text-zinc-600 hover:bg-zinc-200'}`}
          >
            好评 ({stanceCounts.positive})
          </button>
          <button
            onClick={() => setStanceFilter('negative')}
            className={`px-2.5 py-1 rounded-full transition-colors ${stanceFilter === 'negative' ? 'bg-zinc-900 text-white' : 'bg-zinc-100 text-zinc-600 hover:bg-zinc-200'}`}
          >
            踩雷 ({stanceCounts.negative})
          </button>
          <button
            onClick={() => setStanceFilter('mixed')}
            className={`px-2.5 py-1 rounded-full transition-colors ${stanceFilter === 'mixed' ? 'bg-zinc-900 text-white' : 'bg-zinc-100 text-zinc-600 hover:bg-zinc-200'}`}
          >
            分歧 ({stanceCounts.mixed})
          </button>
        </div>
      </div>

      {/* Evidence List */}
      <div className="space-y-3">
        {filteredEvidence.map((ev, idx) => {
          const isSelected = selectedEvidenceId === ev.evidenceId
          const isExpanded = expandedItems[ev.evidenceId] ?? false
          const isLongExcerpt = (ev.excerpt || '').length > 180

          let stanceTag = {
            label: '事实中立',
            class: 'bg-zinc-100 text-zinc-700 border-zinc-200/60',
          }
          if (ev.stance === 'positive') {
            stanceTag = {
              label: '好评',
              class: 'bg-emerald-50 text-[#10a37f] border-emerald-200/60',
            }
          } else if (ev.stance === 'negative') {
            stanceTag = {
              label: '避雷',
              class: 'bg-red-50 text-red-600 border-red-200/60',
            }
          } else if (ev.stance === 'mixed') {
            stanceTag = {
              label: '分歧',
              class: 'bg-amber-50 text-amber-700 border-amber-200/60',
            }
          }

          const platformLabel = (ev.source || '').toLowerCase().includes('xhs')
            ? '小红书'
            : (ev.source || '').toLowerCase().includes('dianping')
            ? '大众点评'
            : ev.source || '公开采集源'

          return (
            <div
              key={ev.evidenceId || idx}
              id={`evidence-${ev.evidenceId}`}
              className={`rounded-2xl border bg-white p-4 transition-all ${
                isSelected
                  ? 'border-zinc-900 ring-1 ring-zinc-900 shadow-sm'
                  : 'border-zinc-200 shadow-2xs hover:border-zinc-300'
              }`}
            >
              {/* Card Header */}
              <div className="flex items-center justify-between gap-2 mb-2 flex-wrap text-xs">
                <div className="flex items-center gap-1.5">
                  <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-zinc-100 text-zinc-700 font-medium text-[11px]">
                    {platformLabel}
                  </span>
                  <span className={`inline-flex items-center px-2 py-0.5 rounded-full border text-[11px] font-medium ${stanceTag.class}`}>
                    {stanceTag.label}
                  </span>
                  {ev.confidence !== undefined && ev.confidence !== null && (
                    <span className="text-zinc-400 font-mono text-[11px]">
                      置信度 {Math.round(ev.confidence * 100)}%
                    </span>
                  )}
                </div>

                <div className="flex items-center gap-2 text-zinc-400 text-[11px]">
                  {ev.capturedAt && (
                    <span className="flex items-center gap-1 font-mono">
                      <Clock className="w-3 h-3" />
                      {new Date(ev.capturedAt).toLocaleDateString()}
                    </span>
                  )}
                </div>
              </div>

              {/* Note / Context Title */}
              {ev.title && (
                <div className="text-xs text-zinc-500 font-medium mb-1.5 line-clamp-1">
                  笔记：{ev.title}
                </div>
              )}

              {/* Excerpt Body */}
              <div className="text-sm text-zinc-800 leading-relaxed font-normal bg-zinc-50/70 p-3 rounded-xl border border-zinc-100">
                <p className={`whitespace-pre-line ${!isExpanded && isLongExcerpt ? 'line-clamp-3' : ''}`}>
                  “{ev.excerpt || '暂无摘录'}”
                </p>
                {isLongExcerpt && (
                  <button
                    onClick={() => toggleItemExpand(ev.evidenceId)}
                    className="mt-1.5 text-xs text-zinc-600 hover:text-zinc-900 font-medium inline-flex items-center gap-1"
                  >
                    {isExpanded ? (
                      <>
                        收起 <ChevronUp className="w-3 h-3" />
                      </>
                    ) : (
                      <>
                        展开更多 <ChevronDown className="w-3 h-3" />
                      </>
                    )}
                  </button>
                )}
              </div>

              {/* Associated Entity */}
              {ev.entityRefs && ev.entityRefs.length > 0 && (
                <div className="mt-2.5 pt-2 border-t border-zinc-100 flex items-center justify-between text-xs">
                  <div className="flex items-center gap-1.5 text-zinc-400">
                    <span>关联餐厅：</span>
                    {ev.entityRefs.map((ref, rIdx) => (
                      <button
                        key={rIdx}
                        onClick={() => onSelectShop?.(ref.entityId)}
                        className="px-2 py-0.5 rounded-full bg-zinc-100 hover:bg-zinc-200 text-zinc-700 font-medium transition-colors text-[11px]"
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

