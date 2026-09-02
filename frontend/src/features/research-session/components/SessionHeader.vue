<script setup lang="ts">
import { useRouter } from 'vue-router'
import StatusBadge from '../../../shared/ui/StatusBadge.vue'
import AdaptiveButton from '../../../shared/ui/AdaptiveButton.vue'

defineProps<{
  sessionId: string
  connectionState: string
  isComplete: boolean
}>()

const emit = defineEmits<{
  (e: 'reconnect'): void
  (e: 'recover'): void
}>()

const router = useRouter()

function goBack() {
  router.push('/app/explore')
}
</script>

<template>
  <div class="flex items-center justify-between pb-3 border-b border-[var(--color-border)] gap-2">
    <div class="flex items-center gap-2.5 min-w-0">
      <button
        class="p-1.5 rounded-lg text-[var(--color-text-secondary)] hover:bg-[var(--color-neutral-150)] cursor-pointer"
        @click="goBack"
      >
        <span>← 返回</span>
      </button>
      <div class="truncate">
        <h2 class="text-base md:text-lg font-bold text-[var(--color-text-primary)] truncate">
          美食研判会话
        </h2>
        <div class="text-[11px] text-[var(--color-text-tertiary)] font-mono truncate">
          {{ sessionId }}
        </div>
      </div>
    </div>

    <div class="flex items-center gap-2 shrink-0">
      <StatusBadge
        :status="connectionState === 'connected' ? 'ready' : (connectionState === 'reconnecting' ? 'warning' : 'disabled')"
        :text="connectionState === 'connected' ? '实时流已连通' : (connectionState === 'reconnecting' ? '重连中...' : connectionState)"
        size="sm"
      />
      <AdaptiveButton
        v-if="connectionState === 'disconnected' || connectionState === 'error'"
        variant="outline"
        size="sm"
        @click="emit('reconnect')"
      >
        <span>重试连线</span>
      </AdaptiveButton>
    </div>
  </div>
</template>
