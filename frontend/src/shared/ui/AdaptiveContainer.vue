<script setup lang="ts">
import { useDevice } from '../utils/device'

const props = withDefaults(
  defineProps<{
    maxWidth?: 'sm' | 'md' | 'lg' | 'xl' | '2xl' | 'full'
    noPadding?: boolean
  }>(),
  {
    maxWidth: 'xl',
    noPadding: false,
  },
)

const { isMobile } = useDevice()
</script>

<template>
  <div
    class="w-full mx-auto transition-all"
    :class="[
      props.maxWidth === 'sm' && 'max-w-screen-sm',
      props.maxWidth === 'md' && 'max-w-screen-md',
      props.maxWidth === 'lg' && 'max-w-screen-lg',
      props.maxWidth === 'xl' && 'max-w-screen-xl',
      props.maxWidth === '2xl' && 'max-w-screen-2xl',
      props.maxWidth === 'full' && 'max-w-full',
      !props.noPadding && (isMobile ? 'px-4 py-3' : 'px-6 py-6'),
    ]"
  >
    <slot />
  </div>
</template>
