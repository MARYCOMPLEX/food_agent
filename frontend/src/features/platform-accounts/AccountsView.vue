<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import AdaptiveContainer from '../../shared/ui/AdaptiveContainer.vue'
import AdaptiveButton from '../../shared/ui/AdaptiveButton.vue'
import EmptyState from '../../shared/ui/EmptyState.vue'
import PlatformLoginModal from '../platform-login/components/PlatformLoginModal.vue'
import AccountCard from './components/AccountCard.vue'
import AccountAddModal from './components/AccountAddModal.vue'
import { platformAccountsApi } from './api/platformAccountsApi'
import type { PlatformAccount, PlatformAccountCreateRequest } from './types'

const activePlatform = ref<string>('all')
const accounts = ref<PlatformAccount[]>([])
const addModalOpen = ref(false)
const loginModalOpen = ref(false)
const selectedAccount = ref<PlatformAccount | null>(null)

function loadAccounts() {
  accounts.value = platformAccountsApi.getLocalAccounts()
}

const filteredAccounts = computed(() => {
  if (activePlatform.value === 'all')
    return accounts.value
  return accounts.value.filter(a => a.platform === activePlatform.value)
})

function handleOpenLogin(acc: PlatformAccount) {
  selectedAccount.value = acc
  loginModalOpen.value = true
}

async function handleRefreshAccount(acc: PlatformAccount) {
  try {
    const updated = await platformAccountsApi.getAccount(acc.platform, acc.account_ref)
    const idx = accounts.value.findIndex(
      a => a.platform === acc.platform && a.account_ref === acc.account_ref,
    )
    if (idx >= 0) {
      accounts.value[idx] = updated
    }
  }
  catch (err) {
    console.error('Refresh account failed', err)
  }
}

async function handleCreateAccount(req: PlatformAccountCreateRequest) {
  try {
    await platformAccountsApi.registerAccount(req)
    loadAccounts()
    addModalOpen.value = false
  }
  catch (err) {
    console.error('Create account failed', err)
  }
}

function handleLoginSuccess(acc: PlatformAccount) {
  acc.status = 'active'
  acc.health = 'healthy'
  acc.session_version = (acc.session_version || 1) + 1
  platformAccountsApi.saveAccountLocally(acc)
  loadAccounts()
}

onMounted(() => {
  loadAccounts()
})
</script>

<template>
  <AdaptiveContainer max-width="xl" class="space-y-6">
    <!-- Header -->
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
      <div>
        <h1 class="text-xl md:text-2xl font-bold text-[var(--color-text-primary)]">
          数据采集平台账号管理
        </h1>
        <p class="text-xs md:text-sm text-[var(--color-text-secondary)] mt-0.5">
          管理用于检索小红书和大众点评真实笔记的数据源会话与扫码认证
        </p>
      </div>

      <div class="flex items-center gap-2">
        <AdaptiveButton
          variant="primary"
          size="sm"
          @click="addModalOpen = true"
        >
          <span>➕ 添加账号引用</span>
        </AdaptiveButton>
      </div>
    </div>

    <!-- Platform Filter Tabs -->
    <div class="flex items-center gap-2 border-b border-[var(--color-border)] pb-2 overflow-x-auto">
      <button
        class="px-3.5 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer whitespace-nowrap"
        :class="activePlatform === 'all' ? 'bg-[var(--color-brand-500)] text-white font-semibold' : 'bg-[var(--color-neutral-150)] text-[var(--color-text-secondary)] hover:bg-[var(--color-neutral-200)]'"
        @click="activePlatform = 'all'"
      >
        全部平台 ({{ accounts.length }})
      </button>
      <button
        class="px-3.5 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer whitespace-nowrap"
        :class="activePlatform === 'xhs_pc' ? 'bg-[var(--color-brand-500)] text-white font-semibold' : 'bg-[var(--color-neutral-150)] text-[var(--color-text-secondary)] hover:bg-[var(--color-neutral-200)]'"
        @click="activePlatform = 'xhs_pc'"
      >
        📕 小红书 PC 端
      </button>
      <button
        class="px-3.5 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer whitespace-nowrap"
        :class="activePlatform === 'xhs_creator' ? 'bg-[var(--color-brand-500)] text-white font-semibold' : 'bg-[var(--color-neutral-150)] text-[var(--color-text-secondary)] hover:bg-[var(--color-neutral-200)]'"
        @click="activePlatform = 'xhs_creator'"
      >
        🎨 小红书创作者
      </button>
      <button
        class="px-3.5 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer whitespace-nowrap"
        :class="activePlatform === 'dianping' ? 'bg-[var(--color-brand-500)] text-white font-semibold' : 'bg-[var(--color-neutral-150)] text-[var(--color-text-secondary)] hover:bg-[var(--color-neutral-200)]'"
        @click="activePlatform = 'dianping'"
      >
        🍴 大众点评
      </button>
    </div>

    <!-- Account Grid -->
    <div v-if="filteredAccounts.length" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      <AccountCard
        v-for="acc in filteredAccounts"
        :key="`${acc.platform}-${acc.account_ref}`"
        :account="acc"
        @login="handleOpenLogin"
        @reauth="handleOpenLogin"
        @refresh="handleRefreshAccount"
      />
    </div>

    <!-- Empty State -->
    <EmptyState
      v-else
      icon="🔗"
      title="当前平台暂无配置账号"
      description="点击上方'添加账号引用'即可接入新的数据采集凭据"
    >
      <template #action>
        <AdaptiveButton variant="primary" size="md" @click="addModalOpen = true">
          <span>添加账号引用</span>
        </AdaptiveButton>
      </template>
    </EmptyState>

    <!-- Modals -->
    <AccountAddModal
      v-model="addModalOpen"
      @submit="handleCreateAccount"
    />

    <PlatformLoginModal
      v-model="loginModalOpen"
      :account="selectedAccount"
      @success="handleLoginSuccess"
    />
  </AdaptiveContainer>
</template>
