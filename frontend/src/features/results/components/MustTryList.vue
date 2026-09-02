<script setup lang="ts">
import type { MustTryItem } from '../types'

defineProps<{
  items?: MustTryItem[]
}>()
</script>

<template>
  <div v-if="items && items.length" class="space-y-1.5">
    <div class="text-xs font-semibold text-emerald-700 flex items-center gap-1">
      <span>👍 必点推荐</span>
    </div>
    <div class="flex flex-wrap gap-1.5">
      <span
        v-for="(item, idx) in items"
        :key="idx"
        class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-emerald-50 text-emerald-800 border border-emerald-200"
      >
        <span class="font-medium">{{ item.name }}</span>
        <span v-if="item.reason" class="text-emerald-600 text-[11px]">({{ item.reason }})</span>
      </span>
    </div>
  </div>
</template>
