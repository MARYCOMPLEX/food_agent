<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import AdaptiveContainer from '../../shared/ui/AdaptiveContainer.vue'
import AdaptiveButton from '../../shared/ui/AdaptiveButton.vue'
import AdaptiveCard from '../../shared/ui/AdaptiveCard.vue'
import AdaptiveModal from '../../shared/ui/AdaptiveModal.vue'
import StatusBadge from '../../shared/ui/StatusBadge.vue'
import { serviceCatalogApi } from './api/serviceCatalogApi'
import type { ServiceEndpointConfig } from './types'

const router = useRouter()

const services = ref<ServiceEndpointConfig[]>([])
const editModalOpen = ref(false)
const draftService = ref<ServiceEndpointConfig>({
  service_id: '',
  name: '',
  base_url: '',
  mcp_url: '',
  protocol: 'http',
  channels: ['xhs_pc'],
  capabilities: [],
  descriptor_version: '1.0.0',
  timeout_seconds: 30,
  auth_ref: '',
  status: 'ready',
})

const testing = ref(false)
const testResult = ref<any>(null)

async function loadServices() {
  services.value = await serviceCatalogApi.getServices()
}

function handleOpenNew() {
  draftService.value = {
    service_id: `svc_${Math.random().toString(36).substr(2, 6)}`,
    name: '新数据服务接入',
    base_url: 'http://localhost:8080',
    mcp_url: 'http://localhost:8080/mcp',
    protocol: 'http',
    channels: ['xhs_pc'],
    capabilities: ['search_notes'],
    descriptor_version: '1.0.0',
    timeout_seconds: 30,
    auth_ref: 'vault://custom/auth_ref',
    status: 'ready',
  }
  testResult.value = null
  editModalOpen.value = true
}

function handleEdit(svc: ServiceEndpointConfig) {
  draftService.value = { ...svc }
  testResult.value = null
  editModalOpen.value = true
}

function viewDetail(svc: ServiceEndpointConfig) {
  router.push(`/ops/services/${svc.service_id}`)
}

async function handleTestEndpoint() {
  testing.value = true
  testResult.value = null
  try {
    const res = await serviceCatalogApi.testEndpoint(draftService.value.base_url)
    testResult.value = res
  }
  catch {
    testResult.value = { success: false, latencyMs: 0 }
  }
  finally {
    testing.value = false
  }
}

async function handleSaveDraft() {
  draftService.value.updated_at = new Date().toISOString()
  await serviceCatalogApi.saveService(draftService.value)
  editModalOpen.value = false
  loadServices()
}

onMounted(() => {
  loadServices()
})
</script>

