<script setup lang="ts">
import { useRouter } from 'vue-router'

const props = withDefaults(
  defineProps<{
    title?: string
    showBack?: boolean
  }>(),
  {
    title: '',
    showBack: false,
  },
)

const router = useRouter()

function handleBack() {
  if (window.history.length > 1) {
    router.back()
  }
  else {
    router.push('/app/explore')
  }
}
</script>

<template>
  <header class="sticky top-0 z-40 bg-[var(--color-bg-surface)]/95 backdrop-blur-md border-b border-[var(--color-border)] px-4 h-12 flex items-center justify-between">
    <div class="flex items-center gap-2">
      <button
        v-if="props.showBack"
        class="p-1.5 -ml-1 text-[var(--color-text-primary)] hover:bg-[var(--color-neutral-150)] rounded-full cursor-pointer"
        @click="handleBack"
      >
        <span class="text-lg">←</span>
      </button>
      <h1 class="text-base font-semibold text-[var(--color-text-primary)] truncate">
        {{ props.title }}
      </h1>
    </div>
    <div class="flex items-center gap-2">
      <slot name="actions" />
    </div>
  </header>
</template>
