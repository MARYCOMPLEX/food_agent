<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import MissingUiBlock from './components/MissingUiBlock.vue'
import UiBlockRenderer from './components/UiBlockRenderer.vue'
import { createAssistantExternalStore, createExternalStoreRuntime, useExternalStoreRuntime } from './externalStoreRuntime'
import { createResearchUiBlockRegistry } from './renderers'
import type {
  AssistantDomainMessage,
  AssistantExternalStoreRuntime,
  AssistantMessagePart,
  AssistantUiBlock,
  AssistantUiBlockRegistry,
} from './types'

const props = withDefaults(defineProps<{
  runtime?: AssistantExternalStoreRuntime
  messages?: AssistantDomainMessage[]
  uiBlocks?: AssistantUiBlock[] | Record<string, AssistantUiBlock>
  isRunning?: boolean
  title?: string
  subtitle?: string
  placeholder?: string
  submitLabel?: string
  emptyLabel?: string
  showComposer?: boolean
  registry?: AssistantUiBlockRegistry
}>(), {
  isRunning: false,
  title: '研究对话',
  subtitle: '证据、争议和店铺档案会随着研究进展持续补充',
  placeholder: '继续追问这次研究…',
  submitLabel: '发送',
  emptyLabel: '研究结果将在这里逐步出现。',
  showComposer: true,
})

const emit = defineEmits<{
  submit: [content: string]
  cancel: []
  'block-action': [action: { blockId: string, actionId: string, payload?: unknown }]
}>()

const ownedRuntime = createExternalStoreRuntime(createAssistantExternalStore({
  messages: props.messages ?? [],
  uiBlocks: normalizeBlocks(props.uiBlocks),
  isRunning: props.isRunning,
  syncStatus: 'idle',
}))
const activeRuntime = props.runtime ?? ownedRuntime
const { snapshot } = useExternalStoreRuntime(activeRuntime)
const registry = props.registry ?? createResearchUiBlockRegistry()
const composerValue = ref('')

function normalizeBlocks(value: AssistantRuntimeShellProps['uiBlocks']): Record<string, AssistantUiBlock> {
  if (!value) return {}
  if (Array.isArray(value)) return Object.fromEntries(value.map(block => [block.id, block]))
  return { ...value }
}

type AssistantRuntimeShellProps = {
  uiBlocks?: AssistantUiBlock[] | Record<string, AssistantUiBlock>
}

watch(
  [() => props.messages, () => props.uiBlocks, () => props.isRunning],
  ([messages, uiBlocks, isRunning]) => {
    if (props.runtime) return
    const current = ownedRuntime.getSnapshot()
    ownedRuntime.store.replace({
      ...current,
      messages: messages ? [...messages] : current.messages,
      uiBlocks: uiBlocks ? normalizeBlocks(uiBlocks) : current.uiBlocks,
      isRunning: isRunning ?? current.isRunning,
    })
  },
  { deep: true },
)

const visibleMessages = computed(() => snapshot.value.messages)
const isRunning = computed(() => snapshot.value.isRunning)

function blockFor(part: AssistantMessagePart): AssistantUiBlock | undefined {
  return part.kind === 'ui' ? snapshot.value.uiBlocks[part.blockId] : undefined
}

function roleLabel(role: AssistantDomainMessage['role']): string {
  if (role === 'user') return '你'
  if (role === 'system') return '系统'
  return '研究助手'
}

function submit(): void {
  const content = composerValue.value.trim()
  if (!content || isRunning.value) return
  composerValue.value = ''
  emit('submit', content)
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    submit()
  }
}

function cancel(): void {
  emit('cancel')
  void activeRuntime.cancel()
}

function emitBlockAction(block: AssistantUiBlock, actionId: string, payload?: unknown): void {
  emit('block-action', { blockId: block.id, actionId, payload })
}
</script>

