<script setup lang="ts">
import { ref } from 'vue'
import AdaptiveModal from '../../../shared/ui/AdaptiveModal.vue'
import AdaptiveButton from '../../../shared/ui/AdaptiveButton.vue'
import type { PlatformAccountCreateRequest } from '../types'

defineProps<{
  modelValue: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', val: boolean): void
  (e: 'submit', req: PlatformAccountCreateRequest): void
}>()

const platform = ref('xhs_pc')
const accountRef = ref('')
const alias = ref('')

function handleSubmit() {
  if (!accountRef.value.trim() || !alias.value.trim())
    return
  emit('submit', {
    platform: platform.value,
    account_ref: accountRef.value.trim(),
    alias: alias.value.trim(),
  })
  accountRef.value = ''
  alias.value = ''
}
</script>

<template>
  <AdaptiveModal
    :model-value="modelValue"
    title="添加采集平台账号引用"
    width="440px"
    @update:model-value="(v) => emit('update:modelValue', v)"
  >
    <form class="space-y-4 text-sm" @submit.prevent="handleSubmit">
      <div class="p-3 bg-blue-50 text-blue-900 rounded-xl text-xs leading-relaxed">
        💡 提示：此处管理的是用于抓取公开美食数据的平台凭证句柄，系统不保存明文密码或用户个人账号。
      </div>

      <div>
        <label class="block text-xs font-semibold text-[var(--color-text-secondary)] mb-1">所属平台通道</label>
        <select
          v-model="platform"
          class="w-full px-3 py-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-surface)] text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-brand-500)]"
        >
          <option value="xhs_pc">
            小红书 PC 探索端 (xhs_pc)
          </option>
          <option value="xhs_creator">
            小红书创作者后台 (xhs_creator)
          </option>
          <option value="dianping">
            大众点评 (dianping)
          </option>
        </select>
      </div>

      <div>
        <label class="block text-xs font-semibold text-[var(--color-text-secondary)] mb-1">账号唯一引用 (account_ref)</label>
        <input
          v-model="accountRef"
          type="text"
          placeholder="例如: xhs_crawler_bot_01"
          class="w-full px-3 py-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-surface)] text-sm font-mono text-[var(--color-text-primary)] outline-none focus:border-[var(--color-brand-500)]"
          required
        >
      </div>

      <div>
        <label class="block text-xs font-semibold text-[var(--color-text-secondary)] mb-1">账号别名 / 备注</label>
        <input
          v-model="alias"
          type="text"
          placeholder="例如: 成都本地美食探店专号"
          class="w-full px-3 py-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-surface)] text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-brand-500)]"
          required
        >
      </div>

      <div class="pt-2 flex justify-end gap-2">
        <AdaptiveButton variant="outline" size="sm" @click="emit('update:modelValue', false)">
          <span>取消</span>
        </AdaptiveButton>
        <AdaptiveButton type="submit" variant="primary" size="sm" :disabled="!accountRef || !alias">
          <span>确认创建</span>
        </AdaptiveButton>
      </div>
    </form>
  </AdaptiveModal>
</template>
