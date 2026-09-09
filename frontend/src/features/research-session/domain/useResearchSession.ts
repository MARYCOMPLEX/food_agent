import { computed, onUnmounted, ref, shallowRef } from 'vue'
import type { Ref } from 'vue'
import type { ResearchEventV1, UserResearchProjectionV1 } from '../../../shared/contracts/research'
import { createResearchSessionStore } from './store'
import type {
  ResearchSessionState,
  ResearchSessionStore,
  ResearchStoreDispatchResult,
} from './store'
import { ResearchSseTransport } from './transport'
import type {
  LegacyTransportMessage,
  ResearchSseTransportOptions,
  ResearchTransportMessage,
  ResearchTransportState,
} from './transport'
import { legacyToResearchEvents } from './transport'

export interface UseResearchSessionOptions extends Omit<ResearchSseTransportOptions, 'sessionId' | 'onMessage' | 'onStateChange' | 'onError'> {
  readonly snapshot?: UserResearchProjectionV1 | null
  readonly autoStart?: boolean
  readonly onMessage?: (message: ResearchTransportMessage) => void
  readonly onStateChange?: (state: ResearchTransportState) => void
  readonly onError?: (error: Error) => void
}

export interface UseResearchSessionResult {
  readonly state: Readonly<Ref<ResearchSessionState>>
  readonly projection: Readonly<Ref<UserResearchProjectionV1 | null>>
  readonly legacyEvents: Readonly<Ref<ResearchSessionState['legacyEvents']>>
  readonly transportState: Readonly<Ref<ResearchTransportState>>
  readonly store: ResearchSessionStore
  readonly transport: ResearchSseTransport
  readonly start: () => void
  readonly stop: () => void
  readonly reset: () => void
  readonly initializeSnapshot: (snapshot: UserResearchProjectionV1, cursor?: string | null) => ResearchStoreDispatchResult
  readonly appendEvent: (event: ResearchEventV1, cursor?: string | null) => ResearchStoreDispatchResult
  readonly dispatch: (message: ResearchTransportMessage) => ResearchStoreDispatchResult
}

function legacyDataRecord(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function legacyString(value: unknown): string | undefined {
  return typeof value === 'string' && value.length > 0 ? value : undefined
}

function legacyNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isInteger(value) && value > 0 ? value : undefined
}

/**
 * Feed a legacy SSE frame into the same projection store as ResearchEvent v1.
 * The generated events are deliberately partial: they contain only fields that
 * the old wire format can prove and never fabricate evidence or controversies.
 */
export function dispatchLegacyTransportMessage(
  store: ResearchSessionStore,
  sessionId: string,
  message: LegacyTransportMessage,
): readonly ResearchStoreDispatchResult[] {
  const stored = store.dispatch(message)
  const state = stored.state
  const data = legacyDataRecord(message.data)
  const projection = state.projection
  const taskId = legacyString(data.taskId) ?? projection?.taskId ?? `legacy-task-${sessionId}`
  const turnId = legacyNumber(data.turnId) ?? projection?.turnId ?? 1
  const events = legacyToResearchEvents(message, {
    sessionId,
    taskId,
    turnId,
    runId: legacyString(data.runId) ?? projection?.runId ?? null,
    startSequence: (projection?.lastSequence ?? 0) + 1,
    occurredAt: legacyString(data.occurredAt),
  })
  return events.map(event => store.appendEvent(event, message.cursor))
}

export function useResearchSession(
  sessionId: string,
  options: UseResearchSessionOptions = {},
): UseResearchSessionResult {
  const store = createResearchSessionStore({ snapshot: options.snapshot })
  const state = shallowRef<ResearchSessionState>(store.getState())
  const transportState = ref<ResearchTransportState>('idle')
  const seenLegacyCursors = new Set<string>()
  const rememberLegacyCursor = (key: string): void => {
    seenLegacyCursors.add(key)
    if (seenLegacyCursors.size > 256) {
      const first = seenLegacyCursors.values().next().value as string | undefined
      if (first) seenLegacyCursors.delete(first)
    }
  }
  const unsubscribe = store.subscribe((nextState) => {
    state.value = nextState
  })
  const transport = new ResearchSseTransport({
    ...options,
    sessionId,
    onMessage: (message) => {
      if (message.kind === 'legacy' || message.kind === 'control') {
        const legacyKey = message.cursor ? `${message.eventName}:${message.cursor}` : null
        if (legacyKey && seenLegacyCursors.has(legacyKey)) {
          store.dispatch(message)
        }
        else {
          if (legacyKey) rememberLegacyCursor(legacyKey)
          dispatchLegacyTransportMessage(store, sessionId, message)
        }
      }
      else {
        store.dispatch(message)
      }
      options.onMessage?.(message)
    },
    onStateChange: (nextState) => {
      transportState.value = nextState
      options.onStateChange?.(nextState)
    },
    onError: (error) => {
      store.markTransportError(error)
      options.onError?.(error)
    },
  })

  const projection = computed(() => state.value.projection)
  const legacyEvents = computed(() => state.value.legacyEvents)

  function start(): void {
    transport.start()
  }

  function stop(): void {
    transport.stop()
  }

  function reset(): void {
    store.reset()
  }

  if (options.autoStart) start()

  onUnmounted(() => {
    unsubscribe()
    transport.stop()
  })

  return {
    state,
    projection,
    legacyEvents,
    transportState,
    store,
    transport,
    start,
    stop,
    reset,
    initializeSnapshot: (snapshot, cursor) => store.initializeSnapshot(snapshot, cursor),
    appendEvent: (event, cursor) => store.appendEvent(event, cursor),
    dispatch: message => store.dispatch(message),
  }
}