<template>
  <section class="assistant-runtime-shell" aria-label="研究对话">
    <header class="assistant-runtime-shell__header">
      <div>
        <span class="assistant-runtime-shell__eyebrow">FOOD RESEARCH / LIVE THREAD</span>
        <h2>{{ title }}</h2>
        <p>{{ subtitle }}</p>
      </div>
      <div class="assistant-runtime-shell__state" :data-running="isRunning">
        <span class="assistant-runtime-shell__state-dot" aria-hidden="true" />
        {{ isRunning ? '研究中' : '已同步' }}
      </div>
    </header>

    <div class="assistant-runtime-shell__viewport" aria-live="polite">
      <div v-if="!visibleMessages.length" class="assistant-runtime-shell__empty">
        <div class="assistant-runtime-shell__empty-mark" aria-hidden="true">+</div>
        <p>{{ emptyLabel }}</p>
      </div>

      <article
        v-for="message in visibleMessages"
        :key="message.id"
        class="assistant-message"
        :class="`assistant-message--${message.role}`"
      >
        <div class="assistant-message__meta">
          <span>{{ roleLabel(message.role) }}</span>
          <span v-if="message.status !== 'complete'" class="assistant-message__status">{{ message.status }}</span>
        </div>

        <div class="assistant-message__parts">
          <template v-for="part in message.parts" :key="part.id">
            <p v-if="part.kind === 'text'" class="assistant-message__text">{{ part.text }}</p>
            <details v-else-if="part.kind === 'reasoning'" class="assistant-message__reasoning" :open="!part.collapsed">
              <summary>研究思路摘要</summary>
              <p>{{ part.text }}</p>
            </details>
            <div v-else-if="part.kind === 'tool'" class="assistant-tool-call">
              <div class="assistant-tool-call__name">{{ part.toolName }}</div>
              <span class="assistant-tool-call__status">{{ part.status }}</span>
              <code v-if="part.argsText">{{ part.argsText }}</code>
            </div>
            <UiBlockRenderer
              v-else-if="part.kind === 'ui' && blockFor(part)"
              :block="blockFor(part)!"
              :registry="registry"
              @click="(event: MouseEvent) => {
                const target = event.target as HTMLElement
                const actionId = target.dataset.actionId
                if (actionId) emitBlockAction(blockFor(part)!, actionId)
              }"
            />
            <MissingUiBlock v-else-if="part.kind === 'ui'" :block-id="part.blockId" />
          </template>
        </div>
      </article>

      <div v-if="isRunning" class="assistant-runtime-shell__working">
        <span class="assistant-runtime-shell__working-pulse" aria-hidden="true" />
        正在整理新的评论证据…
      </div>
    </div>

    <form v-if="showComposer" class="assistant-composer" @submit.prevent="submit">
      <textarea
        v-model="composerValue"
        :placeholder="placeholder"
        :disabled="isRunning"
        rows="2"
        @keydown="handleKeydown"
      />
      <div class="assistant-composer__footer">
        <span>Enter 发送 · Shift + Enter 换行</span>
        <button v-if="isRunning" type="button" class="assistant-composer__cancel" @click="cancel">停止研究</button>
        <button v-else type="submit" :disabled="!composerValue.trim()">{{ submitLabel }}</button>
      </div>
    </form>
  </section>
</template>

