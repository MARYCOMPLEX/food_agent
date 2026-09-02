<script setup lang="ts">
defineProps<{
  title?: string
  description?: string
  icon?: string
}>()
</script>

<template>
  <div class="flex flex-col items-center justify-center py-12 px-4 text-center">
    <div class="w-16 h-16 rounded-full bg-[var(--color-neutral-150)] flex items-center justify-center text-2xl text-[var(--color-text-tertiary)] mb-4">
      <slot name="icon">
        <span>{{ icon || '🔍' }}</span>
      </slot>
    </div>
    <h3 class="text-base font-semibold text-[var(--color-text-primary)] mb-1">
      {{ title || '暂无数据' }}
    </h3>
    <p v-if="description" class="text-sm text-[var(--color-text-secondary)] max-w-sm mb-4">
      {{ description }}
    </p>
    <div v-if="$slots.action" class="mt-2">
      <slot name="action" />
    </div>
  </div>
</template>
