<script setup lang="ts">
import { watch } from 'vue'
import { useDevice } from '../utils/device'

const props = withDefaults(
  defineProps<{
    modelValue: boolean
    title?: string
    width?: string
  }>(),
  {
    width: '480px',
  },
)

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'close'): void
}>()

const { isMobile } = useDevice()

function close() {
  emit('update:modelValue', false)
  emit('close')
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      document.body.style.overflow = 'hidden'
    }
    else {
      document.body.style.overflow = ''
    }
  },
)
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div
        v-if="modelValue"
        class="fixed inset-0 bg-black/50 z-[1050] backdrop-blur-xs flex items-center justify-center p-4"
        @click.self="close"
      >
        <div
          class="bg-[var(--color-bg-surface)] rounded-modal shadow-2xl border border-[var(--color-border)] w-full max-h-[90vh] flex flex-col overflow-hidden animate-scale-in"
          :style="{ maxWidth: isMobile ? '100%' : width }"
        >
          <div class="flex items-center justify-between px-5 py-4 border-b border-[var(--color-border)]">
            <h3 class="text-base md:text-lg font-semibold text-[var(--color-text-primary)]">
              {{ title || '' }}
            </h3>
            <button
              class="p-1 rounded-full text-[var(--color-text-tertiary)] hover:bg-[var(--color-neutral-150)] cursor-pointer"
              @click="close"
            >
              ✕
            </button>
          </div>

          <div class="flex-1 overflow-y-auto px-5 py-4">
            <slot />
          </div>

          <div v-if="$slots.footer" class="px-5 py-3 border-t border-[var(--color-border)] bg-[var(--color-bg-subtle)] flex justify-end gap-2">
            <slot name="footer" />
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.fade-enter-active, .fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from, .fade-leave-to {
  opacity: 0;
}
.animate-scale-in {
  animation: scaleIn 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}
@keyframes scaleIn {
  from {
    opacity: 0;
    transform: scale(0.95);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}
</style>
