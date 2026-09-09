<script setup lang="ts">
import UnknownUiBlock from './UnknownUiBlock.vue'
import type { AssistantUiBlock } from '../types'

const props = defineProps<{ blockId: string }>()

const block: AssistantUiBlock = {
  id: props.blockId,
  renderer: 'app.missing-block@1',
  schemaVersion: 1,
  revision: 0,
  status: 'error',
  data: null,
}
</script>

<template>
  <UnknownUiBlock :block="block" reason="missing" />
</template>
