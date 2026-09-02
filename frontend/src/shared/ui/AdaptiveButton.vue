<script setup lang="ts">
import { computed } from 'vue'
import { useDevice } from '../utils/device'

const props = withDefaults(
  defineProps<{
    variant?: 'primary' | 'secondary' | 'subtle' | 'outline' | 'danger' | 'ghost'
    size?: 'sm' | 'md' | 'lg'
    loading?: boolean
    disabled?: boolean
    block?: boolean
    icon?: string
  }>(),
  {
    variant: 'primary',
    size: 'md',
    loading: false,
    disabled: false,
    block: false,
  },
)

const emit = defineEmits<{
  (e: 'click', event: MouseEvent): void
}>()

const { isMobile } = useDevice()

const variantClasses = computed(() => {
  switch (props.variant) {
    case 'primary':
      return 'bg-[var(--color-brand-500)] text-white hover:bg-[var(--color-brand-600)] active:bg-[var(--color-brand-700)] shadow-sm'
    case 'secondary':
      return 'bg-[var(--color-neutral-150)] text-[var(--color-text-primary)] hover:bg-[var(--color-neutral-200)] border border-[var(--color-border)]'
    case 'subtle':
      return 'bg-[var(--color-brand-50)] text-[var(--color-brand-700)] hover:bg-[var(--color-brand-100)]'
    case 'outline':
      return 'bg-transparent text-[var(--color-text-primary)] border border-[var(--color-border)] hover:bg-[var(--color-neutral-100)]'
    case 'danger':
      return 'bg-red-500 text-white hover:bg-red-600 active:bg-red-700 shadow-sm'
    case 'ghost':
      return 'bg-transparent text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)] hover:bg-[var(--color-neutral-100)]'
    default:
      return ''
  }
})

const sizeClasses = computed(() => {
  if (isMobile.value) {
    switch (props.size) {
      case 'sm':
        return 'px-3 py-1.5 text-xs min-h-[32px]'
      case 'lg':
        return 'px-5 py-3.5 text-base min-h-[48px]'
      default:
        return 'px-4 py-2.5 text-sm min-h-[42px]'
    }
  }
  else {
    switch (props.size) {
      case 'sm':
        return 'px-2.5 py-1 text-xs min-h-[28px]'
      case 'lg':
        return 'px-5 py-2.5 text-base min-h-[44px]'
      default:
        return 'px-3.5 py-2 text-sm min-h-[36px]'
    }
  }
})
</script>

<template>
  <button
    :disabled="disabled || loading"
    class="inline-flex items-center justify-center font-medium rounded-btn transition-colors focus-ring disabled:opacity-50 disabled:cursor-not-allowed select-none touch-manipulation cursor-pointer"
    :class="[
      variantClasses,
      sizeClasses,
      block ? 'w-full' : '',
    ]"
    @click="(e) => !disabled && !loading && emit('click', e)"
  >
    <svg
      v-if="loading"
      class="animate-spin -ml-1 mr-2 h-4 w-4 text-current"
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
    >
      <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
      <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
    </svg>
    <slot />
  </button>
</template>
