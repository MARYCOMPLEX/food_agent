<script setup lang="ts">
import type { PlatformAccount } from '../types'
import StatusBadge from '../../../shared/ui/StatusBadge.vue'
import AdaptiveButton from '../../../shared/ui/AdaptiveButton.vue'
import AdaptiveCard from '../../../shared/ui/AdaptiveCard.vue'
import { formatRelativeTime } from '../../../shared/utils/date'

defineProps<{
  account: PlatformAccount
}>()

const emit = defineEmits<{
  (e: 'login', account: PlatformAccount): void
  (e: 'reauth', account: PlatformAccount): void
  (e: 'refresh', account: PlatformAccount): void
}>()
</script>

<template>
  <AdaptiveCard padding="md" class="space-y-3 flex flex-col justify-between">
    <div>
      <div class="flex items-start justify-between gap-2">
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2">
            <span class="text-base">
              {{ account.platform === 'dianping' ? '🍴' : '📕' }}
            </span>
            <h4 class="font-bold text-sm md:text-base text-[var(--color-text-primary)] truncate">
              {{ account.alias }}
            </h4>
          </div>
          <div class="text-xs text-[var(--color-text-tertiary)] font-mono mt-0.5 truncate">
            ref: {{ account.account_ref }}
          </div>
        </div>

        <StatusBadge :status="account.status" size="sm" />
      </div>

      <!-- Account Metadata Grid -->
      <div class="grid grid-cols-2 gap-2 mt-3 pt-3 border-t border-[var(--color-border)] text-xs text-[var(--color-text-secondary)]">
        <div>
          <span class="text-[var(--color-text-tertiary)]">健康状态: </span>
          <span class="font-medium" :class="account.health === 'healthy' ? 'text-emerald-600' : 'text-amber-600'">
            {{ account.health === 'healthy' ? '正常健康' : (account.health || '良好') }}
          </span>
        </div>
        <div>
          <span class="text-[var(--color-text-tertiary)]">Session 版本: </span>
          <span class="font-mono font-medium text-[var(--color-text-primary)]">
            v{{ account.session_version || 1 }}
          </span>
        </div>
      </div>

      <div class="text-[11px] text-[var(--color-text-tertiary)] mt-2">
        最近更新: {{ formatRelativeTime(account.updated_at || account.created_at) }}
      </div>
    </div>

    <!-- Actions -->
    <div class="pt-2 border-t border-[var(--color-border)] flex items-center justify-end gap-2">
      <AdaptiveButton
        variant="ghost"
        size="sm"
        @click="emit('refresh', account)"
      >
        <span>🔄 刷新</span>
      </AdaptiveButton>

      <AdaptiveButton
        :variant="account.status === 'active' ? 'outline' : 'primary'"
        size="sm"
        @click="emit('login', account)"
      >
        <span>{{ account.status === 'active' ? '重新扫码认证' : '📲 扫码登录' }}</span>
      </AdaptiveButton>
    </div>
  </AdaptiveCard>
</template>
