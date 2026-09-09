<script setup lang="ts">
import type { ResearchRecommendationViewV1 } from '../../../../shared/contracts/research'
import { computed, ref } from 'vue'
import { formatPercent } from './researchFormat'

const props = withDefaults(defineProps<{
  recommendations: ResearchRecommendationViewV1[]
  loading?: boolean
}>(), { loading: false })

const expanded = ref<string | null>(null)
const visibleRecommendations = computed(() => [...props.recommendations].sort((a, b) => (a.rank ?? 999) - (b.rank ?? 999)))

function toggle(id: string) {
  expanded.value = expanded.value === id ? null : id
}
</script>

<template>
  <section class="research-panel research-recommendation-panel" aria-labelledby="research-recommendation-title">
    <div class="research-panel-heading research-panel-heading-wrap">
      <div>
        <p class="research-kicker">SHORTLIST</p>
        <h2 id="research-recommendation-title" class="research-panel-title">值得去看</h2>
        <p class="research-panel-subtitle">推荐先看评论证据，再用争议和店铺档案做最后判断。</p>
      </div>
      <span class="research-count-badge research-count-badge-warm">{{ recommendations.length }} 家</span>
    </div>

    <div v-if="loading && !recommendations.length" class="research-recommendation-skeleton" aria-label="推荐加载中" aria-busy="true">
      <div v-for="index in 2" :key="index" />
    </div>
    <div v-else-if="!recommendations.length" class="research-empty-inline">
      <span class="research-empty-glyph" aria-hidden="true">⌂</span>
      <span>候选店铺会在评论线索被确认后出现在这里</span>
    </div>
    <ol v-else class="research-recommendation-list">
      <li v-for="(item, index) in visibleRecommendations" :key="item.recommendationId" class="research-recommendation-item">
        <span class="research-recommendation-rank" aria-hidden="true">{{ item.rank ?? index + 1 }}</span>
        <article>
          <div class="research-recommendation-heading">
            <div>
              <h3>{{ item.title }}</h3>
              <p v-if="item.summary">{{ item.summary }}</p>
            </div>
            <span v-if="item.confidence !== null && item.confidence !== undefined" class="research-confidence">{{ formatPercent(item.confidence) }}</span>
          </div>
          <div v-if="item.highlights?.length || item.warnings?.length" class="research-recommendation-signals">
            <span v-for="highlight in item.highlights?.slice(0, 3) ?? []" :key="`h-${highlight}`" class="is-positive">{{ highlight }}</span>
            <span v-for="warning in item.warnings?.slice(0, 2) ?? []" :key="`w-${warning}`" class="is-warning">{{ warning }}</span>
          </div>
          <div class="research-recommendation-footer">
            <span v-if="item.evidenceRefs?.length">{{ item.evidenceRefs.length }} 条评论证据</span>
            <span v-if="item.controversyRefs?.length">{{ item.controversyRefs.length }} 个争议点</span>
            <button class="research-text-button" type="button" :aria-expanded="expanded === item.recommendationId" @click="toggle(item.recommendationId)">
              {{ expanded === item.recommendationId ? '收起关联' : '查看关联' }}
            </button>
          </div>
          <div v-if="expanded === item.recommendationId" class="research-evidence-detail">
            <span v-if="item.profileRef">店铺档案 {{ item.profileRef }}</span>
            <span v-for="ref in item.evidenceRefs ?? []" :key="`e-${ref}`">证据 {{ ref }}</span>
            <span v-for="ref in item.controversyRefs ?? []" :key="`c-${ref}`">争议 {{ ref }}</span>
            <span v-if="!item.profileRef && !item.evidenceRefs?.length && !item.controversyRefs?.length">暂未公开关联信息</span>
          </div>
        </article>
      </li>
    </ol>
  </section>
</template>
