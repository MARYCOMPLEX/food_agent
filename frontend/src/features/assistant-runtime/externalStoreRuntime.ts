import { computed, getCurrentInstance, onUnmounted, shallowRef, type Ref } from 'vue'
import type {
  AssistantDomainMessage,
  AssistantExternalStoreRuntime,
  AssistantStoreListener,
  AssistantStoreSnapshot,
  AssistantTransport,
  AssistantUiBlock,
  AssistantExternalStoreLike,
} from './types'

function nowIso(): string {
  return new Date().toISOString()
}

function createInitialSnapshot(threadId = 'local-thread'): AssistantStoreSnapshot {
  return {
    threadId,
    messages: [],
    uiBlocks: {},
    isRunning: false,
    runStatus: null,
    lastSequence: 0,
    syncStatus: 'idle',
  }
}

function normalizeMessages(messages: AssistantDomainMessage[]): AssistantDomainMessage[] {
  return messages.map(message => ({
    ...message,
    parts: [...message.parts],
  }))
}

export class AssistantExternalStore implements AssistantExternalStoreLike {
  private snapshot: AssistantStoreSnapshot
  private readonly listeners = new Set<AssistantStoreListener>()

  constructor(initial?: Partial<AssistantStoreSnapshot>) {
    this.snapshot = {
      ...createInitialSnapshot(initial?.threadId),
      ...initial,
      messages: normalizeMessages(initial?.messages ?? []),
      uiBlocks: { ...(initial?.uiBlocks ?? {}) },
    }
  }

  getSnapshot(): AssistantStoreSnapshot {
    return this.snapshot
  }

  subscribe(listener: AssistantStoreListener): () => void {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  replace(snapshot: AssistantStoreSnapshot): void {
    this.commit({
      ...snapshot,
      messages: normalizeMessages(snapshot.messages),
      uiBlocks: { ...snapshot.uiBlocks },
    })
  }

  setMessages(messages: AssistantDomainMessage[]): void {
    this.commit({ ...this.snapshot, messages: normalizeMessages(messages) })
  }

  upsertMessage(message: AssistantDomainMessage): void {
    const index = this.snapshot.messages.findIndex(item => item.id === message.id)
    const messages = [...this.snapshot.messages]
    if (index === -1) messages.push({ ...message, parts: [...message.parts] })
    else messages[index] = { ...message, parts: [...message.parts] }
    this.commit({ ...this.snapshot, messages })
  }

  upsertBlock(block: AssistantUiBlock): void {
    const previous = this.snapshot.uiBlocks[block.id]
    if (previous && previous.revision > block.revision) return
    this.commit({
      ...this.snapshot,
      uiBlocks: { ...this.snapshot.uiBlocks, [block.id]: { ...block } },
    })
  }

  removeBlock(blockId: string): void {
    if (!(blockId in this.snapshot.uiBlocks)) return
    const uiBlocks = { ...this.snapshot.uiBlocks }
    delete uiBlocks[blockId]
    this.commit({ ...this.snapshot, uiBlocks })
  }

  setRunState(patch: Pick<AssistantStoreSnapshot, 'isRunning' | 'runStatus' | 'lastSequence' | 'syncStatus'>): void {
    this.commit({ ...this.snapshot, ...patch })
  }

  private commit(next: AssistantStoreSnapshot): void {
    this.snapshot = next
    for (const listener of this.listeners) listener(this.snapshot)
  }
}

export class ExternalStoreRuntime implements AssistantExternalStoreRuntime {
  readonly store: AssistantExternalStoreLike
  private readonly transport?: AssistantTransport

  constructor(store: AssistantExternalStoreLike, transport?: AssistantTransport) {
    this.store = store
    this.transport = transport
  }

  getSnapshot(): AssistantStoreSnapshot {
    return this.store.getSnapshot()
  }

  subscribe(listener: AssistantStoreListener): () => void {
    return this.store.subscribe(listener)
  }

  async sendMessage(content: string): Promise<void> {
    const text = content.trim()
    if (!text) return

    const snapshot = this.store.getSnapshot()
    const message: AssistantDomainMessage = {
      id: `user-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      role: 'user',
      parts: [{ id: `text-${Date.now()}`, kind: 'text', text }],
      status: 'complete',
      createdAt: nowIso(),
    }
    this.store.upsertMessage(message)
    if (!this.transport?.sendMessage) return

    this.store.setRunState({
      isRunning: true,
      runStatus: 'running',
      lastSequence: snapshot.lastSequence,
      syncStatus: 'streaming',
    })
    try {
      await this.transport.sendMessage({ threadId: snapshot.threadId, message })
    }
    catch (error) {
      this.store.setRunState({
        isRunning: false,
        runStatus: 'failed',
        lastSequence: this.store.getSnapshot().lastSequence,
        syncStatus: 'error',
      })
      throw error
    }
  }

  async cancel(): Promise<void> {
    const threadId = this.store.getSnapshot().threadId
    await this.transport?.cancelRun?.(threadId)
    this.store.setRunState({
      isRunning: false,
      runStatus: 'cancelled',
      lastSequence: this.store.getSnapshot().lastSequence,
      syncStatus: this.store.getSnapshot().syncStatus,
    })
  }

  async reload(): Promise<void> {
    const threadId = this.store.getSnapshot().threadId
    await this.transport?.reloadThread?.(threadId)
  }
}

export function createAssistantExternalStore(initial?: Partial<AssistantStoreSnapshot>): AssistantExternalStore {
  return new AssistantExternalStore(initial)
}

export function createExternalStoreRuntime(
  store: AssistantExternalStoreLike,
  transport?: AssistantTransport,
): ExternalStoreRuntime {
  return new ExternalStoreRuntime(store, transport)
}

/**
 * Vue equivalent of assistant-ui's useExternalStoreRuntime subscription.
 * The returned ref is intentionally a projection of the domain store, so a
 * React adapter can use the same runtime without importing Vue.
 */
export function useExternalStoreRuntime(runtime: AssistantExternalStoreRuntime): {
  snapshot: Readonly<Ref<AssistantStoreSnapshot>>
  runtime: AssistantExternalStoreRuntime
} {
  const snapshot = shallowRef(runtime.getSnapshot())
  const unsubscribe = runtime.subscribe((next) => {
    snapshot.value = next
  })

  if (getCurrentInstance()) onUnmounted(unsubscribe)

  return {
    snapshot: computed(() => snapshot.value),
    runtime,
  }
}
