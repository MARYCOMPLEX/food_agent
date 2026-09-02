<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import AdaptiveContainer from '../../shared/ui/AdaptiveContainer.vue'
import AdaptiveButton from '../../shared/ui/AdaptiveButton.vue'
import EmptyState from '../../shared/ui/EmptyState.vue'
import SkeletonLoader from '../../shared/ui/SkeletonLoader.vue'
import { RestaurantCard, RestaurantDetailDrawer } from '../results'
import type { Restaurant } from '../../shared/contracts'
import { favoritesApi } from './api/favoritesApi'

const router = useRouter()

const items = ref<Restaurant[]>([])
const loading = ref(false)
const searchQuery = ref('')
const selectedTag = ref('all')
const selectedRestaurant = ref<Restaurant | null>(null)
const drawerOpen = ref(false)

async function loadFavorites() {
  loading.value = true
  try {
    const data = await favoritesApi.getFavorites()
    // Normalize items
    if (data?.items) {
      items.value = data.items.map((it: any) => {
        if (it.restaurant)
          return it.restaurant
        return {
          id: it.restaurant_id || it.id || `res_${Math.random().toString(36).substr(2, 6)}`,
          name: it.name || it.restaurant_name || '特色餐厅',
          chnName: it.chnName,
          price: it.price || '¥¥',
          trustScore: it.trustScore || 8.0,
          oneLiner: it.oneLiner || it.recommendation || '本地口碑极佳，招牌必点',
          tags: it.tags || ['特色美食', '本地推荐'],
          mustTry: it.mustTry || [],
          pros: it.pros || [],
          cons: it.cons || [],
          warning: it.warning,
          authenticity: it.authenticity || 'authentic',
          confidence: it.confidence || 0.88,
          updatedAt: it.updated_at || it.created_at,
        }
      })
    }
  }
  catch (err) {
    console.error('Failed to load favorites', err)
  }
  finally {
    loading.value = false
  }
}

const availableTags = computed(() => {
  const set = new Set<string>()
  items.value.forEach((r) => {
    r.tags?.forEach(t => set.add(t))
  })
  return ['all', ...Array.from(set)]
})

const filteredItems = computed(() => {
  return items.value.filter((r) => {
    const matchesSearch
      = !searchQuery.value.trim()
        || r.name.toLowerCase().includes(searchQuery.value.toLowerCase())
        || (r.chnName && r.chnName.toLowerCase().includes(searchQuery.value.toLowerCase()))
    const matchesTag = selectedTag.value === 'all' || r.tags?.includes(selectedTag.value)
    return matchesSearch && matchesTag
  })
})

function openDetail(r: Restaurant) {
  selectedRestaurant.value = r
  drawerOpen.value = true
}

async function handleToggleFavorite(r: Restaurant) {
  try {
    await favoritesApi.removeFavorite(r.id)
    items.value = items.value.filter(i => i.id !== r.id)
  }
  catch (err) {
    console.error('Remove favorite failed', err)
  }
}

function handleReStudy(r: Restaurant) {
  router.push({
    path: '/app/explore',
    query: { reSearch: r.name },
  })
}

onMounted(() => {
  loadFavorites()
})
</script>

<template>
  <AdaptiveContainer max-width="xl" class="space-y-6">
    <!-- Header -->
    <div class="flex flex-col md:flex-row md:items-center justify-between gap-4">
      <div>
        <h1 class="text-xl md:text-2xl font-bold text-[var(--color-text-primary)]">
          我的美食收藏
        </h1>
        <p class="text-xs md:text-sm text-[var(--color-text-secondary)] mt-0.5">
          保存的特色店铺与核验证据，支持随时复用与重新研判
        </p>
      </div>

      <AdaptiveButton
        variant="subtle"
        size="sm"
        @click="loadFavorites"
      >
        <span>🔄 刷新列表</span>
      </AdaptiveButton>
    </div>

    <!-- Filter & Search Controls -->
    <div class="p-3 bg-[var(--color-bg-surface)] rounded-xl border border-[var(--color-border)] flex flex-col sm:flex-row items-center gap-3">
      <!-- Search input -->
      <div class="relative flex-1 w-full">
        <input
          v-model="searchQuery"
          type="text"
          placeholder="按餐厅名称筛选..."
          class="w-full px-3 py-1.5 pl-8 text-xs md:text-sm rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-subtle)] outline-none focus:border-[var(--color-brand-500)] text-[var(--color-text-primary)]"
        >
        <span class="absolute left-2.5 top-2 text-xs text-[var(--color-text-tertiary)]">🔍</span>
      </div>

      <!-- Tag Filter -->
      <div v-if="availableTags.length > 1" class="flex items-center gap-1.5 overflow-x-auto w-full sm:w-auto">
        <button
          v-for="tag in availableTags"
          :key="tag"
          class="px-2.5 py-1 rounded-md text-xs font-medium transition-colors whitespace-nowrap cursor-pointer"
          :class="selectedTag === tag ? 'bg-[var(--color-brand-500)] text-white' : 'bg-[var(--color-neutral-150)] text-[var(--color-text-secondary)] hover:bg-[var(--color-neutral-200)]'"
          @click="selectedTag = tag"
        >
          {{ tag === 'all' ? '全部' : `#${tag}` }}
        </button>
      </div>
    </div>

    <!-- Loading Skeleton -->
    <SkeletonLoader v-if="loading" type="card" :count="4" />

    <!-- Grid List -->
    <div v-else-if="filteredItems.length" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      <RestaurantCard
        v-for="r in filteredItems"
        :key="r.id"
        :restaurant="r"
        :is-favorite="true"
        @click="openDetail(r)"
        @toggle-favorite="handleToggleFavorite"
      />
    </div>

    <!-- Empty State -->
    <EmptyState
      v-else
      icon="❤️"
      title="暂无收藏餐厅"
      description="在探索或研判会话中点击卡片右上角的心形图标即可收藏心仪店铺"
    >
      <template #action>
        <AdaptiveButton variant="primary" size="md" @click="router.push('/app/explore')">
          <span>去探索美食</span>
        </AdaptiveButton>
      </template>
    </EmptyState>

    <!-- Detail Drawer -->
    <RestaurantDetailDrawer
      v-model="drawerOpen"
      :restaurant="selectedRestaurant"
      @re-study="handleReStudy"
    />
  </AdaptiveContainer>
</template>
