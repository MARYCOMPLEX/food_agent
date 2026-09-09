<script setup lang="ts">
import type { ResearchControversyViewV1 } from '../../../../shared/contracts/research'
import { ref } from 'vue'
import { formatPercent } from './researchFormat'

withDefaults(defineProps<{
  controversies: ResearchControversyViewV1[]
  loading?: boolean
}>(), { loading: false })

const expanded = ref<string | null>(null)

function statusLabel(status: ResearchControversyViewV1['status']): string {
  return status === 'resolved' ? '已核清' : status === 'partially_resolved' ? '部分核清' : '仍有分歧'
}

function toggle(id: string) {
  expanded.value = expanded.value === id ? null : id
}
</script>

<template>
  <section class="research-panel research-controversy-panel" aria-labelledby="research-controversy-title">
    <div class="research-panel-heading research-panel-heading-wrap">
      <div>
        <p class="research-kicker">CONFLICT MAP</p>
        <h2 id="research-controversy-title" class="research-panel-title">争议与反例</h2>
        <p class="research-panel-subtitle">把相互矛盾的体验并列展示，帮助你判断“适不适合我”。</p>
      </div>
      <span class="research-count-badge research-count-badge-warm">{{ controversies.length }} 个</span>
    </div>

    <div v-if="loading && !controversies.length" class="research-skeleton-list" aria-label="争议加载中" aria-busy="true">
      <div v-for="index in 2" :key="index" class="research-skeleton-block" />
    </div>
    <div v-else-if="!controversies.length" class="research-empty-inline">
      <span class="research-empty-glyph" aria-hidden="true">◇</span>
      <span>暂未发现需要单独核对的争议</span>
    </div>
    <div v-else class="research-controversy-list">
      <article v-for="item in controversies" :key="item.controversyId" class="research-controversy-card" :class="`is-${item.status ?? 'unresolved'}`">
        <div class="research-controversy-heading">
          <div>
            <h3>{{ item.topic }}</h3>
            <p v-if="item.summary">{{ item.summary }}</p>
          </div>
          <span class="research-controversy-status">{{ statusLabel(item.status) }}</span>
        </div>
        <div v-if="item.sides?.length" class="research-sides">
          <div v-for="(side, index) in item.sides.slice(0, 2)" :key="side.sideId" class="research-side" :class="index === 0 ? 'is-first' : 'is-second'">
            <div class="research-side-label"><span aria-hidden="true">{{ index === 0 ? '＋' : '－' }}</span>{{ side.label }}</div>
            <p v-if="side.summary">{{ side.summary }}</p>
            <span v-if="side.evidenceRefs?.length" class="research-side-ref">{{ side.evidenceRefs.length }} 条评论支持</span>
          </div>
        </div>
        <div v-if="item.resolution || item.remainingQuestion" class="research-controversy-resolution">
          <div v-if="item.resolution"><span>目前判断</span><p>{{ item.resolution }}</p></div>
          <div v-if="item.remainingQuestion"><span>还需留意</span><p>{{ item.remainingQuestion }}</p></div>
        </div>
        <div class="research-controversy-footer">
          <span v-if="item.confidence !== null && item.confidence !== undefined">判断置信度 {{ formatPercent(item.confidence) }}</span>
          <span v-if="item.evidenceRefs?.length">引用 {{ item.evidenceRefs.length }} 条证据</span>
          <button class="research-text-button" type="button" :aria-expanded="expanded === item.controversyId" @click="toggle(item.controversyId)">
            {{ expanded === item.controversyId ? '收起证据链' : '查看证据链' }}
          </button>
        </div>
        <div v-if="expanded === item.controversyId" class="research-evidence-detail">
          <span v-for="ref in item.evidenceRefs ?? []" :key="ref">证据 {{ ref }}</span>
          <span v-if="!item.evidenceRefs?.length">暂无可公开的证据引用</span>
        </div>
      </article>
    </div>
  </section>
</template>