<template>
  <AdaptiveContainer max-width="2xl" class="space-y-6">
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
      <div>
        <h1 class="text-xl md:text-2xl font-bold text-[var(--color-text-primary)]">
          服务端点接入控制台 (Service Catalog)
        </h1>
        <p class="text-xs md:text-sm text-[var(--color-text-secondary)] mt-0.5">
          配置与治理上游数据源连接器、MCP 工具端点与原子能力发现
        </p>
      </div>

      <AdaptiveButton variant="primary" size="sm" @click="handleOpenNew">
        <span>➕ 新增服务接入</span>
      </AdaptiveButton>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      <AdaptiveCard
        v-for="svc in services"
        :key="svc.service_id"
        padding="md"
        class="space-y-3 flex flex-col justify-between hover:border-[var(--color-brand-400)] transition-all"
      >
        <div>
          <div class="flex items-start justify-between gap-2">
            <div>
              <h3 class="font-bold text-base text-[var(--color-text-primary)]">
                {{ svc.name }}
              </h3>
              <div class="text-xs font-mono text-[var(--color-text-tertiary)] mt-0.5">
                {{ svc.service_id }}
              </div>
            </div>
            <StatusBadge :status="svc.status" size="sm" />
          </div>

          <div class="space-y-1.5 mt-3 text-xs text-[var(--color-text-secondary)]">
            <div class="flex items-center gap-1.5">
              <span class="text-[var(--color-text-tertiary)]">HTTP URL:</span>
              <span class="font-mono text-[var(--color-text-primary)] truncate">{{ svc.base_url }}</span>
            </div>
            <div v-if="svc.mcp_url" class="flex items-center gap-1.5">
              <span class="text-[var(--color-text-tertiary)]">MCP URL:</span>
              <span class="font-mono text-[var(--color-text-primary)] truncate">{{ svc.mcp_url }}</span>
            </div>
            <div class="flex items-center gap-2 pt-1">
              <span class="px-1.5 py-0.5 rounded bg-[var(--color-neutral-200)] text-[10px] font-mono uppercase">
                {{ svc.protocol }}
              </span>
              <span class="px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 text-[10px] font-mono">
                v{{ svc.descriptor_version }}
              </span>
            </div>
          </div>
        </div>

        <div class="pt-3 border-t border-[var(--color-border)] flex items-center justify-between gap-2">
          <AdaptiveButton variant="ghost" size="sm" @click="handleEdit(svc)">
            <span>✏️ 编辑配置</span>
          </AdaptiveButton>
          <AdaptiveButton variant="subtle" size="sm" @click="viewDetail(svc)">
            <span>查看详情 & MCP →</span>
          </AdaptiveButton>
        </div>
      </AdaptiveCard>
    </div>

    <AdaptiveModal
      v-model="editModalOpen"
      :title="`配置服务接入 - ${draftService.name || '新服务'}`"
      width="540px"
    >
      <form class="space-y-4 text-sm" @submit.prevent="handleSaveDraft">
        <div class="p-3 bg-amber-50 text-amber-900 rounded-xl text-xs leading-relaxed">
          🔒 安全规范：只保存 <code>auth_ref</code> 凭证引用，不存储真实明文 Token 或 Cookie。
        </div>

        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block text-xs font-semibold text-[var(--color-text-secondary)] mb-1">服务 ID (service_id)</label>
            <input
              v-model="draftService.service_id"
              type="text"
              class="w-full px-3 py-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-surface)] text-sm font-mono text-[var(--color-text-primary)] outline-none"
              required
            >
          </div>
          <div>
            <label class="block text-xs font-semibold text-[var(--color-text-secondary)] mb-1">服务名称</label>
            <input
              v-model="draftService.name"
              type="text"
              class="w-full px-3 py-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-surface)] text-sm text-[var(--color-text-primary)] outline-none"
              required
            >
          </div>
        </div>

        <div>
          <label class="block text-xs font-semibold text-[var(--color-text-secondary)] mb-1">Base HTTP URL</label>
          <input
            v-model="draftService.base_url"
            type="text"
            placeholder="http://localhost:8001"
            class="w-full px-3 py-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-surface)] text-sm font-mono text-[var(--color-text-primary)] outline-none"
            required
          >
        </div>

        <div>
          <label class="block text-xs font-semibold text-[var(--color-text-secondary)] mb-1">MCP Endpoint URL</label>
          <input
            v-model="draftService.mcp_url"
            type="text"
            placeholder="http://localhost:8001/mcp"
            class="w-full px-3 py-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-surface)] text-sm font-mono text-[var(--color-text-primary)] outline-none"
          >
        </div>

        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block text-xs font-semibold text-[var(--color-text-secondary)] mb-1">协议类型</label>
            <select
              v-model="draftService.protocol"
              class="w-full px-3 py-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-surface)] text-sm text-[var(--color-text-primary)] outline-none"
            >
              <option value="http">
                HTTP Rest
              </option>
              <option value="mcp">
                Model Context Protocol (MCP)
              </option>
              <option value="sse">
                SSE Stream
              </option>
            </select>
          </div>
          <div>
            <label class="block text-xs font-semibold text-[var(--color-text-secondary)] mb-1">凭证引用 (auth_ref)</label>
            <input
              v-model="draftService.auth_ref"
              type="text"
              placeholder="vault://xhs/auth_key"
              class="w-full px-3 py-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-surface)] text-sm font-mono text-[var(--color-text-primary)] outline-none"
            >
          </div>
        </div>

        <div class="p-3 bg-[var(--color-bg-subtle)] rounded-xl border border-[var(--color-border)] space-y-2">
          <div class="flex items-center justify-between">
            <span class="text-xs font-bold text-[var(--color-text-primary)]">连接可用性与契约诊断:</span>
            <AdaptiveButton
              type="button"
              variant="outline"
              size="sm"
              :loading="testing"
              @click="handleTestEndpoint"
            >
              <span>🧪 测试连接 & 握手</span>
            </AdaptiveButton>
          </div>

          <div v-if="testResult" class="text-xs text-emerald-800 bg-emerald-50 p-2.5 rounded-lg border border-emerald-200">
            ✓ 契约握手成功！响应耗时: {{ testResult.latencyMs }}ms，发现能力: {{ (testResult.capabilities || []).join(', ') }}
          </div>
        </div>

        <div class="pt-2 flex justify-end gap-2">
          <AdaptiveButton variant="outline" size="sm" @click="editModalOpen = false">
            <span>取消</span>
          </AdaptiveButton>
          <AdaptiveButton type="submit" variant="primary" size="sm">
            <span>确认保存并原子刷新</span>
          </AdaptiveButton>
        </div>
      </form>
    </AdaptiveModal>
  </AdaptiveContainer>
</template>
