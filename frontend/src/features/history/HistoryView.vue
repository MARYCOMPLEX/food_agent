<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import AdaptiveContainer from '../../shared/ui/AdaptiveContainer.vue'
import AdaptiveButton from '../../shared/ui/AdaptiveButton.vue'
import AdaptiveCard from '../../shared/ui/AdaptiveCard.vue'
import AdaptiveModal from '../../shared/ui/AdaptiveModal.vue'
import EmptyState from '../../shared/ui/EmptyState.vue'
import SkeletonLoader from '../../shared/ui/SkeletonLoader.vue'
import type { HistoryItem } from '../../shared/contracts'
import { formatRelativeTime } from '../../shared/utils/date'
import { historyApi } from './api/historyApi'

const router = useRouter()

const items = ref<HistoryItem[]>([])
const loading = ref(false)
const searchQuery = ref('')
const clearModalOpen = ref(false)
const clearing = ref(false)

async function loadHistory() {
  loading.value = true
  try {
    const data = await historyApi.getHistory()
    items.value = data?.items || []
  }
  catch (err) {
    console.error('Failed to load history', err)
  }
  finally {
    loading.value = false
  }
}

const filteredItems = computed(() => {
  if (!searchQuery.value.trim())
    return items.value
  return items.value.filter(i =>
    i.query.toLowerCase().includes(searchQuery.value.toLowerCase()),
  )
})

function openSession(item: HistoryItem) {
  if (item.session_id) {
    router.push(`/app/sessions/${item.session_id}`)
  }
  else {
    // Re-launch search with query
    router.push({
      path: '/app/explore',
      query: { q: item.query },
    })
  }
}

async function handleDelete(item: HistoryItem, e: MouseEvent) {
  e.stopPropagation()
  try {
    await historyApi.deleteHistoryItem(item.id)
    items.value = items.value.filter(i => i.id !== item.id)
  }
  catch (err) {
    console.error('Delete item failed', err)
  }
}

async function handleClearAll() {
  clearing.value = true
  try {
    await historyApi.clearHistory()
    items.value = []
    clearModalOpen.value = false
  }
  catch (err) {
    console.error('Clear history failed', err)
  }
  finally {
    clearing.value = false
  }
}

onMounted(() => {
  loadHistory()
})
</script>

<template>
  <AdaptiveContainer max-width="lg" class="space-y-6">
    <!-- Header -->
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
      <div>
        <h1 class="text-xl md:text-2xl font-bold text-[var(--color-text-primary)]">
          历史搜索与研究
        </h1>
        <p class="text-xs md:text-sm text-[var(--color-text-secondary)] mt-0.5">
          查看往期美食研判会话与追问记录，支持一键恢复或重新发起
        </p>
      </div>

      <div class="flex items-center gap-2">
        <AdaptiveButton
          variant="subtle"
          size="sm"
          @click="loadHistory"
        >
          <span>🔄 刷新</span>
        </AdaptiveButton>

        <AdaptiveButton
          v-if="items.length"
          variant="outline"
          size="sm"
          class="text-red-600 border-red-200 hover:bg-red-50"
          @click="clearModalOpen = true"
        >
          <span>🗑️ 清空历史</span>
        </AdaptiveButton>
      </div>
    </div>

    <!-- Search input -->
    <div v-if="items.length" class="relative">
      <input
        v-model="searchQuery"
        type="text"
        placeholder="搜索历史记录关键字..."
        class="w-full px-4 py-2.5 pl-10 text-xs md:text-sm rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-surface)] outline-none focus:border-[var(--color-brand-500)] text-[var(--color-text-primary)] shadow-xs"
      >
      <span class="absolute left-3.5 top-3 text-xs text-[var(--color-text-tertiary)]">🔍</span>
    </div>

    <!-- Skeleton -->
    <SkeletonLoader v-if="loading" type="list" :count="5" />

    <!-- History List -->
    <div v-else-if="filteredItems.length" class="space-y-2.5">
      <AdaptiveCard
        v-for="item in filteredItems"
        :key="item.id"
        :interactive="true"
        padding="sm"
        class="flex items-center justify-between gap-3 group hover:border-[var(--color-brand-400)]"
        @click="openSession(item)"
      >
        <div class="flex items-start gap-3 min-w-0 flex-1">
          <div class="w-9 h-9 rounded-lg bg-[var(--color-brand-50)] text-[var(--color-brand-600)] flex items-center justify-center text-base shrink-0 mt-0.5">
            🍜
          </div>
          <div class="min-w-0 flex-1">
            <h4 class="font-bold text-sm text-[var(--color-text-primary)] group-hover:text-[var(--color-brand-600)] transition-colors truncate">
              {{ item.query }}
            </h4>
            <div class="flex items-center gap-3 text-[11px] text-[var(--color-text-tertiary)] mt-1">
              <span>🕒 {{ formatRelativeTime(item.created_at) }}</span>
              <span v-if="item.location">📍 {{ item.location }}</span>
              <span v-if="item.results_count">📊 匹配 {{ item.results_count }} 家餐厅</span>
            </div>
          </div>
        </div>

        <div class="flex items-center gap-2 shrink-0">
          <AdaptiveButton
            variant="subtle"
            size="sm"
            @click.stop="openSession(item)"
          >
            <span>恢复会话</span>
          </AdaptiveButton>
          <button
            class="p-1.5 rounded-md text-[var(--color-text-tertiary)] hover:text-red-500 hover:bg-red-50 transition-colors cursor-pointer"
            title="删除此记录"
            @click="(e) => handleDelete(item, e)"
          >
            🗑️
          </button>
        </div>
      </AdaptiveCard>
    </div>

    <!-- Empty State -->
    <EmptyState
      v-else
      icon="🕒"
      title="暂无搜索历史"
      description="您的所有美食探索与追问会话将自动记录在此处"
    >
      <template #action>
        <AdaptiveButton variant="primary" size="md" @click="router.push('/app/explore')">
          <span>开始新的探索</span>
        </AdaptiveButton>
      </template>
    </EmptyState>

    <!-- Clear Modal -->
    <AdaptiveModal
      v-model="clearModalOpen"
      title="清空全部搜索历史"
      width="400px"
    >
      <p class="text-sm text-[var(--color-text-secondary)] leading-relaxed">
        确定要清空所有历史搜索记录吗？该操作不可撤销。
      </p>
      <template #footer>
        <AdaptiveButton variant="outline" size="sm" @click="clearModalOpen = false">
          <span>取消</span>
        </AdaptiveButton>
        <AdaptiveButton variant="danger" size="sm" :loading="clearing" @click="handleClearAll">
          <span>确认清空</span>
        </AdaptiveButton>
      </template>
    </AdaptiveModal>
  </AdaptiveContainer>
</template>
