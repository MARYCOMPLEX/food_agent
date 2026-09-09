import { parseResearchEventV1, parseUserResearchProjectionV1 } from '../../../shared/contracts/research'
import type {
  ResearchEventV1,
  UserResearchProjectionV1,
} from '../../../shared/contracts/research'
import {
  createInitialResearchProjection,
  ResearchProjectionIdentityError,
  ResearchProjectionSequenceError,
  ResearchProjectionTerminalError,
  researchProjectionReducer,
} from './reducer'
import type { LegacyTransportMessage, ResearchTransportMessage } from './transport'

export const MAX_PENDING_RESEARCH_EVENTS = 256
export const MAX_LEGACY_TRANSPORT_EVENTS = 128

export interface ResearchSequenceGap {
  expectedSequence: number
  receivedSequence: number
  pendingSequences: readonly number[]
  detectedAt: string
}

export type ResearchSyncState = 'idle' | 'synced' | 'gap' | 'resync_required' | 'terminal' | 'error'

export interface ResearchSessionState {
  readonly projection: UserResearchProjectionV1 | null
  readonly syncState: ResearchSyncState
  readonly sequenceGap: ResearchSequenceGap | null
  readonly transportCursor: string | null
  readonly legacyEvents: readonly LegacyTransportMessage[]
  readonly lastError: Error | null
  readonly duplicateEventCount: number
  readonly staleEventCount: number
  readonly ignoredSnapshotCount: number
}

export type ResearchSessionListener = (state: ResearchSessionState) => void

export interface ResearchSessionStoreOptions {
  snapshot?: UserResearchProjectionV1 | null
  transportCursor?: string | null
}

export interface ResearchStoreDispatchResult {
  readonly accepted: boolean
  readonly buffered: boolean
  readonly duplicate: boolean
  readonly ignored: boolean
  readonly state: ResearchSessionState
}

function errorFrom(value: unknown): Error {
  return value instanceof Error ? value : new Error(String(value))
}

function nowIso(): string {
  return new Date().toISOString()
}

function isResearchEventMessage(message: ResearchTransportMessage): message is Extract<ResearchTransportMessage, { kind: 'research_event' }> {
  return message.kind === 'research_event'
}

function isSnapshotMessage(message: ResearchTransportMessage): message is Extract<ResearchTransportMessage, { kind: 'snapshot' }> {
  return message.kind === 'snapshot'
}

export class ResearchSessionStore {
  private state: ResearchSessionState
  private readonly listeners = new Set<ResearchSessionListener>()
  private readonly pendingEvents = new Map<number, ResearchEventV1>()
  private readonly ignoredEventIds = new Set<string>()

  constructor(options: ResearchSessionStoreOptions = {}) {
    const projection = options.snapshot ? parseUserResearchProjectionV1(options.snapshot) : null
    this.state = {
      projection,
      syncState: projection ? (projection.termination ? 'terminal' : 'synced') : 'idle',
      sequenceGap: null,
      transportCursor: options.transportCursor ?? null,
      legacyEvents: [],
      lastError: null,
      duplicateEventCount: 0,
      staleEventCount: 0,
      ignoredSnapshotCount: 0,
    }
  }

  getState(): ResearchSessionState {
    return this.state
  }

  subscribe(listener: ResearchSessionListener): () => void {
    this.listeners.add(listener)
    listener(this.state)
    return () => this.listeners.delete(listener)
  }

  initializeSnapshot(snapshot: UserResearchProjectionV1, transportCursor?: string | null): ResearchStoreDispatchResult {
    try {
      const parsed = parseUserResearchProjectionV1(snapshot)
      const current = this.state.projection
      if (current && this.isOlderSnapshot(current, parsed)) {
        this.publish({
          ...this.state,
          transportCursor: transportCursor ?? this.state.transportCursor,
          ignoredSnapshotCount: this.state.ignoredSnapshotCount + 1,
          lastError: null,
        })
        return this.result(false, false, false, true)
      }

      this.pendingEvents.clear()
      this.state = {
        ...this.state,
        projection: parsed,
        syncState: parsed.termination ? 'terminal' : 'synced',
        sequenceGap: null,
        transportCursor: transportCursor ?? this.state.transportCursor,
        lastError: null,
      }
      this.publish(this.state)
      return this.result(true, false, false, false)
    }
    catch (error) {
      return this.fail(error)
    }
  }

