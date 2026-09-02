<script setup lang="ts">
import type { PromptTemplate } from '../types'

defineProps<{
  templates: PromptTemplate[]
}>()

const emit = defineEmits<{
  (e: 'select', template: PromptTemplate): void
}>()
</script>

<template>
  <div class="space-y-2">
    <div class="text-xs font-semibold text-[var(--color-text-tertiary)] flex items-center gap-1">
      <span>✨ 推荐探索主题:</span>
    </div>
    <div class="flex flex-wrap gap-2">
      <button
        v-for="(t, idx) in templates"
        :key="idx"
        class="px-3 py-1.5 rounded-full text-xs font-medium bg-[var(--color-neutral-150)] text-[var(--color-text-secondary)] hover:bg-[var(--color-brand-50)] hover:text-[var(--color-brand-700)] hover:border-[var(--color-brand-200)] border border-[var(--color-border)] transition-all cursor-pointer text-left active:scale-98"
        @click="emit('select', t)"
      >
        <span class="mr-1">🍜</span>
        <span>{{ t.title }}</span>
      </button>
    </div>
  </div>
</template>
