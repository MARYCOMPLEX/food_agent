<script setup lang="ts">
import { ref } from 'vue'
import AdaptiveButton from '../../../shared/ui/AdaptiveButton.vue'

const props = defineProps<{
  loading?: boolean
  disabled?: boolean
}>()

const emit = defineEmits<{
  (e: 'submit', query: string): void
}>()

const text = ref('')

function handleSubmit() {
  if (!text.value.trim() || props.loading || props.disabled)
    return
  emit('submit', text.value.trim())
  text.value = ''
}
</script>

<template>
  <form class="flex items-center gap-2 p-2 bg-[var(--color-bg-surface)] border border-[var(--color-border)] rounded-2xl shadow-md" @submit.prevent="handleSubmit">
    <input
      v-model="text"
      type="text"
      placeholder="继续追问，例如：'排除这几家，还有更便宜的吗？' 或 '推荐带包间的'..."
      class="flex-1 px-3 py-2 bg-transparent text-sm text-[var(--color-text-primary)] placeholder-[var(--color-text-tertiary)] outline-none"
      :disabled="loading || disabled"
    >
    <AdaptiveButton
      type="submit"
      variant="primary"
      size="sm"
      :loading="loading"
      :disabled="!text.trim() || disabled"
    >
      <span>追问</span>
    </AdaptiveButton>
  </form>
</template>