  appendEvent(rawEvent: ResearchEventV1, transportCursor?: string | null): ResearchStoreDispatchResult {
    let event: ResearchEventV1
    try {
      event = parseResearchEventV1(rawEvent)
    }
    catch (error) {
      return this.fail(error)
    }

    const projection = this.state.projection ?? createInitialResearchProjection(
      event.sessionId,
      event.taskId,
      event.turnId,
      event.runId,
    )
    try {
      if (projection.appliedEventIds?.includes(event.eventId) || this.ignoredEventIds.has(event.eventId)) {
        this.publish({
          ...this.state,
          projection,
          transportCursor: transportCursor ?? this.state.transportCursor,
          duplicateEventCount: this.state.duplicateEventCount + 1,
          lastError: null,
        })
        return this.result(false, false, true, false)
      }
      if (!this.state.projection) this.state = { ...this.state, projection }
      if (event.sessionId !== projection.sessionId || event.taskId !== projection.taskId || event.turnId !== projection.turnId || (projection.runId && event.runId && projection.runId !== event.runId)) {
        throw new ResearchProjectionIdentityError('event identity does not match the active research projection')
      }

      const expected = projection.lastSequence + 1
      if (event.sequence < expected) {
        this.ignoredEventIds.add(event.eventId)
        this.publish({
          ...this.state,
          projection,
          transportCursor: transportCursor ?? this.state.transportCursor,
          syncState: 'synced',
          staleEventCount: this.state.staleEventCount + 1,
          lastError: null,
        })
        return this.result(false, false, false, true)
      }
      if (event.sequence > expected) {
        if (this.pendingEvents.size >= MAX_PENDING_RESEARCH_EVENTS) {
          this.pendingEvents.clear()
          this.publish({
            ...this.state,
            projection,
            syncState: 'resync_required',
            sequenceGap: {
              expectedSequence: expected,
              receivedSequence: event.sequence,
              pendingSequences: [],
              detectedAt: nowIso(),
            },
            transportCursor: transportCursor ?? this.state.transportCursor,
            lastError: null,
          })
          return this.result(false, false, false, true)
        }
        this.pendingEvents.set(event.sequence, event)
        this.publish({
          ...this.state,
          projection,
          syncState: 'gap',
          sequenceGap: {
            expectedSequence: expected,
            receivedSequence: event.sequence,
            pendingSequences: [...this.pendingEvents.keys()].sort((a, b) => a - b),
            detectedAt: this.state.sequenceGap?.detectedAt ?? nowIso(),
          },
          transportCursor: transportCursor ?? this.state.transportCursor,
          lastError: null,
        })
        return this.result(false, true, false, false)
      }

      this.pendingEvents.delete(event.sequence)
      let nextProjection = this.applyContiguous(projection, event)
      while (this.pendingEvents.has(nextProjection.lastSequence + 1)) {
        const nextEvent = this.pendingEvents.get(nextProjection.lastSequence + 1)
        if (!nextEvent) break
        this.pendingEvents.delete(nextEvent.sequence)
        nextProjection = this.applyContiguous(nextProjection, nextEvent)
      }
      const pendingSequences = [...this.pendingEvents.keys()].sort((a, b) => a - b)
      const nextState: ResearchSessionState = {
        ...this.state,
        projection: nextProjection,
        syncState: pendingSequences.length ? 'gap' : (nextProjection.termination ? 'terminal' : 'synced'),
        sequenceGap: pendingSequences.length
          ? {
              expectedSequence: nextProjection.lastSequence + 1,
              receivedSequence: pendingSequences[pendingSequences.length - 1] ?? nextProjection.lastSequence,
              pendingSequences,
              detectedAt: this.state.sequenceGap?.detectedAt ?? nowIso(),
            }
          : null,
        transportCursor: transportCursor ?? this.state.transportCursor,
        lastError: null,
      }
      this.publish(nextState)
      return this.result(true, false, false, false)
    }
    catch (error) {
      if (error instanceof ResearchProjectionSequenceError && error.receivedSequence > error.expectedSequence) {
        this.pendingEvents.set(event.sequence, event)
        this.publish({
          ...this.state,
          projection,
          syncState: 'gap',
          sequenceGap: {
            expectedSequence: error.expectedSequence,
            receivedSequence: error.receivedSequence,
            pendingSequences: [...this.pendingEvents.keys()].sort((a, b) => a - b),
            detectedAt: this.state.sequenceGap?.detectedAt ?? nowIso(),
          },
          transportCursor: transportCursor ?? this.state.transportCursor,
          lastError: null,
        })
        return this.result(false, true, false, false)
      }
      if (error instanceof ResearchProjectionTerminalError) {
        this.ignoredEventIds.add(event.eventId)
        this.publish({
          ...this.state,
          projection,
          syncState: 'terminal',
          transportCursor: transportCursor ?? this.state.transportCursor,
          staleEventCount: this.state.staleEventCount + 1,
          lastError: null,
        })
        return this.result(false, false, false, true)
      }
      return this.fail(error)
    }
  }

