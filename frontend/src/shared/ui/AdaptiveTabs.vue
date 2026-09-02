<script setup lang="ts">
import { useDevice } from '../utils/device'

export interface TabItem {
  key: string
  label: string
  count?: number
  icon?: string
}

const props = defineProps<{
  tabs: TabItem[]
  modelValue: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', key: string): void
  (e: 'change', key: string): void
}>()

const { isMobile } = useDevice()

function select(key: string) {
  emit('update:modelValue', key)
  emit('change', key)
}
</script>

<template>
  <div
    class="flex border-b border-[var(--color-border)] overflow-x-auto no-scrollbar"
    :class="isMobile ? 'gap-1 px-1' : 'gap-2 px-2'"
  >
    <button
      v-for="tab in props.tabs"
      :key="tab.key"
      class="inline-flex items-center gap-1.5 py-2.5 px-3 font-medium text-sm whitespace-nowrap border-b-2 transition-all cursor-pointer relative"
      :class="[
        props.modelValue === tab.key
          ? 'border-[var(--color-brand-500)] text-[var(--color-brand-600)] font-semibold'
          : 'border-transparent text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)] hover:border-[var(--color-neutral-300)]',
      ]"
      @click="select(tab.key)"
    >
      <span v-if="tab.icon">{{ tab.icon }}</span>
      <span>{{ tab.label }}</span>
      <span
        v-if="tab.count !== undefined"
        class="ml-1 px-1.5 py-0.2 text-xs rounded-full"
        :class="props.modelValue === tab.key ? 'bg-[var(--color-brand-100)] text-[var(--color-brand-700)]' : 'bg-[var(--color-neutral-200)] text-[var(--color-text-tertiary)]'"
      >
        {{ tab.count }}
      </span>
    </button>
  </div>
</template>

<style scoped>
.no-scrollbar::-webkit-scrollbar {
  display: none;
}
.no-scrollbar {
  -ms-overflow-style: none;
  scrollbar-width: none;
}
</style>
