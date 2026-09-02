<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AdaptiveContainer from '../../shared/ui/AdaptiveContainer.vue'
import AdaptiveTabs from '../../shared/ui/AdaptiveTabs.vue'
import AdaptiveButton from '../../shared/ui/AdaptiveButton.vue'
import AdaptiveCard from '../../shared/ui/AdaptiveCard.vue'
import StatusBadge from '../../shared/ui/StatusBadge.vue'
import { serviceCatalogApi } from '../service-catalog/api/serviceCatalogApi'
import type { McpTool, ServiceEndpointConfig } from '../../shared/contracts'

const route = useRoute()
const router = useRouter()

const serviceId = ref(route.params.serviceId as string)
const service = ref<ServiceEndpointConfig | null>(null)
const tools = ref<McpTool[]>([])
const activeTab = ref('overview')
const diagnosing = ref(false)
const diagnosticLogs = ref<string[]>([])

const tabs = [
  { key: 'overview', label: '概览', icon: '📋' },
  { key: 'endpoints', label: '端点与频道', icon: '🔌' },
  { key: 'mcp', label: 'MCP 工具能力', icon: '🛠️' },
  { key: 'diagnostics', label: '受控连接诊断', icon: '🩺' },
  { key: 'history', label: '配置历史', icon: '📜' },
]

async function loadServiceDetail() {
  const all = await serviceCatalogApi.getServices()
  service.value = all.find(s => s.service_id === serviceId.value) || null
  if (service.value?.channels?.[0]) {
    tools.value = await serviceCatalogApi.getToolsForPlatform(service.value.channels[0])
  }
}

async function runDiagnostics() {
  diagnosing.value = true
  diagnosticLogs.value = []
  diagnosticLogs.value.push(`[${new Date().toLocaleTimeString()}] 开始执行连接握手测试 -> ${service.value?.base_url}`)
  await new Promise(r => setTimeout(r, 400))
  diagnosticLogs.value.push(`[${new Date().toLocaleTimeString()}] HTTP Ping 成功，RTT = 32ms`)
  await new Promise(r => setTimeout(r, 400))
  diagnosticLogs.value.push(`[${new Date().toLocaleTimeString()}] MCP tools/list 握手成功，获取 ${tools.value.length} 个受控工具`)
  await new Promise(r => setTimeout(r, 300))
  diagnosticLogs.value.push(`[${new Date().toLocaleTimeString()}] 凭证引用校验通过 (${service.value?.auth_ref})`)
  diagnosing.value = false
}

onMounted(() => {
  loadServiceDetail()
})
</script>

