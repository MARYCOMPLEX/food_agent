<script setup lang="ts">
import { createElement } from 'react'
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { createRoot, type Root } from 'react-dom/client'
import ReactAssistantIsland from '../../assistant-runtime/ReactAssistantIsland'
import type {
  AssistantDomainMessage,
  AssistantExternalStoreLike,
} from '../../assistant-runtime/types'
import type { ReactAssistantUiRegistry } from '../../assistant-runtime/ReactAssistantIsland'

const props = defineProps<{
  store: AssistantExternalStoreLike
  registry?: ReactAssistantUiRegistry
  onNew?: (message: AssistantDomainMessage) => Promise<void>
  onCancel?: () => Promise<void>
}>()

const mountPoint = ref<HTMLElement | null>(null)
let root: Root | null = null

function renderIsland(): void {
  if (!root || !mountPoint.value) return
  root.render(createElement(ReactAssistantIsland, {
    store: props.store,
    registry: props.registry,
    onNew: props.onNew,
    onCancel: props.onCancel,
    className: 'research-react-island',
  }))
}

onMounted(() => {
  if (!mountPoint.value) return
  root = createRoot(mountPoint.value)
  renderIsland()
})

watch(() => [props.store, props.registry, props.onNew, props.onCancel], renderIsland)

onUnmounted(() => {
  root?.unmount()
  root = null
})
</script>

<template>
  <div ref="mountPoint" class="research-react-island-host" aria-label="研究对话运行时" />
</template>

<style>
.research-react-island-host {
  min-width: 0;
}

.research-react-island {
  display: grid;
  min-width: 0;
  overflow: hidden;
  border: 1px solid var(--color-border, #d1d7e0);
  border-radius: 14px;
  background: var(--color-bg-surface, #fff);
  box-shadow: 0 8px 24px rgb(16 24 40 / 5%);
}

.assistant-ui-island__messages {
  display: grid;
  gap: 12px;
  max-height: 280px;
  overflow-y: auto;
  padding: 16px 18px;
  background: #fcfcfd;
}

.assistant-ui-message {
  display: grid;
  gap: 5px;
  min-width: 0;
}

.assistant-ui-message--user {
  justify-self: end;
  width: min(88%, 620px);
}

.assistant-ui-message__role {
  color: var(--color-text-tertiary, #667085);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: .08em;
  text-transform: uppercase;
}

.assistant-ui-message--user .assistant-ui-message__role {
  text-align: right;
}

.assistant-ui-message__parts {
  display: grid;
  gap: 8px;
}

.assistant-ui-message__parts > p {
  margin: 0;
  padding: 10px 12px;
  border: 1px solid var(--color-border-muted, #e4e8ee);
  border-radius: 10px;
  color: var(--color-text-primary, #101828);
  background: #fff;
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
}

.assistant-ui-message--user .assistant-ui-message__parts > p {
  border-color: var(--color-brand-150-exact, #dce2ff);
  color: var(--color-brand-900, #201a67);
  background: var(--color-brand-50, #edf0ff);
}

.assistant-ui-island__composer {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  align-items: end;
  padding: 12px 14px;
  border-top: 1px solid var(--color-border-muted, #e4e8ee);
  background: #fff;
}

.assistant-ui-island__composer textarea {
  min-height: 42px;
  max-height: 120px;
  resize: vertical;
  border: 1px solid var(--color-border, #d1d7e0);
  border-radius: 9px;
  padding: 10px 11px;
  outline: none;
  color: var(--color-text-primary, #101828);
  font-size: 13px;
  line-height: 1.45;
}

.assistant-ui-island__composer textarea:focus {
  border-color: var(--color-brand-500, #4f46e5);
  box-shadow: 0 0 0 3px rgb(79 70 229 / 12%);
}

.assistant-ui-island__composer button {
  min-height: 42px;
  border: 0;
  border-radius: 9px;
  padding: 0 15px;
  color: #fff;
  background: var(--color-brand-600, #3b30d9);
  cursor: pointer;
  font-size: 12px;
  font-weight: 800;
}

.assistant-ui-island__composer button:disabled {
  cursor: not-allowed;
  opacity: .45;
}

.assistant-ui-unknown-block {
  display: grid;
  gap: 3px;
  border: 1px dashed var(--color-border, #d1d7e0);
  border-radius: 9px;
  padding: 9px 11px;
  color: var(--color-text-secondary, #475467);
  background: #fff;
  font-size: 11px;
}

.assistant-ui-tool-call {
  display: flex;
  gap: 8px;
  border: 1px dashed var(--color-border, #d1d7e0);
  border-radius: 9px;
  padding: 9px 11px;
  color: var(--color-text-secondary, #475467);
  font-size: 11px;
}

@media (max-width: 640px) {
  .assistant-ui-island__messages { max-height: 220px; padding: 13px 12px; }
  .assistant-ui-message--user { width: 95%; }
  .assistant-ui-island__composer { grid-template-columns: 1fr; }
  .assistant-ui-island__composer button { width: 100%; }
}
</style>
