<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    score?: number
    size?: 'sm' | 'md' | 'lg'
  }>(),
  {
    score: 0,
    size: 'md',
  },
)

const scoreColor = computed(() => {
  const s = props.score || 0
  if (s >= 8.5)
    return 'bg-emerald-500 text-white'
  if (s >= 7.0)
    return 'bg-teal-500 text-white'
  if (s >= 5.0)
    return 'bg-amber-500 text-white'
  return 'bg-red-500 text-white'
})
</script>

<template>
  <div
    class="inline-flex items-center gap-1 rounded-md font-bold select-none"
    :class="[
      scoreColor,
      size === 'sm' && 'px-1.5 py-0.5 text-xs',
      size === 'md' && 'px-2 py-0.5 text-sm',
      size === 'lg' && 'px-2.5 py-1 text-base',
    ]"
  >
    <span class="text-xs">★</span>
    <span>{{ Number(score || 0).toFixed(1) }}</span>
  </div>
</template>
