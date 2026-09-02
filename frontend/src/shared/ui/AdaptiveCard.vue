<script setup lang="ts">
import { useDevice } from '../utils/device'

withDefaults(
  defineProps<{
    interactive?: boolean
    padding?: 'none' | 'sm' | 'md' | 'lg'
  }>(),
  {
    interactive: false,
    padding: 'md',
  },
)

const { isMobile } = useDevice()
</script>

<template>
  <div
    class="bg-[var(--color-bg-surface)] border border-[var(--color-border)] rounded-card transition-all"
    :class="[
      interactive && 'hover:border-[var(--color-brand-300)] hover:shadow-md cursor-pointer active:scale-[0.99]',
      padding === 'none' && '',
      padding === 'sm' && (isMobile ? 'p-3' : 'p-4'),
      padding === 'md' && (isMobile ? 'p-4' : 'p-5'),
      padding === 'lg' && (isMobile ? 'p-5' : 'p-6'),
    ]"
  >
    <slot />
  </div>
</template>
