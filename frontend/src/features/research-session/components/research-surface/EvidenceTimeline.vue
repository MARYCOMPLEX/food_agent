<script setup lang="ts">
import type { ResearchEvidenceItemV1 } from '../../../../shared/contracts/research'
import { computed, ref } from 'vue'
import { evidenceSource, formatDate, formatPercent, sourceLabel } from './researchFormat'

const props = withDefaults(defineProps<{
  evidence: ResearchEvidenceItemV1[]
  loading?: boolean
}>(), { loading: false })

const query = ref('')
const stance = ref<'all' | 'positive' | 'negative' | 'mixed' | 'neutral'>('all')
const expanded = ref<string | null>(null)

const filteredEvidence = computed(() => {
  const normalized = query.value.trim().toLowerCase()
  return props.evidence.filter((item) => {
    const matchesStance = stance.value === 'all' || item.stance === stance.value
    if (!matchesStance) return false
    if (!normalized) return true
    const searchable = [item.title, item.excerpt, item.source, item.noteRef, item.commentRef].filter(Boolean).join(' ').toLowerCase()
    return searchable.includes(normalized)
  })
})

function toggleExpanded(id: string) {
  expanded.value = expanded.value === id ? null : id
}
</script>

<template>
  <section class="research-panel research-evidence-panel" aria-labelledby="research-evidence-title">
    <div class="research-panel-heading research-panel-heading-wrap">
      <div>
        <p class="research-kicker">COMMENTARY SIGNALS</p>
        <h2 id="research-evidence-title" class="research-panel-title">评论证据</h2>
        <p class="research-panel-subtitle">从具体评论里提取口味、体验与反例，不把热度当成结论。</p>
      </div>
      <span class="research-count-badge">{{ evidence.length }} 条</span>
    </div>

    <div v-if="evidence.length" class="research-filter-row">
      <label class="research-search-field">
        <span class="sr-only">搜索评论证据</span>
        <span aria-hidden="true">⌕</span>
        <input v-model="query" type="search" placeholder="搜索店名、评论或来源">
      </label>
      <label class="research-select-field">
        <span class="sr-only">按立场筛选</span>
        <select v-model="stance">
          <option value="all">全部立场</option>
          <option value="positive">正向</option>
          <option value="negative">负向</option>
          <option value="mixed">混合</option>
          <option value="neutral">中性</option>
        </select>
      </label>
    </div>

    <div v-if="loading && !evidence.length" class="research-skeleton-list" aria-label="证据加载中" aria-busy="true">
      <div v-for="index in 3" :key="index" class="research-skeleton-line" />
    </div>

    <div v-else-if="!evidence.length" class="research-empty-inline">
      <span class="research-empty-glyph" aria-hidden="true">◎</span>
      <span>评论证据将在 Agent 找到可引用内容后出现</span>
    </div>

    <div v-else-if="!filteredEvidence.length" class="research-empty-inline">
      <span class="research-empty-glyph" aria-hidden="true">⌕</span>
      <span>没有匹配的证据，换个关键词或清除筛选</span>
    </div>

    <ol v-else class="research-evidence-timeline">
      <li v-for="item in filteredEvidence" :key="item.evidenceId" class="research-evidence-item">
        <span class="research-evidence-rail" aria-hidden="true"><span /></span>
        <article class="research-evidence-card">
          <div class="research-evidence-meta">
            <span class="research-source-chip" :class="`source-${evidenceSource(item).replace(/[^a-z0-9_-]/gi, '').toLowerCase()}`">{{ sourceLabel(evidenceSource(item)) }}</span>
            <span v-if="item.stance" class="research-stance" :class="`is-${item.stance}`">{{ item.stance === 'positive' ? '正向' : item.stance === 'negative' ? '负向' : item.stance === 'mixed' ? '有分歧' : '中性' }}</span>
            <time :datetime="item.capturedAt ?? undefined">{{ formatDate(item.capturedAt) }}</time>
          </div>
          <h3 v-if="item.title">{{ item.title }}</h3>
          <blockquote v-if="item.excerpt">“{{ item.excerpt }}”</blockquote>
          <div class="research-evidence-footer">
            <div class="research-ref-list">
              <span v-if="item.noteRef" class="research-ref-chip">笔记 {{ item.noteRef }}</span>
              <span v-if="item.commentRef" class="research-ref-chip">评论 {{ item.commentRef }}</span>
              <span v-if="item.confidence !== null && item.confidence !== undefined" class="research-confidence">可信度 {{ formatPercent(item.confidence) }}</span>
            </div>
            <button class="research-text-button" type="button" :aria-expanded="expanded === item.evidenceId" @click="toggleExpanded(item.evidenceId)">
              {{ expanded === item.evidenceId ? '收起' : '查看引用' }}
            </button>
          </div>
          <div v-if="expanded === item.evidenceId" class="research-evidence-detail">
            <span>证据编号 {{ item.evidenceId }}</span>
            <span v-if="item.claimRefs?.length">关联 {{ item.claimRefs.length }} 个判断</span>
            <span v-if="item.entityRefs?.length">涉及 {{ item.entityRefs.length }} 个实体</span>
          </div>
        </article>
      </li>
    </ol>
  </section>
</template>
