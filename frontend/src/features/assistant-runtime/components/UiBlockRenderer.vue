<script setup lang="ts">
import { computed } from 'vue'
import UnknownUiBlock from './UnknownUiBlock.vue'
import type { AssistantUiBlock, AssistantUiBlockRegistry } from '../types'

const props = defineProps<{
  block: AssistantUiBlock
  registry: AssistantUiBlockRegistry
}>()

const resolved = computed(() => {
  const entry = props.registry.get(props.block.renderer)
  if (!entry) return { kind: 'unknown' as const }
  if (!entry.schema) return { kind: 'ready' as const, component: entry.component, data: props.block.data }

  const parsed = entry.schema.safeParse(props.block.data)
  if (!parsed.success) return { kind: 'invalid' as const }
  return { kind: 'ready' as const, component: entry.component, data: parsed.data }
})
</script>

<template>
  <UnknownUiBlock v-if="resolved.kind === 'unknown'" :block="block" />
  <UnknownUiBlock v-else-if="resolved.kind === 'invalid'" :block="block" reason="invalid" />
  <component
    :is="resolved.component"
    :block="block"
    :data="resolved.data"
    v-else
  />
</template>