  dispatch(message: ResearchTransportMessage): ResearchStoreDispatchResult {
    if (isResearchEventMessage(message)) return this.appendEvent(message.event, message.cursor)
    if (isSnapshotMessage(message)) return this.initializeSnapshot(message.snapshot, message.cursor)
    return this.appendLegacy(message)
  }

  markTransportError(error: unknown): void {
    this.publish({ ...this.state, syncState: 'error', lastError: errorFrom(error) })
  }

  reset(): void {
    this.pendingEvents.clear()
    this.ignoredEventIds.clear()
    this.publish({
      ...this.state,
      projection: null,
      syncState: 'idle',
      sequenceGap: null,
      transportCursor: null,
      legacyEvents: [],
      lastError: null,
      duplicateEventCount: 0,
      staleEventCount: 0,
      ignoredSnapshotCount: 0,
    })
  }

  private applyContiguous(projection: UserResearchProjectionV1, event: ResearchEventV1): UserResearchProjectionV1 {
    return researchProjectionReducer.apply(projection, event)
  }

  private isOlderSnapshot(current: UserResearchProjectionV1, incoming: UserResearchProjectionV1): boolean {
    return incoming.revision < current.revision || incoming.lastSequence < current.lastSequence
  }

  private appendLegacy(message: LegacyTransportMessage): ResearchStoreDispatchResult {
    this.publish({
      ...this.state,
      transportCursor: message.cursor ?? this.state.transportCursor,
      legacyEvents: [...this.state.legacyEvents, message].slice(-MAX_LEGACY_TRANSPORT_EVENTS),
      lastError: null,
    })
    return this.result(false, false, false, false)
  }

  private result(accepted: boolean, buffered: boolean, duplicate: boolean, ignored: boolean): ResearchStoreDispatchResult {
    return { accepted, buffered, duplicate, ignored, state: this.state }
  }

  private fail(error: unknown): ResearchStoreDispatchResult {
    const nextError = errorFrom(error)
    this.publish({ ...this.state, syncState: 'error', lastError: nextError })
    return this.result(false, false, false, true)
  }

  private publish(nextState: ResearchSessionState): void {
    this.state = nextState
    for (const listener of this.listeners) listener(this.state)
  }
}

export function createResearchSessionStore(options: ResearchSessionStoreOptions = {}): ResearchSessionStore {
  return new ResearchSessionStore(options)
}
