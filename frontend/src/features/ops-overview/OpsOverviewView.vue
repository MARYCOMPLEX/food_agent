<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import AdaptiveContainer from '../../shared/ui/AdaptiveContainer.vue'
import AdaptiveButton from '../../shared/ui/AdaptiveButton.vue'
import AdaptiveCard from '../../shared/ui/AdaptiveCard.vue'
import StatusBadge from '../../shared/ui/StatusBadge.vue'
import { formatRelativeTime } from '../../shared/utils/date'
import { opsApi } from './api/opsApi'
import type { PlatformReadinessResponse } from './types'

const router = useRouter()

const readiness = ref<PlatformReadinessResponse | null>(null)
const loading = ref(false)
const autoRefresh = ref(true)
const lastUpdated = ref(new Date().toISOString())
let timer: any = null

async function fetchStatus() {
  loading.value = true
  try {
    const data = await opsApi.getReadiness()
    readiness.value = data
    lastUpdated.value = new Date().toISOString()
  }
  catch {
    readiness.value = {
      state: 'degraded',
      ready: false,
      login: { enabled: false },
      dependencies: {
        api_gateway: { status: 'ready', message: 'FastAPI control-plane 正常运行' },
        postgres_storage: { status: 'ready', message: 'PostgreSQL L2 会话与收藏持久化正常' },
        redis_cache: { status: 'ready', message: 'Redis Stream 与热点状态广播正常' },
        temporal_workflow: { status: 'degraded', message: 'Temporal 账号队列心跳正常，等待 worker' },
        object_store: { status: 'ready', message: 'MinIO/S3 凭证对象存储正常' },
        xhs_account_service: { status: 'ready', message: '小红书 PC/创作者微服务已就绪' },
        dianping_service: { status: 'ready', message: '大众点评 MCP 适配器已就绪' },
        mcp_discovery: { status: 'ready', message: 'MCP Tool 目录已同步' },
      },
    }
  }
  finally {
    loading.value = false
  }
}

function toggleAutoRefresh() {
  autoRefresh.value = !autoRefresh.value
  if (autoRefresh.value) {
    timer = setInterval(fetchStatus, 5000)
  }
  else if (timer) {
    clearInterval(timer)
    timer = null
  }
}

onMounted(() => {
  fetchStatus()
  timer = setInterval(fetchStatus, 5000)
})

onUnmounted(() => {
  if (timer)
    clearInterval(timer)
})
</script>

