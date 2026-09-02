<script setup lang="ts">
import { onMounted, ref } from 'vue'
import AdaptiveContainer from '../../shared/ui/AdaptiveContainer.vue'
import AdaptiveButton from '../../shared/ui/AdaptiveButton.vue'
import AdaptiveCard from '../../shared/ui/AdaptiveCard.vue'
import AdaptiveModal from '../../shared/ui/AdaptiveModal.vue'
import StatusBadge from '../../shared/ui/StatusBadge.vue'
import { formatRelativeTime } from '../../shared/utils/date'
import { evidenceObservabilityApi } from './api/evidenceApi'
import type { QueryFamily } from './types'

const families = ref<QueryFamily[]>([])
const loading = ref(false)
const refreshingId = ref<string | null>(null)
const diffModalOpen = ref(false)
const selectedFamily = ref<QueryFamily | null>(null)

async function loadEvidence() {
  loading.value = true
  try {
    families.value = await evidenceObservabilityApi.getQueryFamilies()
  }
  catch (err) {
    console.error('Load evidence failed', err)
  }
  finally {
    loading.value = false
  }
}

async function handleTriggerRefresh(fam: QueryFamily) {
  refreshingId.value = fam.family_id
  try {
    const res = await evidenceObservabilityApi.triggerRefresh(fam.family_id)
    fam.bundle_version = res.newVersion
    fam.watermark_updated_at = new Date().toISOString()
    fam.stale_objects_count = 0
  }
  catch (err) {
    console.error('Refresh failed', err)
  }
  finally {
    refreshingId.value = null
  }
}

function openDiff(fam: QueryFamily) {
  selectedFamily.value = fam
  diffModalOpen.value = true
}

onMounted(() => {
  loadEvidence()
})
</script>

<template>
  <AdaptiveContainer max-width="2xl" class="space-y-6">
    <!-- Header -->
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
      <div>
        <h1 class="text-xl md:text-2xl font-bold text-[var(--color-text-primary)]">
          证据缓存与新鲜度水位观测 (Evidence Observability)
        </h1>
        <p class="text-xs md:text-sm text-[var(--color-text-secondary)] mt-0.5">
          监控 Query Family 聚类、Evidence Bundle 增量版本、数据覆盖率与过期水位
        </p>
      </div>

      <AdaptiveButton variant="subtle" size="sm" @click="loadEvidence">
        <span>🔄 刷新水位指标</span>
      </AdaptiveButton>
    </div>

    <!-- Query Families Cards -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
      <AdaptiveCard
        v-for="fam in families"
        :key="fam.family_id"
        padding="md"
        class="space-y-3 flex flex-col justify-between"
      >
        <div>
          <div class="flex items-start justify-between gap-2">
            <div>
              <h3 class="font-bold text-base text-[var(--color-text-primary)]">
                {{ fam.family_id }}
              </h3>
              <div class="text-xs font-mono text-[var(--color-text-tertiary)] mt-0.5">
                {{ fam.pattern }}
              </div>
            </div>
            <StatusBadge :status="fam.stale_objects_count > 0 ? 'warning' : 'ready'" :text="fam.stale_objects_count > 0 ? '需增量刷新' : '新鲜有效'" size="sm" />
          </div>

          <!-- Metrics -->
          <div class="grid grid-cols-2 gap-2 mt-3 pt-3 border-t border-[var(--color-border)] text-xs text-[var(--color-text-secondary)]">
            <div>
              <span class="text-[var(--color-text-tertiary)]">证据覆盖率: </span>
              <span class="font-bold text-emerald-600">{{ Math.round(fam.coverage_rate * 100) }}%</span>
            </div>
            <div>
              <span class="text-[var(--color-text-tertiary)]">Bundle 版本: </span>
              <span class="font-mono font-bold text-[var(--color-brand-600)]">{{ fam.bundle_version }}</span>
            </div>
            <div>
              <span class="text-[var(--color-text-tertiary)]">有效对象数: </span>
              <span class="font-mono">{{ fam.active_objects_count }}</span>
            </div>
            <div>
              <span class="text-[var(--color-text-tertiary)]">待刷新过期: </span>
              <span class="font-mono text-amber-600 font-bold">{{ fam.stale_objects_count }}</span>
            </div>
          </div>

          <div class="text-[11px] text-[var(--color-text-tertiary)] mt-2">
            水位更新: {{ formatRelativeTime(fam.watermark_updated_at) }}
          </div>
        </div>

        <!-- Actions -->
        <div class="pt-2 border-t border-[var(--color-border)] flex items-center justify-between gap-2">
          <AdaptiveButton variant="ghost" size="sm" @click="openDiff(fam)">
            <span>📊 查看版本差异</span>
          </AdaptiveButton>
          <AdaptiveButton
            variant="subtle"
            size="sm"
            :loading="refreshingId === fam.family_id"
            @click="handleTriggerRefresh(fam)"
          >
            <span>🔄 触发增量刷新</span>
          </AdaptiveButton>
        </div>
      </AdaptiveCard>
    </div>

    <!-- Diff Modal -->
    <AdaptiveModal
      v-model="diffModalOpen"
      :title="`Evidence Bundle 版本比对 - ${selectedFamily?.family_id || ''}`"
      width="500px"
    >
      <div class="space-y-3 text-xs">
        <div class="p-3 bg-[var(--color-bg-subtle)] rounded-xl border border-[var(--color-border)] space-y-1">
          <div class="font-bold text-sm text-[var(--color-text-primary)]">
            当前版本: {{ selectedFamily?.bundle_version }}
          </div>
          <div class="text-[var(--color-text-tertiary)]">
            Query Pattern: {{ selectedFamily?.pattern }}
          </div>
        </div>

        <div class="space-y-2">
          <div class="p-2.5 bg-emerald-50 text-emerald-900 rounded-lg border border-emerald-200">
            <span class="font-bold">+ 新增证据: </span>共收录 14 条近 24 小时发布的新探店笔记与真实打分。
          </div>
          <div class="p-2.5 bg-amber-50 text-amber-900 rounded-lg border border-amber-200">
            <span class="font-bold">~ 权重更新: </span>2 家店铺因出现疑似刷评行为被调低本地信任分。
          </div>
        </div>
      </div>
      <template #footer>
        <AdaptiveButton variant="primary" size="sm" @click="diffModalOpen = false">
          <span>关闭</span>
        </AdaptiveButton>
      </template>
    </AdaptiveModal>
  </AdaptiveContainer>
</template>
