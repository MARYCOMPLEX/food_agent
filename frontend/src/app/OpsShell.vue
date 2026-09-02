<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useDevice } from '../shared/utils/device'
import StatusBadge from '../shared/ui/StatusBadge.vue'
import { httpClient } from '../shared/api/httpClient'
import type { PlatformReadinessResponse } from '../shared/contracts'

const route = useRoute()
const router = useRouter()
const { isMobile } = useDevice()

const readiness = ref<PlatformReadinessResponse | null>(null)
const loadingReadiness = ref(false)

const opsNavItems = [
  { path: '/ops', label: '系统总览', icon: '📊' },
  { path: '/ops/services', label: '服务接入', icon: '🔌' },
  { path: '/ops/tasks', label: '任务观测', icon: '⚡' },
  { path: '/ops/evidence', label: '证据观测', icon: '🗂️' },
]

function isActive(path: string): boolean {
  if (path === '/ops') {
    return route.path === '/ops'
  }
  return route.path.startsWith(path)
}

function navigate(path: string) {
  router.push(path)
}

function goToApp() {
  router.push('/app/explore')
}

async function fetchReadiness() {
  loadingReadiness.value = true
  try {
    const data = await httpClient.get<PlatformReadinessResponse>('/v1/platform/readiness')
    readiness.value = data
  }
  catch {
    readiness.value = { state: 'degraded', ready: false }
  }
  finally {
    loadingReadiness.value = false
  }
}

onMounted(() => {
  fetchReadiness()
})
</script>

<template>
  <div class="min-h-screen bg-[var(--color-bg-canvas)] text-[var(--color-text-primary)] flex flex-col font-sans">
    <!-- Top Navigation Header -->
    <header class="sticky top-0 z-40 bg-[var(--color-bg-surface)] border-b border-[var(--color-border)] shadow-xs select-none">
      <div class="max-w-7xl mx-auto px-4 md:px-6 h-14 flex items-center justify-between">
        <!-- Logo & Title -->
        <div class="flex items-center gap-6">
          <div class="flex items-center gap-2 cursor-pointer" @click="navigate('/ops')">
            <div class="w-8 h-8 rounded-lg bg-[var(--color-neutral-900)] text-white flex items-center justify-center font-bold text-sm">
              OPS
            </div>
            <div class="font-bold text-sm md:text-base text-[var(--color-text-primary)] flex items-center gap-1.5">
              <span>AnyFast 观测与配置端</span>
              <span class="text-xs px-1.5 py-0.2 rounded bg-amber-100 text-amber-800 font-normal">Internal</span>
            </div>
          </div>

          <!-- Nav Items (Desktop) -->
          <nav v-if="!isMobile" class="flex items-center gap-1">
            <button
              v-for="item in opsNavItems"
              :key="item.path"
              class="px-3 py-1.5 rounded-md text-sm font-medium transition-colors cursor-pointer flex items-center gap-1.5"
              :class="[
                isActive(item.path)
                  ? 'bg-[var(--color-neutral-200)] text-[var(--color-text-primary)] font-semibold'
                  : 'text-[var(--color-text-secondary)] hover:bg-[var(--color-neutral-100)] hover:text-[var(--color-text-primary)]',
              ]"
              @click="navigate(item.path)"
            >
              <span>{{ item.icon }}</span>
              <span>{{ item.label }}</span>
            </button>
          </nav>
        </div>

        <!-- Right Header Actions -->
        <div class="flex items-center gap-3">
          <div v-if="readiness" class="hidden sm:flex items-center gap-2">
            <StatusBadge :status="readiness.state" :text="`系统状态: ${readiness.state}`" size="sm" />
          </div>

          <button
            class="px-3 py-1.5 rounded-btn text-xs font-medium bg-[var(--color-brand-50)] text-[var(--color-brand-700)] hover:bg-[var(--color-brand-100)] transition-colors cursor-pointer flex items-center gap-1"
            @click="goToApp"
          >
            <span>🍜</span>
            <span>返回用户端</span>
          </button>
        </div>
      </div>

      <!-- Mobile Nav Row -->
      <div v-if="isMobile" class="flex items-center justify-around border-t border-[var(--color-border)] px-2 py-1.5 bg-[var(--color-bg-subtle)] overflow-x-auto">
        <button
          v-for="item in opsNavItems"
          :key="item.path"
          class="flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium whitespace-nowrap"
          :class="[
            isActive(item.path)
              ? 'bg-[var(--color-neutral-300)] text-[var(--color-text-primary)] font-bold'
              : 'text-[var(--color-text-secondary)]',
          ]"
          @click="navigate(item.path)"
        >
          <span>{{ item.icon }}</span>
          <span>{{ item.label }}</span>
        </button>
      </div>
    </header>

    <!-- Main Content Area -->
    <main class="flex-1 max-w-7xl w-full mx-auto p-4 md:p-6 overflow-y-auto">
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>
  </div>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
