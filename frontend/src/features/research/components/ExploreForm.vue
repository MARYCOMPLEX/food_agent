<script setup lang="ts">
import { ref } from 'vue'
import type { PlatformChannel, UnifiedSearchRequest } from '../types'
import AdaptiveButton from '../../../shared/ui/AdaptiveButton.vue'
import { useDevice } from '../../../shared/utils/device'

const props = defineProps<{
  loading?: boolean
}>()

const emit = defineEmits<{
  (e: 'submit', request: UnifiedSearchRequest): void
}>()

const { isMobile } = useDevice()

const query = ref('')
const city = ref('成都')
const budget = ref('$$')
const taste = ref('地道/不辣')
const source = ref<PlatformChannel | 'all'>('all')
const mode = ref<'reuse' | 'incremental' | 'new'>('reuse')

const cityOptions = ['成都', '上海', '北京', '广州', '深圳', '杭州', '重庆', '西安', '武汉', '长沙']
const budgetOptions = [
  { label: '不限', value: '' },
  { label: '经济实惠 ($)', value: '$' },
  { label: '人均中等 ($$)', value: '$$' },
  { label: '高档品质 ($$$)', value: '$$$' },
]
const tasteOptions = ['地道老字号', '麻辣重口', '清淡少油', '夜市小吃', '适合聚餐', '一人食']

function setQueryAndCity(q: string, c: string) {
  query.value = q
  if (c)
    city.value = c
}

function handleSubmit() {
  if (!query.value.trim() || props.loading)
    return
  emit('submit', {
    query: query.value.trim(),
    city: city.value,
    budget: budget.value,
    taste: taste.value,
    source: source.value,
    mode: mode.value,
  })
}

defineExpose({
  setQueryAndCity,
})
</script>

<template>
  <form class="space-y-4" @submit.prevent="handleSubmit">
    <!-- Main Natural Language Input -->
    <div class="relative">
      <textarea
        v-model="query"
        rows="3"
        placeholder="输入您想寻找的美食需求，例如：'成都市中心不用排队、本地人常去的正宗老火锅' 或 '浦东机场附近地道川菜馆'..."
        class="w-full p-4 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-surface)] text-[var(--color-text-primary)] placeholder-[var(--color-text-tertiary)] focus:border-[var(--color-brand-500)] focus:ring-2 focus:ring-[var(--color-brand-100)] text-sm md:text-base outline-none resize-none transition-all shadow-xs"
        :disabled="loading"
        @keydown.enter.exact.prevent="handleSubmit"
      />
      <div class="absolute right-3 bottom-3 text-xs text-[var(--color-text-tertiary)] hidden sm:block">
        按 Enter 快速开始研究
      </div>
    </div>

    <!-- Filters Row: City, Budget, Taste, Source -->
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
      <!-- City Selector -->
      <div>
        <label class="block text-xs font-semibold text-[var(--color-text-secondary)] mb-1">目标城市</label>
        <select
          v-model="city"
          class="w-full px-3 py-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-surface)] text-xs md:text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-brand-500)] cursor-pointer"
        >
          <option v-for="c in cityOptions" :key="c" :value="c">
            {{ c }}
          </option>
        </select>
      </div>

      <!-- Budget Selector -->
      <div>
        <label class="block text-xs font-semibold text-[var(--color-text-secondary)] mb-1">预算区间</label>
        <select
          v-model="budget"
          class="w-full px-3 py-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-surface)] text-xs md:text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-brand-500)] cursor-pointer"
        >
          <option v-for="b in budgetOptions" :key="b.value" :value="b.value">
            {{ b.label }}
          </option>
        </select>
      </div>

      <!-- Taste Preference -->
      <div>
        <label class="block text-xs font-semibold text-[var(--color-text-secondary)] mb-1">口味偏好</label>
        <select
          v-model="taste"
          class="w-full px-3 py-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-surface)] text-xs md:text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-brand-500)] cursor-pointer"
        >
          <option v-for="t in tasteOptions" :key="t" :value="t">
            {{ t }}
          </option>
        </select>
      </div>

      <!-- Data Source Connectors -->
      <div>
        <label class="block text-xs font-semibold text-[var(--color-text-secondary)] mb-1">数据源连接器</label>
        <select
          v-model="source"
          class="w-full px-3 py-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-surface)] text-xs md:text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-brand-500)] cursor-pointer"
        >
          <option value="all">
            全平台 (XHS + 点评)
          </option>
          <option value="xhs_pc">
            小红书 PC 探索源
          </option>
          <option value="xhs_creator">
            小红书创作者源
          </option>
          <option value="dianping">
            大众点评源
          </option>
        </select>
      </div>
    </div>

    <!-- Research Mode Selector (复用证据 / 增量刷新 / 新建研究) -->
    <div class="p-3 bg-[var(--color-bg-subtle)] rounded-xl border border-[var(--color-border)] flex flex-col sm:flex-row sm:items-center justify-between gap-3">
      <div class="text-xs text-[var(--color-text-secondary)]">
        <span class="font-semibold text-[var(--color-text-primary)]">研究策略:</span>
        <span class="ml-1 text-[var(--color-text-tertiary)]">控制证据缓存与时效性</span>
      </div>

      <div class="flex items-center gap-1.5">
        <button
          type="button"
          class="px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all cursor-pointer"
          :class="mode === 'reuse' ? 'bg-[var(--color-brand-500)] text-white shadow-xs font-semibold' : 'bg-[var(--color-bg-surface)] text-[var(--color-text-secondary)] border border-[var(--color-border)]'"
          @click="mode = 'reuse'"
        >
          ⚡ 复用证据 (推荐)
        </button>
        <button
          type="button"
          class="px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all cursor-pointer"
          :class="mode === 'incremental' ? 'bg-[var(--color-brand-500)] text-white shadow-xs font-semibold' : 'bg-[var(--color-bg-surface)] text-[var(--color-text-secondary)] border border-[var(--color-border)]'"
          @click="mode = 'incremental'"
        >
          🔄 增量刷新
        </button>
        <button
          type="button"
          class="px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all cursor-pointer"
          :class="mode === 'new' ? 'bg-[var(--color-brand-500)] text-white shadow-xs font-semibold' : 'bg-[var(--color-bg-surface)] text-[var(--color-text-secondary)] border border-[var(--color-border)]'"
          @click="mode = 'new'"
        >
          ✨ 新建全量研究
        </button>
      </div>
    </div>

    <!-- Submit Button -->
    <div class="flex justify-end">
      <AdaptiveButton
        type="submit"
        variant="primary"
        size="lg"
        :loading="loading"
        :disabled="!query.trim()"
        :block="isMobile"
      >
        <span>🚀 开始美食深度研判</span>
      </AdaptiveButton>
    </div>
  </form>
</template>
