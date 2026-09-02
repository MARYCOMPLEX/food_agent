<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'
import { useDevice } from '../shared/utils/device'
import MobileTabBar from '../shared/ui/MobileTabBar.vue'

const route = useRoute()
const router = useRouter()
const { isMobile } = useDevice()

const navItems = [
  { path: '/app/explore', label: '美食探索', icon: '🔍', desc: '自然语言搜索与研究' },
  { path: '/app/favorites', label: '我的收藏', icon: '❤️', desc: '保存的特色店铺' },
  { path: '/app/history', label: '搜索历史', icon: '🕒', desc: '过往研究与追问记录' },
  { path: '/app/accounts', label: '平台账号', icon: '🔗', desc: '小红书/点评数据源' },
  { path: '/app/me', label: '个人中心', icon: '👤', desc: '偏好与记忆管理' },
]

function isActive(path: string): boolean {
  if (path === '/app/explore') {
    return route.path === '/app/explore' || route.path.startsWith('/app/sessions')
  }
  return route.path.startsWith(path)
}

function navigate(path: string) {
  router.push(path)
}

function goToOps() {
  router.push('/ops')
}
</script>

<template>
  <div class="min-h-screen bg-[var(--color-bg-canvas)] text-[var(--color-text-primary)] flex flex-col font-sans">
    <!-- Desktop Layout -->
    <div v-if="!isMobile" class="flex flex-1 min-h-screen">
      <!-- Sidebar -->
      <aside class="w-64 bg-[var(--color-bg-surface)] border-r border-[var(--color-border)] flex flex-col shrink-0 select-none">
        <!-- Brand Header -->
        <div class="h-16 px-6 flex items-center justify-between border-b border-[var(--color-border)]">
          <div class="flex items-center gap-2.5 cursor-pointer" @click="navigate('/app/explore')">
            <div class="w-9 h-9 rounded-xl bg-gradient-to-tr from-[var(--color-brand-600)] to-[var(--color-brand-400)] flex items-center justify-center text-white font-bold text-lg shadow-sm">
              🍜
            </div>
            <div>
              <div class="font-bold text-base leading-tight tracking-tight text-[var(--color-text-primary)]">
                Food Agent
              </div>
              <div class="text-[11px] text-[var(--color-text-tertiary)] leading-tight">
                AnyFast 美食研究引擎
              </div>
            </div>
          </div>
        </div>

        <!-- Navigation Links -->
        <nav class="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
          <button
            v-for="item in navItems"
            :key="item.path"
            class="w-full flex items-center gap-3 px-3.5 py-2.5 rounded-btn text-sm font-medium transition-all text-left cursor-pointer group"
            :class="[
              isActive(item.path)
                ? 'bg-[var(--color-brand-50)] text-[var(--color-brand-700)] font-semibold shadow-xs'
                : 'text-[var(--color-text-secondary)] hover:bg-[var(--color-neutral-100)] hover:text-[var(--color-text-primary)]',
            ]"
            @click="navigate(item.path)"
          >
            <span class="text-lg">{{ item.icon }}</span>
            <div class="flex-1 truncate">
              <div>{{ item.label }}</div>
            </div>
          </button>
        </nav>

        <!-- Footer / Ops Portal Switcher -->
        <div class="p-3 border-t border-[var(--color-border)] bg-[var(--color-bg-subtle)] space-y-2">
          <button
            class="w-full flex items-center justify-between px-3 py-2 rounded-lg text-xs font-medium text-[var(--color-text-secondary)] hover:bg-[var(--color-neutral-200)] transition-colors cursor-pointer"
            @click="goToOps"
          >
            <div class="flex items-center gap-2">
              <span>⚙️</span>
              <span>观测配置控制台</span>
            </div>
            <span class="text-[10px] bg-[var(--color-neutral-300)] text-[var(--color-text-tertiary)] px-1.5 py-0.5 rounded">/ops</span>
          </button>
          <div class="text-[11px] text-center text-[var(--color-text-tertiary)] py-1">
            AnyFast v1.0.0
          </div>
        </div>
      </aside>

      <!-- Main Content Area -->
      <main class="flex-1 flex flex-col min-w-0 overflow-y-auto">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>

    <!-- Mobile Layout -->
    <div v-else class="flex flex-col min-h-screen pb-16">
      <main class="flex-1 overflow-y-auto">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
      <MobileTabBar />
    </div>
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
