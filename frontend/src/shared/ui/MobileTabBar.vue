<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const navItems = [
  { path: '/app/explore', label: '探索', icon: '🔍' },
  { path: '/app/favorites', label: '收藏', icon: '❤️' },
  { path: '/app/history', label: '历史', icon: '🕒' },
  { path: '/app/accounts', label: '平台账号', icon: '🔗' },
  { path: '/app/me', label: '我的', icon: '👤' },
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
</script>

<template>
  <nav class="fixed bottom-0 inset-x-0 z-40 bg-[var(--color-bg-surface)]/95 backdrop-blur-md border-t border-[var(--color-border)] safe-bottom">
    <div class="flex items-center justify-around h-14">
      <button
        v-for="item in navItems"
        :key="item.path"
        class="flex flex-col items-center justify-center flex-1 py-1 transition-colors cursor-pointer select-none"
        :class="[
          isActive(item.path)
            ? 'text-[var(--color-brand-600)] font-semibold'
            : 'text-[var(--color-text-tertiary)] hover:text-[var(--color-text-primary)]',
        ]"
        @click="navigate(item.path)"
      >
        <span class="text-lg leading-none mb-0.5">{{ item.icon }}</span>
        <span class="text-[11px] leading-tight">{{ item.label }}</span>
      </button>
    </div>
  </nav>
</template>

<style scoped>
.safe-bottom {
  padding-bottom: env(safe-area-inset-bottom, 0);
}
</style>
