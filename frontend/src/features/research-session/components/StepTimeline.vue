<script setup lang="ts">
import type { LoadingStep } from '../types'

defineProps<{
  steps: LoadingStep[]
  isComplete?: boolean
}>()

const defaultStepLabels: Record<string, string> = {
  intent_parser: '🧠 意图解析：解析地理位置与口味偏好',
  search: '🔍 笔记检索：抓取小红书与大众点评真实内容',
  analyzer: '📊 口碑分析：识别网红套路与本地人真实好评',
  verifier: '🛡️ 交叉核验：多源比对价格、营业状态与避雷项',
  poi_enricher: '📍 POI 补充：补齐地址、电话与经纬度坐标',
}

function getStepLabel(step: LoadingStep): string {
  return step.label || defaultStepLabels[step.id] || step.id
}
</script>

<template>
  <div class="bg-[var(--color-bg-subtle)] p-4 rounded-xl border border-[var(--color-border)] space-y-3">
    <div class="flex items-center justify-between">
      <div class="text-xs font-bold text-[var(--color-text-primary)] flex items-center gap-1.5">
        <span class="inline-block w-2 h-2 rounded-full" :class="isComplete ? 'bg-emerald-500' : 'bg-[var(--color-brand-500)] animate-ping'" />
        <span>Agent 研判进度</span>
      </div>
      <span class="text-xs text-[var(--color-text-tertiary)]">
        {{ isComplete ? '全部研判流程完成' : '多智能体协作中...' }}
      </span>
    </div>

    <div class="space-y-2">
      <div
        v-for="step in steps"
        :key="step.id"
        class="flex items-start gap-2.5 text-xs transition-all"
      >
        <div class="mt-0.5 shrink-0">
          <span v-if="step.status === 'done'" class="text-emerald-500 font-bold text-sm">✓</span>
          <span v-else-if="step.status === 'loading'" class="inline-block w-3.5 h-3.5 border-2 border-[var(--color-brand-500)] border-t-transparent rounded-full animate-spin" />
          <span v-else-if="step.status === 'error'" class="text-red-500 font-bold text-sm">✕</span>
          <span v-else class="text-[var(--color-neutral-400)] text-sm">•</span>
        </div>

        <div class="flex-1 min-w-0">
          <div
            class="font-medium"
            :class="[
              step.status === 'done' && 'text-emerald-800',
              step.status === 'loading' && 'text-[var(--color-brand-700)] font-semibold',
              step.status === 'error' && 'text-red-700',
              step.status === 'pending' && 'text-[var(--color-text-tertiary)]',
            ]"
          >
            {{ getStepLabel(step) }}
          </div>
          <div v-if="step.detail" class="text-[11px] text-[var(--color-text-secondary)] mt-0.5">
            {{ step.detail }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
