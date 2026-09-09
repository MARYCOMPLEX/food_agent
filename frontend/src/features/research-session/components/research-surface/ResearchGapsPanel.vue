<script setup lang="ts">
import type { ResearchGapViewV1 } from '../../../../shared/contracts/research'
import { computed } from 'vue'
import { formatDate, gapActionLabel, gapSeverityLabel, sourceLabel } from './researchFormat'

const props = withDefaults(defineProps<{
  gaps: ResearchGapViewV1[]
  loading?: boolean
}>(), { loading: false })

const emit = defineEmits<{
  (event: 'retry', gap: ResearchGapViewV1): void
}>()

const openGaps = computed(() => props.gaps.filter(gap => gap.status !== 'resolved'))

function gapStatusLabel(status: ResearchGapViewV1['status']): string {
  return status === 'retrying' ? '重试中' : status === 'exhausted' ? '已耗尽' : status === 'resolved' ? '已补齐' : '待处理'
}
</script>

<template>
  <section class="research-panel research-gap-panel" aria-labelledby="research-gap-title" aria-live="polite">
    <div class="research-panel-heading research-panel-heading-wrap">
      <div>
        <p class="research-kicker">KNOWN LIMITS</p>
        <h2 id="research-gap-title" class="research-panel-title">数据缺口</h2>
        <p class="research-panel-subtitle">部分失败会被明确标出，不会静默影响最终判断。</p>
      </div>
      <span class="research-count-badge" :class="openGaps.length ? 'research-count-badge-danger' : 'research-count-badge-cool'">{{ openGaps.length ? `${openGaps.length} 项待处理` : '已覆盖' }}</span>
    </div>

    <div v-if="loading && !gaps.length" class="research-skeleton-list" aria-label="缺口加载中" aria-busy="true">
      <div v-for="index in 2" :key="index" class="research-skeleton-line" />
    </div>
    <div v-else-if="!gaps.length" class="research-gap-clear">
      <span class="research-gap-clear-icon" aria-hidden="true">✓</span>
      <div><strong>目前没有已知缺口</strong><p>证据链和店铺补充均未报告异常。</p></div>
    </div>
    <ul v-else class="research-gap-list">
      <li v-for="gap in gaps" :key="gap.gapId" class="research-gap-item" :class="`is-${gap.severity ?? 'info'}`">
        <span class="research-gap-icon" aria-hidden="true">{{ gap.severity === 'error' ? '!' : gap.severity === 'warning' ? '△' : 'i' }}</span>
        <div class="research-gap-copy">
          <div class="research-gap-heading"><strong>{{ gap.message }}</strong><span>{{ gapStatusLabel(gap.status) }}</span></div>
          <p>{{ sourceLabel(gap.source) }} · {{ gap.operation }} · {{ gapSeverityLabel(gap.severity) }}</p>
          <time :datetime="gap.occurredAt ?? undefined">{{ formatDate(gap.occurredAt) }}</time>
        </div>
        <button v-if="gap.retryable && gap.status !== 'resolved'" class="research-gap-action" type="button" :disabled="gap.status === 'retrying'" @click="emit('retry', gap)">
          {{ gapActionLabel(gap) }}
        </button>
      </li>
    </ul>
  </section>
</template>