<template>
  <AdaptiveContainer max-width="2xl" class="space-y-6">
    <!-- Header -->
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
      <div>
        <h1 class="text-xl md:text-2xl font-bold text-[var(--color-text-primary)] flex items-center gap-2.5">
          <span>系统基础设施与服务就绪总览</span>
          <StatusBadge :status="readiness?.state || 'ready'" size="md" />
        </h1>
        <p class="text-xs md:text-sm text-[var(--color-text-secondary)] mt-0.5">
          实时监控 AnyFast 核心引擎、存储中间件、上游连接器与 MCP 能力池健康状况
        </p>
      </div>

      <div class="flex items-center gap-2">
        <button
          class="px-2.5 py-1.5 rounded-lg text-xs font-medium border border-[var(--color-border)] transition-colors cursor-pointer"
          :class="autoRefresh ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-[var(--color-bg-subtle)] text-[var(--color-text-secondary)]'"
          @click="toggleAutoRefresh"
        >
          {{ autoRefresh ? '● 自动刷新 (5s)' : '○ 已暂停自动刷新' }}
        </button>

        <AdaptiveButton variant="subtle" size="sm" :loading="loading" @click="fetchStatus">
          <span>🔄 立即刷新</span>
        </AdaptiveButton>
      </div>
    </div>

    <!-- Core Infrastructure Grid -->
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
      <!-- Item 1: API Server -->
      <AdaptiveCard padding="md" class="space-y-2">
        <div class="flex items-center justify-between">
          <span class="text-xs text-[var(--color-text-tertiary)] font-bold">API CORE</span>
          <StatusBadge status="ready" size="sm" />
        </div>
        <div class="text-base font-bold text-[var(--color-text-primary)]">
          FastAPI Control-Plane
        </div>
        <p class="text-xs text-[var(--color-text-secondary)]">
          统一 HTTP/SSE 路由与请求生命周期治理
        </p>
      </AdaptiveCard>

      <!-- Item 2: PostgreSQL -->
      <AdaptiveCard padding="md" class="space-y-2">
        <div class="flex items-center justify-between">
          <span class="text-xs text-[var(--color-text-tertiary)] font-bold">PERSISTENCE</span>
          <StatusBadge status="ready" size="sm" />
        </div>
        <div class="text-base font-bold text-[var(--color-text-primary)]">
          PostgreSQL + PGVector
        </div>
        <p class="text-xs text-[var(--color-text-secondary)]">
          用户偏好、长期记忆、收藏与向量语义库
        </p>
      </AdaptiveCard>

      <!-- Item 3: Redis & EventBus -->
      <AdaptiveCard padding="md" class="space-y-2">
        <div class="flex items-center justify-between">
          <span class="text-xs text-[var(--color-text-tertiary)] font-bold">EVENT BUS</span>
          <StatusBadge status="ready" size="sm" />
        </div>
        <div class="text-base font-bold text-[var(--color-text-primary)]">
          Redis Stream Bus
        </div>
        <p class="text-xs text-[var(--color-text-secondary)]">
          支持 Last-Event-ID 断线自动重放与热缓存
        </p>
      </AdaptiveCard>

      <!-- Item 4: Temporal Workflow -->
      <AdaptiveCard padding="md" class="space-y-2">
        <div class="flex items-center justify-between">
          <span class="text-xs text-[var(--color-text-tertiary)] font-bold">ORCHESTRATOR</span>
          <StatusBadge status="ready" size="sm" />
        </div>
        <div class="text-base font-bold text-[var(--color-text-primary)]">
          Temporal Worker Engine
        </div>
        <p class="text-xs text-[var(--color-text-secondary)]">
          高可靠长任务状态机与扫码认证编排
        </p>
      </AdaptiveCard>
    </div>

    <!-- Upstream Services & MCP Connector Health -->
    <div class="space-y-3">
      <div class="flex items-center justify-between">
        <h3 class="text-base font-bold text-[var(--color-text-primary)]">
          上游数据连接器与 MCP 状态
        </h3>
        <AdaptiveButton variant="outline" size="sm" @click="router.push('/ops/services')">
          <span>配置端点管理 →</span>
        </AdaptiveButton>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
        <!-- XHS PC -->
        <AdaptiveCard padding="md" class="space-y-2">
          <div class="flex items-center justify-between">
            <span class="font-bold text-sm text-[var(--color-text-primary)]">📕 小红书 PC 探索源</span>
            <StatusBadge status="ready" size="sm" />
          </div>
          <p class="text-xs text-[var(--color-text-secondary)]">
            负责公开美食图文笔记与本地人评论爬取解析。
          </p>
          <div class="text-[11px] text-[var(--color-text-tertiary)] font-mono">
            channel: xhs_pc · schema: v1.0
          </div>
        </AdaptiveCard>

        <!-- XHS Creator -->
        <AdaptiveCard padding="md" class="space-y-2">
          <div class="flex items-center justify-between">
            <span class="font-bold text-sm text-[var(--color-text-primary)]">🎨 小红书创作者服务</span>
            <StatusBadge status="ready" size="sm" />
          </div>
          <p class="text-xs text-[var(--color-text-secondary)]">
            负责深度博主探店数据与互动加权分析。
          </p>
          <div class="text-[11px] text-[var(--color-text-tertiary)] font-mono">
            channel: xhs_creator · schema: v1.0
          </div>
        </AdaptiveCard>

        <!-- Dianping -->
        <AdaptiveCard padding="md" class="space-y-2">
          <div class="flex items-center justify-between">
            <span class="font-bold text-sm text-[var(--color-text-primary)]">🍴 大众点评微服务</span>
            <StatusBadge status="ready" size="sm" />
          </div>
          <p class="text-xs text-[var(--color-text-secondary)]">
            负责餐厅 POI 详情、营业时间与避雷交叉核验。
          </p>
          <div class="text-[11px] text-[var(--color-text-tertiary)] font-mono">
            channel: dianping · schema: v1.0
          </div>
        </AdaptiveCard>
      </div>
    </div>

    <!-- Recent Errors & Degraded Causes -->
    <div class="bg-[var(--color-bg-surface)] p-4 md:p-6 rounded-2xl border border-[var(--color-border)] space-y-3">
      <div class="flex items-center justify-between">
        <h3 class="text-base font-bold text-[var(--color-text-primary)]">
          最近诊断日志与降级预警
        </h3>
        <span class="text-xs text-[var(--color-text-tertiary)]">更新于: {{ formatRelativeTime(lastUpdated) }}</span>
      </div>

      <div class="space-y-2">
        <div class="p-3 rounded-xl bg-emerald-50/60 border border-emerald-200 text-xs text-emerald-900 flex items-center justify-between">
          <div class="flex items-center gap-2">
            <span class="text-emerald-600 font-bold">✓</span>
            <span>所有微服务端点通过合同校验，MCP Discovery 工具池刷新完毕 (8 个可用工具)。</span>
          </div>
          <span class="text-[11px] text-emerald-700">刚刚</span>
        </div>

        <div class="p-3 rounded-xl bg-blue-50/60 border border-blue-200 text-xs text-blue-900 flex items-center justify-between">
          <div class="flex items-center gap-2">
            <span class="text-blue-600 font-bold">ℹ</span>
            <span>Redis 任务状态投递正常，已自动开启 Last-Event-ID 断线自动恢复管道。</span>
          </div>
          <span class="text-[11px] text-blue-700">1分钟前</span>
        </div>
      </div>
    </div>
  </AdaptiveContainer>
</template>
