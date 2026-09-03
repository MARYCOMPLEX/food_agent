<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AdaptiveContainer from '../../shared/ui/AdaptiveContainer.vue'
import { RestaurantCard, RestaurantDetailDrawer } from '../results'
import { useSSEStream } from '../../shared/sse/useSSEStream'
import type { LoadingStep, Restaurant } from '../../shared/contracts'
import SessionHeader from './components/SessionHeader.vue'
import StepTimeline from './components/StepTimeline.vue'
import FollowUpInput from './components/FollowUpInput.vue'
import { sessionApi } from './api/sessionApi'

const route = useRoute()
const router = useRouter()

const sessionId = ref(route.params.sessionId as string)
const selectedRestaurant = ref<Restaurant | null>(null)
const drawerOpen = ref(false)
const followUpLoading = ref(false)
const dialogueHistory = ref<Array<{ role: 'user' | 'assistant', content: string, turnId?: number }>>([])

// Default initial steps placeholder
const initialSteps: LoadingStep[] = [
  { id: 'intent_parser', label: '🧠 意图解析：解析地理位置与口味偏好', status: 'loading' },
  { id: 'search', label: '🔍 笔记检索：抓取小红书与大众点评真实内容', status: 'pending' },
  { id: 'analyzer', label: '📊 口碑分析：识别网红套路与本地人真实好评', status: 'pending' },
  { id: 'verifier', label: '🛡️ 交叉核验：多源比对价格、营业状态与避雷项', status: 'pending' },
  { id: 'shop_profile_enrichment', label: '📍 大众点评档案：补齐地址、菜品、图片与营业信息', status: 'pending' },
]

const {
  connectionState,
  steps,
  restaurants,
  summary,
  isComplete,
  start: startSSE,
  stop: stopSSE,
} = useSSEStream(sessionId.value, {
  sseVersion: 'v1',
  autoReconnect: true,
  onResult: (_results, resSummary) => {
    if (resSummary && !dialogueHistory.value.some(d => d.content === resSummary)) {
      dialogueHistory.value.push({ role: 'assistant', content: resSummary })
    }
  },
})

function openDetail(r: Restaurant) {
  selectedRestaurant.value = r
  drawerOpen.value = true
}

async function handleFollowUp(queryText: string) {
  dialogueHistory.value.push({ role: 'user', content: queryText })
  followUpLoading.value = true
  try {
    await sessionApi.refineQuery(sessionId.value, queryText)
    // Restart stream to capture new turn events
    startSSE()
  }
  catch (err) {
    console.error('Refine failed', err)
  }
  finally {
    followUpLoading.value = false
  }
}

async function loadExistingState() {
  try {
    const statusData = await sessionApi.getStatus(sessionId.value)
    if (statusData?.steps && statusData.steps.length) {
      steps.value = statusData.steps
    }
    const resultsData = await sessionApi.getResults(sessionId.value)
    if (resultsData?.recommendations && resultsData.recommendations.length) {
      restaurants.value = resultsData.recommendations
      if (resultsData.summary) {
        summary.value = resultsData.summary
      }
    }
  }
  catch {
    // start SSE directly
  }
}

function handleReStudy(r: Restaurant) {
  router.push({
    path: '/app/explore',
    query: { reSearch: r.name },
  })
}

onMounted(async () => {
  steps.value = initialSteps
  await loadExistingState()
  startSSE()
})

watch(
  () => route.params.sessionId,
  (newId) => {
    if (newId && typeof newId === 'string' && newId !== sessionId.value) {
      sessionId.value = newId
      stopSSE()
      loadExistingState()
      startSSE()
    }
  },
)
</script>

<template>
  <AdaptiveContainer max-width="xl" class="space-y-6 pb-20">
    <!-- Header -->
    <SessionHeader
      :session-id="sessionId"
      :connection-state="connectionState"
      :is-complete="isComplete"
      @reconnect="startSSE"
    />

    <!-- Multi-turn Conversation & Summary -->
    <div v-if="dialogueHistory.length || summary" class="space-y-3">
      <div
        v-for="(msg, idx) in dialogueHistory"
        :key="idx"
        class="p-3.5 rounded-xl text-sm"
        :class="msg.role === 'user' ? 'bg-[var(--color-brand-50)] text-[var(--color-brand-900)] ml-auto max-w-lg' : 'bg-[var(--color-bg-surface)] border border-[var(--color-border)] mr-auto max-w-2xl'"
      >
        <div class="text-[11px] font-bold mb-1 opacity-70">
          {{ msg.role === 'user' ? '👤 您的追问' : '🤖 AnyFast 美食研判建议' }}
        </div>
        <p class="leading-relaxed">
          {{ msg.content }}
        </p>
      </div>

      <!-- Main Agent Summary -->
      <div v-if="summary && !dialogueHistory.some(d => d.content === summary)" class="p-4 rounded-2xl bg-gradient-to-r from-blue-50/80 to-indigo-50/80 border border-blue-200">
        <div class="text-xs font-bold text-blue-900 mb-1 flex items-center gap-1.5">
          <span>✨ 研判结论摘要</span>
        </div>
        <p class="text-sm text-blue-950 leading-relaxed">
          {{ summary }}
        </p>
      </div>
    </div>

    <!-- Agent Progress Timeline -->
    <StepTimeline :steps="steps.length ? steps : initialSteps" :is-complete="isComplete" />

    <!-- Results Grid -->
    <div class="space-y-3">
      <div class="flex items-center justify-between">
        <h3 class="font-bold text-base md:text-lg text-[var(--color-text-primary)] flex items-center gap-2">
          <span>🍽️ 推荐特色餐厅</span>
          <span v-if="restaurants.length" class="text-xs px-2 py-0.5 rounded-full bg-[var(--color-brand-100)] text-[var(--color-brand-700)] font-semibold">
            {{ restaurants.length }} 家
          </span>
        </h3>
        <span class="text-xs text-[var(--color-text-tertiary)]">点击卡片展开证据详情</span>
      </div>

      <div v-if="restaurants.length" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <RestaurantCard
          v-for="r in restaurants"
          :key="r.id"
          :restaurant="r"
          @click="openDetail(r)"
        />
      </div>

      <div v-else-if="!isComplete" class="p-8 text-center bg-[var(--color-bg-surface)] border border-[var(--color-border)] rounded-2xl">
        <div class="inline-block w-8 h-8 border-3 border-[var(--color-brand-500)] border-t-transparent rounded-full animate-spin mb-3" />
        <p class="text-sm text-[var(--color-text-secondary)]">
          正在抓取并核验多源美食数据，请稍候...
        </p>
      </div>

      <div v-else class="p-8 text-center bg-[var(--color-bg-surface)] border border-[var(--color-border)] rounded-2xl text-[var(--color-text-secondary)] text-sm">
        未找到完全匹配的特色餐厅，建议调整查询条件后重试。
      </div>
    </div>

    <!-- Sticky Bottom Follow-up Input Bar -->
    <div class="fixed bottom-0 md:bottom-4 inset-x-0 md:max-w-2xl md:mx-auto px-4 z-30">
      <FollowUpInput
        :loading="followUpLoading"
        @submit="handleFollowUp"
      />
    </div>

    <!-- Restaurant Detail Drawer -->
    <RestaurantDetailDrawer
      v-model="drawerOpen"
      :restaurant="selectedRestaurant"
      @re-study="handleReStudy"
    />
  </AdaptiveContainer>
</template>
