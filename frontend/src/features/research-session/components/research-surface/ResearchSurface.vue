<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ResearchGapViewV1, ResearchRunStatusV1, UserResearchProjectionV1 } from '../../../../shared/contracts/research'
import ControversyPanel from './ControversyPanel.vue'
import EvidenceTimeline from './EvidenceTimeline.vue'
import ResearchGapsPanel from './ResearchGapsPanel.vue'
import ResearchPlanPanel from './ResearchPlanPanel.vue'
import ShopProfileGrid from './ShopProfileGrid.vue'
import RecommendationList from './RecommendationList.vue'
import type { ResearchSurfaceProps } from './researchSurface.types'
import { formatCount, statusLabel } from './researchFormat'
import './research-surface.css'

const props = withDefaults(defineProps<ResearchSurfaceProps>(), {
  projection: null,
  evidence: undefined,
  controversies: undefined,
  profiles: undefined,
  recommendations: undefined,
  gaps: undefined,
  plan: undefined,
  coverage: undefined,
  metrics: undefined,
  status: undefined,
  phase: undefined,
  summary: undefined,
  loading: false,
  error: null,
})

const emit = defineEmits<{
  (event: 'retry'): void
  (event: 'retry-gap', gap: ResearchGapViewV1): void
}>()

const activeSection = ref<'overview' | 'evidence' | 'controversies' | 'profiles' | 'gaps'>('overview')

const projection = computed<UserResearchProjectionV1 | null>(() => props.projection ?? null)
const evidence = computed(() => props.evidence ?? projection.value?.evidence ?? [])
const controversies = computed(() => props.controversies ?? projection.value?.controversies ?? [])
const profiles = computed(() => props.profiles ?? projection.value?.profiles ?? [])
const recommendations = computed(() => props.recommendations ?? projection.value?.recommendations ?? [])
const gaps = computed(() => props.gaps ?? projection.value?.gaps ?? [])
const plan = computed(() => props.plan ?? projection.value?.plan ?? [])
const metrics = computed(() => props.metrics ?? projection.value?.metrics ?? {})
const coverage = computed(() => props.coverage ?? projection.value?.coverage ?? null)
const status = computed<ResearchRunStatusV1 | undefined>(() => props.status ?? projection.value?.status)
const phase = computed(() => props.phase ?? projection.value?.phase ?? null)
const summary = computed(() => props.summary ?? projection.value?.summary ?? null)
const runId = computed(() => projection.value?.runId ?? null)

const state = computed(() => {
  const hasContent = evidence.value.length || controversies.value.length || profiles.value.length || recommendations.value.length || gaps.value.length || plan.value.length || summary.value
  if (!hasContent && props.loading) return 'loading'
  if (!hasContent && props.error) return 'error'
  return hasContent ? 'ready' : 'empty'
})

const openGapCount = computed(() => gaps.value.filter(gap => gap.status !== 'resolved').length)
const tabs = computed(() => [
  { id: 'overview' as const, label: '总览', count: null },
  { id: 'evidence' as const, label: '评论证据', count: evidence.value.length },
  { id: 'controversies' as const, label: '争议', count: controversies.value.length },
  { id: 'profiles' as const, label: '店铺档案', count: profiles.value.length },
  { id: 'gaps' as const, label: '缺口', count: openGapCount.value },
])

function setSection(section: typeof activeSection.value) {
  activeSection.value = section
}

function handleRetryGap(gap: ResearchGapViewV1) {
  emit('retry-gap', gap)
}
</script>