<style scoped>
.assistant-runtime-shell {
  --assistant-border: var(--color-border-muted, #e4e8ee);
  --assistant-ink: var(--color-text-primary, #101828);
  --assistant-muted: var(--color-text-muted, #667085);
  display: grid;
  min-height: 520px;
  overflow: hidden;
  border: 1px solid var(--assistant-border);
  border-radius: 18px;
  background: var(--color-bg-surface, #fff);
  box-shadow: 0 12px 32px rgb(16 24 40 / 6%);
}

.assistant-runtime-shell__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  padding: 22px 24px 18px;
  border-bottom: 1px solid var(--assistant-border);
  background: linear-gradient(120deg, #fff, #f8f9fb);
}

.assistant-runtime-shell__eyebrow {
  display: block;
  margin-bottom: 7px;
  color: var(--color-brand-600, #3b30d9);
  font-size: 9px;
  font-weight: 850;
  letter-spacing: .14em;
}

.assistant-runtime-shell__header h2 {
  margin: 0;
  color: var(--assistant-ink);
  font-size: clamp(18px, 2vw, 23px);
  letter-spacing: -.02em;
}

.assistant-runtime-shell__header p {
  max-width: 560px;
  margin: 5px 0 0;
  color: var(--assistant-muted);
  font-size: 12px;
  line-height: 1.5;
}

.assistant-runtime-shell__state {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  flex: 0 0 auto;
  padding: 7px 10px;
  border: 1px solid var(--assistant-border);
  border-radius: 999px;
  color: var(--assistant-muted);
  font-size: 11px;
  font-weight: 700;
}

.assistant-runtime-shell__state-dot,
.assistant-runtime-shell__working-pulse {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--color-success-600-exact, #16a34a);
}

.assistant-runtime-shell__state[data-running='true'] .assistant-runtime-shell__state-dot,
.assistant-runtime-shell__working-pulse {
  background: var(--color-brand-500, #4f46e4);
  animation: assistant-pulse 1.25s ease-in-out infinite;
}

.assistant-runtime-shell__viewport {
  display: grid;
  align-content: start;
  gap: 16px;
  min-height: 280px;
  max-height: min(68vh, 760px);
  overflow-y: auto;
  padding: 24px;
  background: #fcfcfd;
}

.assistant-runtime-shell__empty {
  display: grid;
  place-items: center;
  min-height: 220px;
  color: var(--assistant-muted);
  text-align: center;
}

.assistant-runtime-shell__empty-mark {
  display: grid;
  width: 38px;
  height: 38px;
  margin-bottom: 10px;
  place-items: center;
  border: 1px solid var(--assistant-border);
  border-radius: 12px;
  color: var(--color-brand-600, #3b30d9);
  font-size: 24px;
  font-weight: 300;
}

.assistant-runtime-shell__empty p {
  margin: 0;
  font-size: 13px;
}

.assistant-message {
  display: grid;
  gap: 7px;
  max-width: min(920px, 100%);
}

.assistant-message--user {
  justify-self: end;
  width: min(640px, 88%);
}

.assistant-message__meta {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--assistant-muted);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: .03em;
  text-transform: uppercase;
}

.assistant-message--user .assistant-message__meta { justify-content: flex-end; }

.assistant-message__status {
  padding: 2px 6px;
  border-radius: 5px;
  color: var(--color-brand-700, #2a1faf);
  background: var(--color-brand-50, #edf0ff);
  font-size: 9px;
  text-transform: none;
}

.assistant-message__parts {
  display: grid;
  gap: 10px;
}

.assistant-message__text {
  max-width: 760px;
  margin: 0;
  padding: 12px 14px;
  border: 1px solid var(--assistant-border);
  border-radius: 12px;
  color: var(--assistant-ink);
  background: #fff;
  font-size: 13px;
  line-height: 1.65;
  white-space: pre-wrap;
}

.assistant-message--user .assistant-message__text {
  border-color: var(--color-brand-150-exact, #dce2ff);
  color: var(--color-brand-900, #201a67);
  background: var(--color-brand-50, #edf0ff);
}

.assistant-message__reasoning,
.assistant-tool-call {
  padding: 10px 12px;
  border: 1px dashed var(--assistant-border);
  border-radius: 10px;
  color: var(--assistant-muted);
  background: #fff;
  font-size: 12px;
}

.assistant-message__reasoning summary { cursor: pointer; font-weight: 700; }
.assistant-message__reasoning p { margin: 8px 0 0; line-height: 1.55; }

.assistant-tool-call {
  display: flex;
  align-items: center;
  gap: 8px;
}

.assistant-tool-call__name { flex: 1; color: var(--assistant-ink); font-weight: 700; }
.assistant-tool-call__status { font-size: 10px; }
.assistant-tool-call code { max-width: 44%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.assistant-runtime-shell__working {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--assistant-muted);
  font-size: 12px;
}

.assistant-composer {
  display: grid;
  gap: 8px;
  padding: 14px 18px 16px;
  border-top: 1px solid var(--assistant-border);
  background: #fff;
}

.assistant-composer textarea {
  width: 100%;
  resize: vertical;
  border: 1px solid var(--assistant-border);
  border-radius: 11px;
  padding: 11px 12px;
  outline: none;
  color: var(--assistant-ink);
  background: #fff;
  font: inherit;
  font-size: 13px;
  line-height: 1.5;
}

.assistant-composer textarea:focus { border-color: var(--color-brand-400, #6a60e8); box-shadow: 0 0 0 3px rgb(79 70 228 / 10%); }
.assistant-composer textarea:disabled { cursor: wait; background: #f8f9fb; }

.assistant-composer__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: var(--assistant-muted);
  font-size: 10px;
}

.assistant-composer button {
  border: 0;
  border-radius: 8px;
  padding: 8px 13px;
  color: #fff;
  background: var(--color-brand-600, #3b30d9);
  cursor: pointer;
  font-size: 11px;
  font-weight: 750;
}

.assistant-composer button:disabled { cursor: not-allowed; opacity: .45; }
.assistant-composer__cancel { color: #b42318 !important; background: #fef3f2 !important; }

@keyframes assistant-pulse {
  0%, 100% { opacity: .4; transform: scale(.85); }
  50% { opacity: 1; transform: scale(1.1); }
}

@media (max-width: 640px) {
  .assistant-runtime-shell__header { padding: 18px 16px 15px; }
  .assistant-runtime-shell__viewport { padding: 18px 14px; }
  .assistant-runtime-shell__header p { display: none; }
  .assistant-message--user { width: 94%; }
  .assistant-composer { padding-inline: 14px; }
  .assistant-composer__footer > span { display: none; }
}
</style>
