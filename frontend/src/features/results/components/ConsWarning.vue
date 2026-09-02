<script setup lang="ts">
import type { BlackListItem } from '../types'

defineProps<{
  warning?: string | null
  items?: BlackListItem[]
}>()
</script>

<template>
  <div v-if="warning || (items && items.length)" class="space-y-1.5">
    <div v-if="warning" class="p-2 rounded-lg bg-red-50 border border-red-200 text-xs text-red-800 flex items-start gap-1.5">
      <span class="text-red-500 font-bold shrink-0">⚠️ 避雷注意:</span>
      <span>{{ warning }}</span>
    </div>

    <div v-if="items && items.length" class="flex flex-wrap gap-1.5">
      <span
        v-for="(item, idx) in items"
        :key="idx"
        class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-red-50 text-red-700 border border-red-200 line-through"
      >
        <span>{{ item.name }}</span>
        <span v-if="item.reason" class="text-red-500 no-underline text-[10px]">({{ item.reason }})</span>
      </span>
    </div>
  </div>
</template>