<template>
  <section class="research-surface" aria-labelledby="research-surface-title">
    <header class="research-surface-header">
      <div class="research-surface-title-block">
        <div class="research-eyebrow"><span class="research-eyebrow-mark" aria-hidden="true">✦</span> EVIDENCE-LED RESEARCH</div>
        <h1 id="research-surface-title">研究现场</h1>
        <p v-if="summary" class="research-surface-summary">{{ summary }}</p>
        <p v-else class="research-surface-summary">Agent 正在把评论线索、争议与店铺事实整理成可复核的结论。</p>
      </div>
      <div class="research-surface-status" role="status" aria-live="polite">
        <span class="research-surface-status-label">{{ statusLabel(status) }}</span>
        <span v-if="runId" class="research-surface-run">RUN {{ runId }}</span>
        <button v-if="state === 'error'" class="research-retry-button" type="button" @click="emit('retry')">重新连接</button>
      </div>
    </header>

    <div class="research-surface-metrics" aria-label="研究进展摘要">
      <div><span>证据</span><strong>{{ formatCount(metrics.commentEvidenceItems ?? metrics.evidenceItems) }}</strong></div>
      <div><span>争议</span><strong>{{ formatCount(metrics.controversies) }}</strong></div>
      <div><span>店铺</span><strong>{{ formatCount(metrics.profiles) }}</strong></div>
      <div :class="openGapCount ? 'has-alert' : ''"><span>缺口</span><strong>{{ formatCount(openGapCount) }}</strong></div>
    </div>

    <nav class="research-surface-tabs" aria-label="研究内容导航" role="tablist">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        class="research-surface-tab"
        :class="{ 'is-active': activeSection === tab.id }"
        type="button"
        role="tab"
        :id="`research-tab-${tab.id}`"
        :aria-selected="activeSection === tab.id"
        :aria-controls="`research-panel-${tab.id}`"
        @click="setSection(tab.id)"
      >
        <span>{{ tab.label }}</span>
        <span v-if="tab.count !== null" class="research-tab-count">{{ tab.count }}</span>
      </button>
    </nav>

    <div v-if="state === 'loading'" class="research-surface-loading" role="status" aria-live="polite">
      <div class="research-loading-orbit" aria-hidden="true"><span /><span /><span /></div>
      <div><strong>Agent 正在整理证据</strong><p>新发现会逐步出现在研究现场，不需要等待全部流程结束。</p></div>
    </div>

    <div v-else-if="state === 'error'" class="research-surface-error" role="alert">
      <span class="research-error-icon" aria-hidden="true">!</span>
      <div><strong>研究流暂时中断</strong><p>{{ error }}</p></div>
      <button class="research-error-action" type="button" @click="emit('retry')">重试</button>
    </div>

    <div v-else-if="state === 'empty'" class="research-surface-empty" role="status">
      <div class="research-empty-illustration" aria-hidden="true"><span>⌁</span><span>◌</span><span>⌂</span></div>
      <h2>调查即将开始</h2>
      <p>当 Agent 找到第一条评论线索，这里会实时呈现证据和店铺档案。</p>
    </div>

    <div v-else class="research-surface-content">
      <div v-if="error" class="research-surface-inline-error" role="alert">
        <span aria-hidden="true">!</span>
        <p>{{ error }}，已保留当前已收集的研究结果。</p>
        <button type="button" @click="emit('retry')">重试连接</button>
      </div>
      <div v-if="loading" class="research-surface-live-note" role="status" aria-live="polite">
        <span class="research-status-dot" aria-hidden="true" />
        <p>Agent 仍在调查，新的证据和档案会继续增量出现。</p>
      </div>
      <div v-show="activeSection === 'overview'" id="research-panel-overview" role="tabpanel" aria-labelledby="research-tab-overview" class="research-surface-overview">
        <ResearchPlanPanel :plan="plan" :coverage="coverage" :metrics="metrics" :phase="phase" :status="status" />
        <RecommendationList :recommendations="recommendations" :loading="props.loading" />
        <div class="research-overview-grid">
          <EvidenceTimeline :evidence="evidence" :loading="props.loading" />
          <ControversyPanel :controversies="controversies" :loading="props.loading" />
        </div>
        <ShopProfileGrid :profiles="profiles" :loading="props.loading" />
        <ResearchGapsPanel :gaps="gaps" :loading="props.loading" @retry="handleRetryGap" />
      </div>
      <div v-if="activeSection === 'evidence'" id="research-panel-evidence" role="tabpanel" aria-labelledby="research-tab-evidence" class="research-single-panel"><EvidenceTimeline :evidence="evidence" :loading="props.loading" /></div>
      <div v-if="activeSection === 'controversies'" id="research-panel-controversies" role="tabpanel" aria-labelledby="research-tab-controversies" class="research-single-panel"><ControversyPanel :controversies="controversies" :loading="props.loading" /></div>
      <div v-if="activeSection === 'profiles'" id="research-panel-profiles" role="tabpanel" aria-labelledby="research-tab-profiles" class="research-single-panel"><ShopProfileGrid :profiles="profiles" :loading="props.loading" /></div>
      <div v-if="activeSection === 'gaps'" id="research-panel-gaps" role="tabpanel" aria-labelledby="research-tab-gaps" class="research-single-panel"><ResearchGapsPanel :gaps="gaps" :loading="props.loading" @retry="handleRetryGap" /></div>
    </div>
  </section>
</template>
