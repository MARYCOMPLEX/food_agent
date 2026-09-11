import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
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

export interface UseResearchSessionReactOptions extends Omit<ResearchSseTransportOptions, 'sessionId' | 'onMessage' | 'onStateChange' | 'onError'> {
  readonly snapshot?: UserResearchProjectionV1 | null
  readonly autoStart?: boolean
  readonly onMessage?: (message: ResearchTransportMessage) => void
  readonly onStateChange?: (state: ResearchTransportState) => void
  readonly onError?: (error: Error) => void
}

export interface UseResearchSessionReactResult {
  readonly state: ResearchSessionState
  readonly projection: UserResearchProjectionV1 | null
  readonly legacyEvents: readonly LegacyTransportMessage[]
  readonly transportState: ResearchTransportState
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

export function dispatchLegacyTransportMessageToStore(
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

export function useResearchSessionReact(
  sessionId: string,
  options: UseResearchSessionReactOptions = {},
): UseResearchSessionReactResult {
  const store = useMemo(
    () => createResearchSessionStore({ snapshot: options.snapshot }),
    [sessionId],
  )

  const state = useSyncExternalStore(
    useCallback((onStoreChange) => store.subscribe(onStoreChange), [store]),
    useCallback(() => store.getState(), [store]),
    useCallback(() => store.getState(), [store]),
  )

  const [transportState, setTransportState] = useState<ResearchTransportState>('idle')
  const seenLegacyCursors = useRef(new Set<string>())

  const rememberLegacyCursor = useCallback((key: string): void => {
    seenLegacyCursors.current.add(key)
    if (seenLegacyCursors.current.size > 256) {
      const first = seenLegacyCursors.current.values().next().value as string | undefined
      if (first) seenLegacyCursors.current.delete(first)
    }
  }, [])

  const optionsRef = useRef(options)
  optionsRef.current = options

  const transport = useMemo(() => {
    return new ResearchSseTransport({
      ...options,
      sessionId,
      onMessage: (message) => {
        if (message.kind === 'legacy' || message.kind === 'control') {
          const legacyKey = message.cursor ? `${message.eventName}:${message.cursor}` : null
          if (legacyKey && seenLegacyCursors.current.has(legacyKey)) {
            store.dispatch(message)
          } else {
            if (legacyKey) rememberLegacyCursor(legacyKey)
            dispatchLegacyTransportMessageToStore(store, sessionId, message)
          }
        } else {
          store.dispatch(message)
        }
        optionsRef.current.onMessage?.(message)
      },
      onStateChange: (nextState) => {
        setTransportState(nextState)
        optionsRef.current.onStateChange?.(nextState)
      },
      onError: (error) => {
        store.markTransportError(error)
        optionsRef.current.onError?.(error)
      },
    })
  }, [sessionId, store, rememberLegacyCursor])

  const start = useCallback(() => {
    transport.start()
  }, [transport])

  const stop = useCallback(() => {
    transport.stop()
  }, [transport])

  const reset = useCallback(() => {
    store.reset()
  }, [store])

  useEffect(() => {
    if (options.autoStart) {
      start()
    }
    return () => {
      transport.stop()
    }
  }, [options.autoStart, start, transport])

  const initializeSnapshot = useCallback(
    (snapshot: UserResearchProjectionV1, cursor?: string | null) => store.initializeSnapshot(snapshot, cursor),
    [store],
  )

  const appendEvent = useCallback(
    (event: ResearchEventV1, cursor?: string | null) => store.appendEvent(event, cursor),
    [store],
  )

  const dispatch = useCallback(
    (message: ResearchTransportMessage) => store.dispatch(message),
    [store],
  )

  return {
    state,
    projection: state.projection,
    legacyEvents: state.legacyEvents,
    transportState,
    store,
    transport,
    start,
    stop,
    reset,
    initializeSnapshot,
    appendEvent,
    dispatch,
  }
}
