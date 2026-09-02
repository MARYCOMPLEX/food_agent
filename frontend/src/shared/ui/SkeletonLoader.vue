<script setup lang="ts">
withDefaults(
  defineProps<{
    type?: 'card' | 'list' | 'text'
    count?: number
  }>(),
  {
    type: 'card',
    count: 3,
  },
)
</script>

<template>
  <div class="space-y-3">
    <template v-if="type === 'card'">
      <div
        v-for="i in count"
        :key="i"
        class="bg-[var(--color-bg-surface)] border border-[var(--color-border)] rounded-card p-4 animate-pulse"
      >
        <div class="flex items-center space-x-3 mb-3">
          <div class="w-10 h-10 bg-[var(--color-neutral-200)] rounded-lg" />
          <div class="flex-1 space-y-2">
            <div class="h-4 bg-[var(--color-neutral-200)] rounded w-1/3" />
            <div class="h-3 bg-[var(--color-neutral-200)] rounded w-1/2" />
          </div>
        </div>
        <div class="h-3 bg-[var(--color-neutral-200)] rounded w-full mb-2" />
        <div class="h-3 bg-[var(--color-neutral-200)] rounded w-4/5" />
      </div>
    </template>

    <template v-else-if="type === 'list'">
      <div
        v-for="i in count"
        :key="i"
        class="flex items-center space-x-3 p-3 bg-[var(--color-bg-surface)] border border-[var(--color-border)] rounded-lg animate-pulse"
      >
        <div class="w-8 h-8 bg-[var(--color-neutral-200)] rounded-full" />
        <div class="flex-1 space-y-1.5">
          <div class="h-4 bg-[var(--color-neutral-200)] rounded w-1/4" />
          <div class="h-3 bg-[var(--color-neutral-200)] rounded w-3/4" />
        </div>
      </div>
    </template>

    <template v-else>
      <div v-for="i in count" :key="i" class="space-y-2 animate-pulse">
        <div class="h-4 bg-[var(--color-neutral-200)] rounded w-3/4" />
        <div class="h-4 bg-[var(--color-neutral-200)] rounded w-full" />
        <div class="h-4 bg-[var(--color-neutral-200)] rounded w-1/2" />
      </div>
    </template>
  </div>
</template>
