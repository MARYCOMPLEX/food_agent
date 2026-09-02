<script setup lang="ts">
import { watch } from 'vue'
import { useDevice } from '../utils/device'

const props = withDefaults(
  defineProps<{
    modelValue: boolean
    title?: string
    width?: string
    maxHeight?: string
  }>(),
  {
    width: '460px',
    maxHeight: '88vh',
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

// Prevent body scroll when open
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
        class="fixed inset-0 bg-black/40 z-[1050] backdrop-blur-xs transition-opacity"
        @click="close"
      />
    </Transition>

    <!-- Mobile Bottom Sheet / Fullscreen Sheet -->
    <Transition v-if="isMobile" name="slide-up">
      <div
        v-if="modelValue"
        class="fixed inset-x-0 bottom-0 z-[1060] bg-[var(--color-bg-surface)] rounded-t-2xl shadow-2xl flex flex-col max-h-[92vh] border-t border-[var(--color-border)]"
        :style="{ height: maxHeight }"
      >
        <!-- Grabber bar -->
        <div class="flex justify-center pt-2.5 pb-1">
          <div class="w-10 h-1.5 bg-[var(--color-neutral-300)] rounded-full" />
        </div>

        <div class="flex items-center justify-between px-4 py-3 border-b border-[var(--color-border)]">
          <h3 class="text-base font-semibold text-[var(--color-text-primary)] truncate">
            {{ title || '' }}
          </h3>
          <button
            class="p-1.5 rounded-full text-[var(--color-text-tertiary)] hover:bg-[var(--color-neutral-150)] cursor-pointer"
            @click="close"
          >
            <span class="text-lg leading-none">✕</span>
          </button>
        </div>

        <div class="flex-1 overflow-y-auto px-4 py-4 overscroll-contain">
          <slot />
        </div>

        <div v-if="$slots.footer" class="px-4 py-3 border-t border-[var(--color-border)] bg-[var(--color-bg-subtle)]">
          <slot name="footer" />
        </div>
      </div>
    </Transition>

    <!-- Desktop Slide-out Drawer (from right) -->
    <Transition v-else name="slide-left">
      <div
        v-if="modelValue"
        class="fixed inset-y-0 right-0 z-[1060] bg-[var(--color-bg-surface)] shadow-2xl flex flex-col border-l border-[var(--color-border)]"
        :style="{ width }"
      >
        <div class="flex items-center justify-between px-5 py-4 border-b border-[var(--color-border)]">
          <h3 class="text-lg font-semibold text-[var(--color-text-primary)] truncate">
            {{ title || '' }}
          </h3>
          <button
            class="p-1.5 rounded-full text-[var(--color-text-tertiary)] hover:bg-[var(--color-neutral-150)] hover:text-[var(--color-text-primary)] cursor-pointer transition-colors"
            @click="close"
          >
            <span class="text-lg leading-none">✕</span>
          </button>
        </div>

        <div class="flex-1 overflow-y-auto px-6 py-5">
          <slot />
        </div>

        <div v-if="$slots.footer" class="px-6 py-4 border-t border-[var(--color-border)] bg-[var(--color-bg-subtle)]">
          <slot name="footer" />
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

.slide-left-enter-active, .slide-left-leave-active {
  transition: transform 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}
.slide-left-enter-from, .slide-left-leave-to {
  transform: translateX(100%);
}

.slide-up-enter-active, .slide-up-leave-active {
  transition: transform 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}
.slide-up-enter-from, .slide-up-leave-to {
  transform: translateY(100%);
}
</style>
