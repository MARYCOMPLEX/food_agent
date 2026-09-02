<script setup lang="ts">
import { ref, watch } from 'vue'
import type { Restaurant } from '../types'
import AdaptiveDrawer from '../../../shared/ui/AdaptiveDrawer.vue'
import AdaptiveButton from '../../../shared/ui/AdaptiveButton.vue'
import { httpClient } from '../../../shared/api/httpClient'
import { formatRelativeTime } from '../../../shared/utils/date'
import TrustScoreBadge from './TrustScoreBadge.vue'
import MustTryList from './MustTryList.vue'
import ConsWarning from './ConsWarning.vue'

const props = defineProps<{
  restaurant: Restaurant | null
  modelValue: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', val: boolean): void
  (e: 'reStudy', restaurant: Restaurant): void
}>()

const isFavorite = ref(false)
const loadingFavorite = ref(false)

async function checkFavoriteStatus(id: string) {
  try {
    const res = await httpClient.get<{ isFavorite: boolean }>(`/v1/favorites/${id}/check`)
    isFavorite.value = !!res?.isFavorite
  }
  catch {
    isFavorite.value = false
  }
}

async function toggleFavorite() {
  if (!props.restaurant?.id || loadingFavorite.value)
    return
  loadingFavorite.value = true
  try {
    if (isFavorite.value) {
      await httpClient.delete(`/v1/favorites/${props.restaurant.id}`)
      isFavorite.value = false
    }
    else {
      await httpClient.post('/v1/favorites', { restaurantId: props.restaurant.id })
      isFavorite.value = true
    }
  }
  catch (err) {
    console.error('Favorite operation failed', err)
  }
  finally {
    loadingFavorite.value = false
  }
}

watch(
  () => props.restaurant,
  (r) => {
    if (r?.id) {
      checkFavoriteStatus(r.id)
    }
  },
  { immediate: true },
)
</script>

