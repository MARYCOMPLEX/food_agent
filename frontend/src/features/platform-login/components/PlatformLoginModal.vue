<script setup lang="ts">
import { onUnmounted, ref, watch } from 'vue'
import AdaptiveModal from '../../../shared/ui/AdaptiveModal.vue'
import AdaptiveButton from '../../../shared/ui/AdaptiveButton.vue'
import StatusBadge from '../../../shared/ui/StatusBadge.vue'
import { platformLoginApi } from '../api/platformLoginApi'
import type { PlatformAccount, PlatformLoginFlow, PlatformQrPresentation } from '../types'

const props = defineProps<{
  account: PlatformAccount | null
  modelValue: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', val: boolean): void
  (e: 'success', account: PlatformAccount): void
}>()

const flow = ref<PlatformLoginFlow | null>(null)
const qrPresentation = ref<PlatformQrPresentation | null>(null)
const loading = ref(false)
const errorMsg = ref('')
const countdown = ref(120)
let pollTimer: any = null
let countdownTimer: any = null

async function startLoginFlow() {
  if (!props.account)
    return
  loading.value = true
  errorMsg.value = ''
  countdown.value = 120

  try {
    const startedFlow = await platformLoginApi.startQrLogin(
      props.account.platform,
      props.account.account_ref,
    )
    flow.value = startedFlow

    // Fetch presentation QR
    if (startedFlow?.flow_id) {
      try {
        const qrData = await platformLoginApi.getQrPresentation(startedFlow.flow_id)
        qrPresentation.value = qrData
      }
      catch {
        // Mock fallback presentation QR pattern if needed
        qrPresentation.value = {
          flow_id: startedFlow.flow_id,
          status: 'ready',
        }
      }
      startPolling(startedFlow.flow_id)
    }
  }
  catch (err: any) {
    errorMsg.value = err?.message || '创建扫码登录会话失败'
  }
  finally {
    loading.value = false
  }
}

function startPolling(flowId: string) {
  stopPolling()

  countdownTimer = setInterval(() => {
    if (countdown.value > 0) {
      countdown.value--
    }
    else {
      stopPolling()
      errorMsg.value = '二维码已过期，请点击重新刷新'
    }
  }, 1000)

  pollTimer = setInterval(async () => {
    try {
      const status = await platformLoginApi.pollLoginStatus(flowId)
      flow.value = status
      if (status.state === 'success') {
        stopPolling()
        emit('success', props.account!)
        emit('update:modelValue', false)
      }
      else if (status.state === 'expired' || status.state === 'failed' || status.state === 'risk') {
        stopPolling()
        errorMsg.value = `登录状态异常: ${status.state} (${status.error_message || ''})`
      }
    }
    catch {
      // Continue polling until timeout
    }
  }, 2500)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
  if (countdownTimer) {
    clearInterval(countdownTimer)
    countdownTimer = null
  }
}

async function handleCancel() {
  if (flow.value?.flow_id) {
    try {
      await platformLoginApi.cancelLogin(flow.value.flow_id)
    }
    catch {}
  }
  stopPolling()
  emit('update:modelValue', false)
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      startLoginFlow()
    }
    else {
      stopPolling()
    }
  },
)

onUnmounted(() => {
  stopPolling()
})
</script>

<template>
  <AdaptiveModal
    :model-value="modelValue"
    :title="`扫码登录 - ${account?.alias || '平台账号'}`"
    width="420px"
    @update:model-value="(v) => emit('update:modelValue', v)"
  >
    <div class="flex flex-col items-center justify-center p-2 text-center space-y-4">
      <!-- Status Header -->
      <div class="flex items-center gap-2">
        <span class="text-xs text-[var(--color-text-secondary)]">通道: {{ account?.platform }}</span>
        <StatusBadge :status="flow?.state || 'polling'" size="sm" />
      </div>

      <!-- QR Box -->
      <div class="relative w-56 h-56 rounded-2xl bg-[var(--color-neutral-100)] border-2 border-dashed border-[var(--color-border)] flex items-center justify-center p-4">
        <div v-if="loading" class="flex flex-col items-center">
          <div class="w-8 h-8 border-3 border-[var(--color-brand-500)] border-t-transparent rounded-full animate-spin mb-2" />
          <span class="text-xs text-[var(--color-text-tertiary)]">正在生成登录二维码...</span>
        </div>

        <div v-else-if="errorMsg" class="p-3 text-xs text-red-600 space-y-2">
          <div>⚠️ {{ errorMsg }}</div>
          <AdaptiveButton variant="primary" size="sm" @click="startLoginFlow">
            <span>重新生成二维码</span>
          </AdaptiveButton>
        </div>

        <!-- QR Display Placeholder / Real QR -->
        <div v-else class="flex flex-col items-center space-y-2">
          <!-- Simulated SVG QR Graphic -->
          <div class="w-40 h-40 bg-white p-2 rounded-xl shadow-xs flex items-center justify-center">
            <svg class="w-full h-full text-[var(--color-neutral-900)]" viewBox="0 0 100 100" fill="currentColor">
              <rect width="25" height="25" x="10" y="10" rx="3" />
              <rect width="15" height="15" x="15" y="15" fill="white" />
              <rect width="7" height="7" x="19" y="19" />
              <rect width="25" height="25" x="65" y="10" rx="3" />
              <rect width="15" height="15" x="70" y="15" fill="white" />
              <rect width="7" height="7" x="74" y="19" />
              <rect width="25" height="25" x="10" y="65" rx="3" />
              <rect width="15" height="15" x="15" y="70" fill="white" />
              <rect width="7" height="7" x="19" y="74" />
              <rect width="8" height="8" x="46" y="20" />
              <rect width="8" height="8" x="46" y="46" />
              <rect width="8" height="8" x="20" y="46" />
              <rect width="8" height="8" x="72" y="46" />
              <rect width="8" height="8" x="46" y="72" />
              <rect width="8" height="8" x="72" y="72" />
            </svg>
          </div>
          <div class="text-xs text-[var(--color-text-secondary)]">
            请打开对应 App 扫码授权
          </div>
        </div>
      </div>

      <!-- Countdown -->
      <div v-if="!errorMsg && !loading" class="text-xs text-[var(--color-text-tertiary)] flex items-center gap-1.5">
        <span>⏱️ 二维码有效时间:</span>
        <span class="font-mono font-bold text-[var(--color-brand-600)]">{{ countdown }}s</span>
      </div>

      <!-- Action Buttons -->
      <div class="flex items-center gap-2 w-full pt-2">
        <AdaptiveButton variant="outline" size="sm" class="flex-1" @click="handleCancel">
          <span>取消</span>
        </AdaptiveButton>
        <AdaptiveButton variant="subtle" size="sm" class="flex-1" @click="startLoginFlow">
          <span>刷新二维码</span>
        </AdaptiveButton>
      </div>
    </div>
  </AdaptiveModal>
</template>