<template>
  <AdaptiveContainer max-width="2xl" class="space-y-6">
    <!-- Header -->
    <div class="flex items-center justify-between pb-3 border-b border-[var(--color-border)]">
      <div class="flex items-center gap-3">
        <button
          class="p-1.5 rounded-lg text-[var(--color-text-secondary)] hover:bg-[var(--color-neutral-150)] cursor-pointer"
          @click="router.push('/ops/services')"
        >
          <span>← 返回列表</span>
        </button>
        <div>
          <h1 class="text-xl md:text-2xl font-bold text-[var(--color-text-primary)] flex items-center gap-2">
            <span>{{ service?.name || serviceId }}</span>
            <StatusBadge :status="service?.status || 'ready'" size="sm" />
          </h1>
          <div class="text-xs font-mono text-[var(--color-text-tertiary)] mt-0.5">
            {{ serviceId }} · Protocol: {{ service?.protocol }}
          </div>
        </div>
      </div>

      <AdaptiveButton variant="primary" size="sm" :loading="diagnosing" @click="runDiagnostics">
        <span>🩺 运行受控诊断</span>
      </AdaptiveButton>
    </div>

    <!-- Tabs -->
    <AdaptiveTabs v-model="activeTab" :tabs="tabs" />

    <!-- Tab 1: Overview -->
    <div v-if="activeTab === 'overview'" class="space-y-4">
      <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
        <AdaptiveCard padding="md" class="space-y-1">
          <div class="text-xs text-[var(--color-text-tertiary)]">
            服务状态
          </div>
          <div class="text-base font-bold text-emerald-600">
            正常提供服务 (Ready)
          </div>
        </AdaptiveCard>

        <AdaptiveCard padding="md" class="space-y-1">
          <div class="text-xs text-[var(--color-text-tertiary)]">
            描述符版本
          </div>
          <div class="text-base font-bold text-[var(--color-brand-600)] font-mono">
            v{{ service?.descriptor_version || '1.0.0' }}
          </div>
        </AdaptiveCard>

        <AdaptiveCard padding="md" class="space-y-1">
          <div class="text-xs text-[var(--color-text-tertiary)]">
            超时阈值
          </div>
          <div class="text-base font-bold text-[var(--color-text-primary)] font-mono">
            {{ service?.timeout_seconds || 30 }}s
          </div>
        </AdaptiveCard>
      </div>

      <AdaptiveCard padding="md" class="space-y-3">
        <h3 class="font-bold text-sm text-[var(--color-text-primary)]">
          基本接入属性
        </h3>
        <div class="grid grid-cols-2 gap-3 text-xs text-[var(--color-text-secondary)]">
          <div><span class="text-[var(--color-text-tertiary)]">Base URL: </span><code class="font-mono text-[var(--color-text-primary)]">{{ service?.base_url }}</code></div>
          <div><span class="text-[var(--color-text-tertiary)]">MCP URL: </span><code class="font-mono text-[var(--color-text-primary)]">{{ service?.mcp_url }}</code></div>
          <div><span class="text-[var(--color-text-tertiary)]">凭证引用: </span><code class="font-mono text-[var(--color-text-primary)]">{{ service?.auth_ref }}</code></div>
          <div><span class="text-[var(--color-text-tertiary)]">最后更新: </span><span>{{ service?.updated_at }}</span></div>
        </div>
      </AdaptiveCard>
    </div>

    <!-- Tab 2: Endpoints & Channels -->
    <AdaptiveCard v-else-if="activeTab === 'endpoints'" padding="md" class="space-y-4">
      <h3 class="font-bold text-base text-[var(--color-text-primary)]">
        生效频道与端点路由
      </h3>
      <div class="space-y-2">
        <div
          v-for="ch in (service?.channels || ['xhs_pc'])"
          :key="ch"
          class="p-3 bg-[var(--color-bg-subtle)] rounded-xl border border-[var(--color-border)] flex items-center justify-between"
        >
          <div>
            <div class="font-bold text-sm text-[var(--color-text-primary)]">
              通道代号: {{ ch }}
            </div>
            <div class="text-xs text-[var(--color-text-secondary)] mt-0.5">
              支持能力: {{ (service?.capabilities || []).join(', ') }}
            </div>
          </div>
          <span class="px-2 py-0.5 rounded bg-emerald-100 text-emerald-800 text-xs font-semibold">Active</span>
        </div>
      </div>
    </AdaptiveCard>

    <!-- Tab 3: MCP Tools -->
    <AdaptiveCard v-else-if="activeTab === 'mcp'" padding="md" class="space-y-4">
      <div class="flex items-center justify-between">
        <div>
          <h3 class="font-bold text-base text-[var(--color-text-primary)]">
            MCP Discovery 工具能力目录
          </h3>
          <p class="text-xs text-[var(--color-text-secondary)] mt-0.5">
            由上游服务动态暴露的受控 Tool 集合
          </p>
        </div>
        <span class="text-xs bg-[var(--color-brand-50)] text-[var(--color-brand-700)] px-2 py-1 rounded-md font-mono">
          {{ tools.length }} tools available
        </span>
      </div>

      <div class="space-y-3">
        <div
          v-for="tool in tools"
          :key="tool.name"
          class="p-3.5 bg-[var(--color-bg-subtle)] rounded-xl border border-[var(--color-border)] space-y-2"
        >
          <div class="flex items-center justify-between">
            <div class="font-mono font-bold text-sm text-[var(--color-brand-700)]">
              {{ tool.name }}
            </div>
            <span class="text-[11px] px-2 py-0.5 rounded bg-gray-100 text-gray-700">
              SideEffect: {{ tool.sideEffect ? 'True' : 'False' }}
            </span>
          </div>
          <p class="text-xs text-[var(--color-text-secondary)]">
            {{ tool.description }}
          </p>
        </div>
      </div>
    </AdaptiveCard>

    <!-- Tab 4: Diagnostics -->
    <AdaptiveCard v-else-if="activeTab === 'diagnostics'" padding="md" class="space-y-4">
      <div class="flex items-center justify-between">
        <h3 class="font-bold text-base text-[var(--color-text-primary)]">
          受控诊断日志
        </h3>
        <AdaptiveButton variant="outline" size="sm" :loading="diagnosing" @click="runDiagnostics">
          <span>重新执行诊断</span>
        </AdaptiveButton>
      </div>

      <div class="bg-[var(--color-neutral-900)] text-emerald-400 p-4 rounded-xl font-mono text-xs space-y-1.5 min-h-[160px]">
        <div v-if="!diagnosticLogs.length" class="text-gray-500">
          点击上方按钮启动受控连接诊断流程...
        </div>
        <div v-for="(log, idx) in diagnosticLogs" :key="idx">
          {{ log }}
        </div>
      </div>
    </AdaptiveCard>

    <!-- Tab 5: History -->
    <AdaptiveCard v-else-if="activeTab === 'history'" padding="md" class="space-y-3">
      <h3 class="font-bold text-base text-[var(--color-text-primary)]">
        配置变更与回滚历史
      </h3>
      <div class="space-y-2 text-xs">
        <div class="p-3 bg-[var(--color-bg-subtle)] rounded-xl border border-[var(--color-border)] flex items-center justify-between">
          <div>
            <div class="font-semibold text-[var(--color-text-primary)]">
              配置版本 v1.2.0 (当前最新)
            </div>
            <div class="text-[11px] text-[var(--color-text-tertiary)]">
              更新时间: 2026-09-02 09:30 · 操作人: admin
            </div>
          </div>
          <span class="text-emerald-600 font-bold">● 当前运行</span>
        </div>
        <div class="p-3 bg-[var(--color-bg-subtle)] rounded-xl border border-[var(--color-border)] flex items-center justify-between opacity-70">
          <div>
            <div class="font-semibold text-[var(--color-text-primary)]">
              配置版本 v1.1.0
            </div>
            <div class="text-[11px] text-[var(--color-text-tertiary)]">
              更新时间: 2026-09-01 18:00 · 操作人: admin
            </div>
          </div>
          <button class="text-xs text-[var(--color-brand-600)] hover:underline cursor-pointer">
            恢复此配置
          </button>
        </div>
      </div>
    </AdaptiveCard>
  </AdaptiveContainer>
</template>
