<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    status?: string
    text?: string
    size?: 'sm' | 'md'
  }>(),
  {
    status: 'ready',
    size: 'sm',
  },
)

const config = computed(() => {
  switch (props.status?.toLowerCase()) {
    case 'ready':
    case 'active':
    case 'success':
    case 'healthy':
    case 'done':
      return {
        bg: 'bg-emerald-50 text-emerald-700 border-emerald-200',
        dot: 'bg-emerald-500',
        label: props.text || '正常就绪',
      }
    case 'degraded':
    case 'warning':
    case 'polling':
    case 'loading':
      return {
        bg: 'bg-amber-50 text-amber-700 border-amber-200',
        dot: 'bg-amber-500 animate-pulse',
        label: props.text || '降级运行',
      }
    case 'dependency-unavailable':
    case 'unavailable':
    case 'risk':
    case 'critical':
      return {
        bg: 'bg-orange-50 text-orange-700 border-orange-200',
        dot: 'bg-orange-500',
        label: props.text || '依赖不可用',
      }
    case 'disabled':
    case 'expired':
    case 'cancelled':
      return {
        bg: 'bg-gray-100 text-gray-600 border-gray-200',
        dot: 'bg-gray-400',
        label: props.text || '已停用',
      }
    case 'failed':
    case 'error':
      return {
        bg: 'bg-red-50 text-red-700 border-red-200',
        dot: 'bg-red-500',
        label: props.text || '执行失败',
      }
    default:
      return {
        bg: 'bg-blue-50 text-blue-700 border-blue-200',
        dot: 'bg-blue-500',
        label: props.text || props.status || '未知',
      }
  }
})
</script>

<template>
  <span
    class="inline-flex items-center gap-1.5 font-medium border rounded-full select-none"
    :class="[
      config.bg,
      size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-3 py-1 text-sm',
    ]"
  >
    <span class="w-1.5 h-1.5 rounded-full" :class="config.dot" />
    <span>{{ config.label }}</span>
  </span>
</template>
