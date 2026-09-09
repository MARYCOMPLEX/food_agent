<script setup lang="ts">
import type {
  ResearchCoverageViewV1,
  ResearchMetricsV1,
  ResearchPlanStepViewV1,
  ResearchRunStatusV1,
} from '../../../../shared/contracts/research'
import { computed } from 'vue'
import { formatCount, formatPercent, statusLabel, stepStatusLabel } from './researchFormat'

const props = withDefaults(defineProps<{
  plan: ResearchPlanStepViewV1[]
  coverage?: ResearchCoverageViewV1 | null
  metrics?: ResearchMetricsV1
  phase?: string | null
  status?: ResearchRunStatusV1
}>(), {
  coverage: null,
  metrics: () => ({}),
  phase: null,
  status: undefined,
})

const completedCount = computed(() => props.plan.filter(step => ['succeeded', 'partial'].includes(step.status ?? '')).length)
const planRatio = computed(() => props.plan.length ? completedCount.value / props.plan.length : 0)
const currentStep = computed(() => props.plan.find(step => step.status === 'running') ?? props.plan.find(step => step.status === 'pending'))
const dimensions = computed(() => props.coverage?.dimensions ?? [])
</script>

<template>
  <section class="research-panel research-plan-panel" aria-labelledby="research-plan-title">
    <div class="research-panel-heading">
      <div>
        <p class="research-kicker">LIVE INVESTIGATION</p>
        <h2 id="research-plan-title" class="research-panel-title">调查计划</h2>
      </div>
      <span class="research-status-pill" :class="`is-${status ?? 'queued'}`">
        <span class="research-status-dot" aria-hidden="true" />
        {{ statusLabel(status) }}
      </span>
    </div>

    <div v-if="plan.length" class="research-plan-progress" aria-label="调查计划完成度">
      <div class="research-progress-track" role="progressbar" :aria-valuenow="Math.round(planRatio * 100)" aria-valuemin="0" aria-valuemax="100">
        <span :style="{ width: `${planRatio * 100}%` }" />
      </div>
      <div class="research-plan-progress-meta">
        <span>{{ completedCount }}/{{ plan.length }} 个步骤已完成</span>
        <span>{{ phase || currentStep?.phase || '等待 Agent 安排下一步' }}</span>
      </div>
    </div>

    <div v-if="plan.length" class="research-plan-list">
      <article v-for="(step, index) in plan" :key="step.stepId" class="research-plan-step" :class="`is-${step.status ?? 'pending'}`">
        <div class="research-plan-index" aria-hidden="true">
          <span v-if="step.status === 'succeeded'">✓</span>
          <span v-else-if="step.status === 'failed'">!</span>
          <span v-else>{{ index + 1 }}</span>
        </div>
        <div class="research-plan-copy">
          <div class="research-plan-step-heading">
            <strong>{{ step.label }}</strong>
            <span>{{ stepStatusLabel(step.status) }}</span>
          </div>
          <p v-if="step.detail">{{ step.detail }}</p>
          <div v-if="step.counts && Object.keys(step.counts).length" class="research-inline-metrics">
            <span v-for="(count, label) in step.counts" :key="label">{{ label }} {{ formatCount(count) }}</span>
          </div>
        </div>
      </article>
    </div>

    <div v-else class="research-empty-inline">
      <span class="research-empty-glyph" aria-hidden="true">◌</span>
      <span>Agent 还在整理调查计划</span>
    </div>

    <div class="research-plan-footer">
      <div class="research-metric-row" aria-label="研究统计">
        <span><b>{{ formatCount(metrics?.commentEvidenceItems ?? metrics?.evidenceItems) }}</b> 条评论证据</span>
        <span><b>{{ formatCount(metrics?.profiles) }}</b> 家店铺档案</span>
        <span><b>{{ formatCount(metrics?.controversies) }}</b> 个争议点</span>
      </div>
      <div v-if="dimensions.length" class="research-coverage-list" aria-label="覆盖度">
        <span v-for="dimension in dimensions" :key="dimension.dimension" class="research-coverage-item">
          {{ dimension.dimension }} <b>{{ formatPercent(dimension.ratio) }}</b>
        </span>
      </div>
    </div>
  </section>
</template>