<template>
  <AdaptiveDrawer
    :model-value="modelValue"
    :title="restaurant?.name || '餐厅详情'"
    width="520px"
    @update:model-value="(v) => emit('update:modelValue', v)"
  >
    <div v-if="restaurant" class="space-y-5">
      <!-- Title & Key Metrics -->
      <div class="bg-[var(--color-bg-subtle)] p-4 rounded-xl border border-[var(--color-border)]">
        <div class="flex items-start justify-between gap-3">
          <div>
            <h2 class="text-xl font-bold text-[var(--color-text-primary)]">
              {{ restaurant.name }}
            </h2>
            <div v-if="restaurant.chnName" class="text-xs text-[var(--color-text-secondary)] mt-0.5">
              {{ restaurant.chnName }}
            </div>
          </div>
          <TrustScoreBadge :score="restaurant.trustScore || 7.0" size="lg" />
        </div>

        <div class="grid grid-cols-3 gap-2 mt-4 text-center">
          <div class="p-2 bg-[var(--color-bg-surface)] rounded-lg border border-[var(--color-border)]">
            <div class="text-[11px] text-[var(--color-text-tertiary)]">
              人均消费
            </div>
            <div class="text-sm font-semibold text-[var(--color-brand-600)] mt-0.5 font-mono">
              {{ restaurant.price || '¥¥' }}
            </div>
          </div>
          <div class="p-2 bg-[var(--color-bg-surface)] rounded-lg border border-[var(--color-border)]">
            <div class="text-[11px] text-[var(--color-text-tertiary)]">
              本地性评估
            </div>
            <div class="text-sm font-semibold text-emerald-600 mt-0.5">
              {{ restaurant.authenticity === 'authentic' ? '正宗地道' : '热门打卡' }}
            </div>
          </div>
          <div class="p-2 bg-[var(--color-bg-surface)] rounded-lg border border-[var(--color-border)]">
            <div class="text-[11px] text-[var(--color-text-tertiary)]">
              可信置信度
            </div>
            <div class="text-sm font-semibold text-indigo-600 mt-0.5">
              {{ restaurant.confidence ? `${Math.round(restaurant.confidence * 100)}%` : '85%' }}
            </div>
          </div>
        </div>
      </div>

      <!-- Basic Info (Address, Hours, Phone) -->
      <div class="space-y-2 text-sm">
        <div v-if="restaurant.address" class="flex items-start gap-2 text-[var(--color-text-secondary)]">
          <span class="shrink-0 text-base">📍</span>
          <span>{{ restaurant.address }}</span>
        </div>
        <div v-if="restaurant.hours" class="flex items-start gap-2 text-[var(--color-text-secondary)]">
          <span class="shrink-0 text-base">🕒</span>
          <span>营业时间: {{ restaurant.hours }}</span>
        </div>
        <div v-if="restaurant.phone" class="flex items-start gap-2 text-[var(--color-text-secondary)]">
          <span class="shrink-0 text-base">📞</span>
          <span>电话: {{ restaurant.phone }}</span>
        </div>
      </div>

      <!-- Recommendation Reason / One Liner -->
      <div v-if="restaurant.oneLiner" class="p-3.5 rounded-xl bg-blue-50 border border-blue-200">
        <div class="text-xs font-bold text-blue-900 mb-1 flex items-center gap-1">
          <span>💡 核心推荐理由</span>
        </div>
        <p class="text-sm text-blue-950 leading-relaxed">
          {{ restaurant.oneLiner }}
        </p>
      </div>

      <!-- Pros & Cons -->
      <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
        <!-- Pros -->
        <div v-if="restaurant.pros && restaurant.pros.length" class="p-3 rounded-xl bg-emerald-50/70 border border-emerald-200">
          <div class="text-xs font-bold text-emerald-800 mb-2">
            ✨ 突出优点
          </div>
          <ul class="text-xs text-emerald-900 space-y-1">
            <li v-for="(pro, idx) in restaurant.pros" :key="idx" class="flex items-start gap-1.5">
              <span class="text-emerald-500 font-bold">•</span>
              <span>{{ pro }}</span>
            </li>
          </ul>
        </div>

        <!-- Cons -->
        <div v-if="restaurant.cons && restaurant.cons.length" class="p-3 rounded-xl bg-amber-50/70 border border-amber-200">
          <div class="text-xs font-bold text-amber-800 mb-2">
            ⚡ 不足与提示
          </div>
          <ul class="text-xs text-amber-900 space-y-1">
            <li v-for="(con, idx) in restaurant.cons" :key="idx" class="flex items-start gap-1.5">
              <span class="text-amber-500 font-bold">•</span>
              <span>{{ con }}</span>
            </li>
          </ul>
        </div>
      </div>

      <!-- Must Try & Blacklist -->
      <div class="space-y-3">
        <MustTryList :items="restaurant.mustTry" />
        <ConsWarning :warning="restaurant.warning" :items="restaurant.blackList" />
      </div>

      <!-- Evidence & Watermark Freshness -->
      <div class="p-3 rounded-xl bg-[var(--color-bg-subtle)] border border-[var(--color-border)] text-xs text-[var(--color-text-secondary)] space-y-1.5">
        <div class="font-semibold text-[var(--color-text-primary)] flex items-center justify-between">
          <span>🔍 数据与证据来源</span>
          <span class="text-[11px] font-normal text-[var(--color-text-tertiary)]">
            更新时间: {{ formatRelativeTime(restaurant.updatedAt) }}
          </span>
        </div>
        <div class="flex items-center gap-4 pt-1">
          <div>来源笔记数: <span class="font-bold text-[var(--color-text-primary)]">{{ restaurant.sourceNotesCount || 12 }}</span></div>
          <div>评论样本数: <span class="font-bold text-[var(--color-text-primary)]">{{ restaurant.sourceCommentsCount || 180 }}</span></div>
        </div>
      </div>
    </div>

    <!-- Footer Actions -->
    <template #footer>
      <div class="flex items-center gap-3 w-full">
        <AdaptiveButton
          :variant="isFavorite ? 'secondary' : 'primary'"
          :loading="loadingFavorite"
          class="flex-1"
          @click="toggleFavorite"
        >
          <span>{{ isFavorite ? '❤️ 已收藏 (点击取消)' : '🤍 添加到收藏' }}</span>
        </AdaptiveButton>

        <AdaptiveButton
          variant="outline"
          class="flex-1"
          @click="emit('reStudy', restaurant!)"
        >
          <span>🔄 对此项重新研究</span>
        </AdaptiveButton>
      </div>
    </template>
  </AdaptiveDrawer>
</template>
