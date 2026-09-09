import { API_BASE_URL, getDefaultHeaders } from '../../../shared/api/config'
import {
  parseResearchEventV1,
  parseUserResearchProjectionV1,
  RESEARCH_EVENT_SCHEMA_VERSION,
  USER_RESEARCH_PROJECTION_SCHEMA_VERSION,
} from '../../../shared/contracts/research'
import type {
  ResearchEventV1,
  ResearchJsonValue,
  ResearchRunStatusV1,
  UserResearchProjectionV1,
} from '../../../shared/contracts/research'

export type ResearchTransportState = 'idle' | 'connecting' | 'connected' | 'reconnecting' | 'disconnected' | 'completed' | 'error'

export interface LegacyTransportMessage {
  readonly kind: 'legacy' | 'control'
  readonly eventName: string
  readonly data: unknown
  readonly cursor: string | null
}

export type ResearchTransportMessage =
  | {
      readonly kind: 'research_event'
      readonly eventName: string
      readonly event: ResearchEventV1
      readonly cursor: string | null
    }
  | {
      readonly kind: 'snapshot'
      readonly eventName: string
      readonly snapshot: UserResearchProjectionV1
      readonly cursor: string | null
    }
  | LegacyTransportMessage

export interface ResearchTransportError extends Error {
  readonly eventName?: string
  readonly cursor?: string | null
}

export interface ResearchSseTransportOptions {
  readonly sessionId: string
  readonly apiBaseUrl?: string
  readonly sseVersion?: 'v1' | 'legacy'
  readonly headers?: HeadersInit
  readonly fetchImpl?: typeof fetch
  readonly lastEventId?: string | null
  readonly autoReconnect?: boolean
  readonly maxReconnectAttempts?: number
  readonly reconnectDelayMs?: number
  readonly onMessage?: (message: ResearchTransportMessage) => void
  readonly onStateChange?: (state: ResearchTransportState) => void
  readonly onError?: (error: Error) => void
}

export interface ResearchSseFrame {
  readonly eventName: string
  readonly data: string
  readonly cursor: string | null
}

export type LegacySemanticKind = 'status' | 'progress' | 'action' | 'recommendation' | 'result' | 'error' | 'done' | 'unknown'

export interface NormalizedLegacyTransportMessage extends LegacyTransportMessage {
  readonly semantic: LegacySemanticKind
  readonly compatibility: 'partial'
}

export interface LegacyResearchEventContext {
  readonly sessionId: string
  readonly taskId: string
  readonly turnId: number
  readonly runId?: string | null
  readonly startSequence: number
  readonly occurredAt?: string
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function parseJson(data: string): unknown {
  try {
    return JSON.parse(data) as unknown
  }
  catch {
    return data
  }
}

function nestedCandidates(value: unknown): unknown[] {
  if (!isRecord(value)) return []
  return [
    value,
    value.event,
    value.researchEvent,
    value.researchEventV1,
    value.projection,
    value.snapshot,
    value.data,
  ]
}

function findResearchEvent(value: unknown): ResearchEventV1 | null {
  for (const candidate of nestedCandidates(value)) {
    if (!isRecord(candidate) || candidate.schemaVersion !== RESEARCH_EVENT_SCHEMA_VERSION) continue
    return parseResearchEventV1(candidate)
  }
  return null
}

function findProjection(value: unknown): UserResearchProjectionV1 | null {
  for (const candidate of nestedCandidates(value)) {
    if (!isRecord(candidate) || candidate.schemaVersion !== USER_RESEARCH_PROJECTION_SCHEMA_VERSION) continue
    return parseUserResearchProjectionV1(candidate)
  }
  return null
}

export function classifyResearchSseFrame(frame: ResearchSseFrame): ResearchTransportMessage {
  const parsed = parseJson(frame.data)
  const event = findResearchEvent(parsed)
  if (event) {
    return {
      kind: 'research_event',
      eventName: frame.eventName,
      event,
      cursor: frame.cursor,
    }
  }
  const snapshot = findProjection(parsed)
  if (snapshot) {
    return {
      kind: 'snapshot',
      eventName: frame.eventName,
      snapshot,
      cursor: frame.cursor,
    }
  }
  return {
    kind: frame.eventName === 'replay_expired' || frame.eventName === 'error' || frame.eventName === 'done' ? 'control' : 'legacy',
    eventName: frame.eventName,
    data: parsed,
    cursor: frame.cursor,
  }
}

function legacySemantic(eventName: string): LegacySemanticKind {
  switch (eventName) {
    case 'status': return 'status'
    case 'progress': return 'progress'
    case 'intent_parsed':
    case 'analysis_done':
    case 'step_start':
    case 'step_done':
    case 'step_error': return 'action'
    case 'restaurant': return 'recommendation'
    case 'notes_found': return 'result'
    case 'result': return 'result'
    case 'error': return 'error'
    case 'done': return 'done'
    default: return 'unknown'
  }
}

export function normalizeLegacyTransportMessage(message: LegacyTransportMessage): NormalizedLegacyTransportMessage {
  return {
    ...message,
    semantic: legacySemantic(message.eventName),
    compatibility: 'partial',
  }
}

function legacyRecord(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function legacyString(value: unknown): string | undefined {
  return typeof value === 'string' && value.length > 0 ? value : undefined
}

function legacyNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function legacyPositiveInteger(value: unknown): number | undefined {
  const number = legacyNumber(value)
  return number !== undefined && Number.isInteger(number) && number > 0 ? number : undefined
}

function legacyConfidence(value: unknown): number | null {
  const number = legacyNumber(value)
  return number !== undefined && number >= 0 && number <= 1 ? number : null
}

function legacyStatus(value: unknown): ResearchRunStatusV1 | undefined {
  return value === 'queued' || value === 'running' || value === 'succeeded' || value === 'partial' || value === 'failed' || value === 'cancelled' || value === 'blocked'
    ? value
    : undefined
}

function safeLegacyId(value: string): string {
  return value.replace(/[^A-Za-z0-9._:-]/g, '_').slice(0, 200) || 'legacy'
}

function legacyEvent(
  context: LegacyResearchEventContext,
  sequence: number,
  kind: ResearchEventV1['kind'],
  payload: ResearchJsonValue,
  status?: ResearchRunStatusV1,
): ResearchEventV1 {
  return parseResearchEventV1({
    schemaVersion: RESEARCH_EVENT_SCHEMA_VERSION,
    eventId: `legacy-${safeLegacyId(context.sessionId)}-${sequence}`,
    sessionId: context.sessionId,
    taskId: context.taskId,
    turnId: context.turnId,
    runId: context.runId ?? null,
    sequence,
    occurredAt: context.occurredAt ?? new Date().toISOString(),
    kind,
    status: status ?? null,
    mutation: kind === 'evidence_added' ? 'append' : 'upsert',
    payload,
  })
}

function legacyProgressPayload(data: Record<string, unknown>): Record<string, ResearchJsonValue> {
  const payload: Record<string, ResearchJsonValue> = {}
  const step = legacyString(data.step) ?? legacyString(data.stepId)
  const detail = legacyString(data.detail) ?? legacyString(data.message)
  const phase = legacyString(data.phase)
  const summary = legacyString(data.summary) ?? legacyString(data.message)
  const progress = legacyNumber(data.progress)
  if (step) payload.stepId = step
  if (detail) payload.detail = detail
  if (phase) payload.phase = phase
  if (summary) payload.summary = summary
  if (progress !== undefined) payload.progress = progress
  return payload
}

function legacyStepId(eventName: string, data: Record<string, unknown>): string {
  const explicit = legacyString(data.step) ?? legacyString(data.stepId)
  if (explicit) return explicit
  if (eventName === 'intent_parsed') return 'intent_parsing'
  if (eventName === 'analysis_done') return 'evidence_analysis'
  if (eventName === 'notes_found') return 'evidence_collection'
  return 'legacy_action'
}

function legacyActionPayload(eventName: string, data: Record<string, unknown>): Record<string, ResearchJsonValue> {
  const payload = legacyProgressPayload(data)
  const stepId = legacyStepId(eventName, data)
  payload.stepId = stepId
  payload.label = legacyString(data.label) ?? stepId
  if (eventName === 'step_error') {
    payload.stepStatus = 'failed'
    payload.detail = legacyString(data.error) ?? payload.detail ?? 'Legacy step failed'
  }
  else if (eventName === 'step_start') {
    payload.stepStatus = 'running'
  }
  else {
    payload.stepStatus = 'succeeded'
  }
  return payload
}

function legacyCandidateValues(eventName: string, data: Record<string, unknown>): unknown[] {
  if (eventName === 'restaurant') {
    return [data.restaurant ?? data.recommendation ?? data]
  }
  const candidates = data.recommendations ?? data.restaurants ?? data.candidates ?? data.items
  return Array.isArray(candidates) ? candidates : []
}

function legacyRecommendationPayload(
  raw: unknown,
  index: number,
  status: 'candidate' | 'recommended',
  requireShopIdentity = false,
): Record<string, ResearchJsonValue> | null {
  const envelope = legacyRecord(raw)
  const nested = isRecord(envelope.restaurant)
    ? envelope.restaurant
    : isRecord(envelope.shop) ? envelope.shop : {}
  const recommendation = { ...nested, ...envelope }
  if (requireShopIdentity && !(
    legacyString(recommendation.restaurantId)
    || legacyString(recommendation.shopId)
    || legacyString(recommendation.restaurantName)
    || legacyString(recommendation.storeName)
    || legacyString(recommendation.name)
    || isRecord(recommendation.restaurant)
    || isRecord(recommendation.shop)
  )) return null
  const recommendationId = legacyString(recommendation.recommendationId)
    ?? legacyString(recommendation.restaurantId)
    ?? legacyString(recommendation.shopId)
    ?? legacyString(recommendation.id)
    ?? legacyString(recommendation.name)
    ?? legacyString(recommendation.title)
  const title = legacyString(recommendation.name)
    ?? legacyString(recommendation.title)
    ?? legacyString(recommendation.restaurantName)
    ?? legacyString(recommendation.storeName)
  if (!recommendationId || !title) return null
  const payload: Record<string, ResearchJsonValue> = {
    recommendation: {
      recommendationId,
      title,
      summary: legacyString(recommendation.oneLiner) ?? legacyString(recommendation.summary) ?? '',
      status,
      rank: legacyPositiveInteger(recommendation.rank) ?? index + 1,
      confidence: legacyConfidence(recommendation.confidence),
    },
  }
  return payload
}

export function legacyToResearchEvents(
  message: LegacyTransportMessage,
  context: LegacyResearchEventContext,
): ResearchEventV1[] {
  const normalized = normalizeLegacyTransportMessage(message)
  const data = legacyRecord(normalized.data)
  let sequence = context.startSequence
  if (normalized.semantic === 'action') {
    const status = normalized.eventName === 'step_error' ? 'running' : 'running'
    const kind: ResearchEventV1['kind'] = normalized.eventName === 'step_start'
      ? 'action_started'
      : normalized.eventName === 'step_done' || normalized.eventName === 'intent_parsed' || normalized.eventName === 'analysis_done'
        ? 'action_completed'
        : 'action_progress'
    return [legacyEvent(context, sequence, kind, legacyActionPayload(normalized.eventName, data), status)]
  }
  if (normalized.semantic === 'progress' || normalized.semantic === 'status') {
    const payload = legacyProgressPayload(data)
    const step = legacyString(data.step) ?? legacyString(data.stepId)
    return [legacyEvent(context, sequence, step ? 'action_progress' : 'run_progress', payload, legacyStatus(data.status) ?? 'running')]
  }
  if (normalized.semantic === 'recommendation' || normalized.semantic === 'result') {
    const status = normalized.eventName === 'result' ? 'recommended' : 'candidate'
    const events = legacyCandidateValues(normalized.eventName, data)
      .map((candidate, index) => legacyRecommendationPayload(candidate, index, status, normalized.eventName === 'notes_found'))
      .filter((payload): payload is Record<string, ResearchJsonValue> => payload !== null)
      .map(payload => legacyEvent(context, sequence++, 'recommendation_upserted', payload))
    if (events.length) return events
    if (normalized.eventName === 'notes_found') {
      return [legacyEvent(context, sequence, 'action_completed', legacyActionPayload('notes_found', data), 'running')]
    }
    return [legacyEvent(context, sequence, 'run_progress', {
      summary: legacyString(data.summary) ?? '',
    }, 'running')]
  }
  if (normalized.semantic === 'error') {
    const rawError = legacyRecord(data.error)
    const code = legacyString(rawError.code) ?? legacyString(data.code) ?? 'legacy_error'
    const messageText = legacyString(rawError.message) ?? legacyString(data.message) ?? 'Legacy search failed'
    return [
      legacyEvent(context, sequence++, 'gap_upserted', {
        gap: {
          gapId: `legacy-gap-${sequence}`,
          source: 'legacy-sse',
          operation: 'search',
          code,
          message: messageText,
          retryable: rawError.retryable === true,
          severity: 'error',
          status: 'exhausted',
        },
      }),
      legacyEvent(context, sequence, 'run_failed', { reason: code, message: messageText }, 'failed'),
    ]
  }
  if (normalized.semantic === 'done') {
    const status = legacyStatus(data.status) === 'partial' ? 'partial' : 'succeeded'
    return [legacyEvent(context, sequence, 'run_completed', {
      message: legacyString(data.message) ?? legacyString(data.summary) ?? 'Search completed',
    }, status)]
  }
  return []
}

export class ResearchSseTransport {
  private readonly options: Required<Pick<ResearchSseTransportOptions, 'sessionId' | 'apiBaseUrl' | 'sseVersion' | 'autoReconnect' | 'maxReconnectAttempts' | 'reconnectDelayMs'>> & ResearchSseTransportOptions
  private state: ResearchTransportState = 'idle'
  private cursor: string | null
  private controller: AbortController | null = null
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private reconnectAttempts = 0
  private stopped = true
  private frameEventName = 'message'
  private frameDataLines: string[] = []
  private frameCursor: string | null = null

  constructor(options: ResearchSseTransportOptions) {
    this.options = {
      ...options,
      apiBaseUrl: options.apiBaseUrl ?? API_BASE_URL,
      sseVersion: options.sseVersion ?? 'v1',
      autoReconnect: options.autoReconnect ?? true,
      maxReconnectAttempts: options.maxReconnectAttempts ?? 5,
      reconnectDelayMs: options.reconnectDelayMs ?? 1_500,
    }
    this.cursor = options.lastEventId ?? null
  }

  getState(): ResearchTransportState {
    return this.state
  }

  getLastEventId(): string | null {
    return this.cursor
  }

  start(): void {
    if (!this.stopped && (this.state === 'connecting' || this.state === 'connected' || this.state === 'reconnecting')) return
    this.stopped = false
    this.reconnectAttempts = 0
    void this.open()
  }

  stop(): void {
    this.stopped = true
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    this.controller?.abort()
    this.controller = null
    this.setState('disconnected')
  }

  private async open(): Promise<void> {
    if (this.stopped) return
    this.setState(this.reconnectAttempts ? 'reconnecting' : 'connecting')
    this.controller = new AbortController()
    const base = this.options.apiBaseUrl.replace(/\/$/, '')
    const params = new URLSearchParams({ sseVersion: this.options.sseVersion })
    const url = `${base}/v1/search/stream/${encodeURIComponent(this.options.sessionId)}?${params.toString()}`
    const headers = new Headers({
      ...getDefaultHeaders(),
      Accept: 'text/event-stream',
      ...(this.options.headers ?? {}),
    })
    if (this.cursor) headers.set('Last-Event-ID', this.cursor)

    try {
      const fetchImpl = this.options.fetchImpl ?? fetch
      const response = await fetchImpl(url, { method: 'GET', headers, signal: this.controller.signal })
      if (!response.ok) throw new Error(`SSE stream failed with status ${response.status}`)
      if (!response.body) throw new Error('SSE response does not provide a readable body')
      this.reconnectAttempts = 0
      this.setState('connected')
      await this.consume(response.body)
      if (!this.stopped && this.state !== 'completed') this.scheduleReconnect()
    }
    catch (error) {
      if (this.stopped || (error instanceof Error && error.name === 'AbortError')) return
      const normalized = error instanceof Error ? error : new Error(String(error))
      this.options.onError?.(normalized)
      this.setState('error')
      this.scheduleReconnect()
    }
  }

  private async consume(body: ReadableStream<Uint8Array>): Promise<void> {
    const reader = body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    try {
      while (!this.stopped) {
        const chunk = await reader.read()
        buffer += decoder.decode(chunk.value ?? new Uint8Array(), { stream: !chunk.done })
        const lines = buffer.split(/\r\n|\r|\n/)
        buffer = lines.pop() ?? ''
        this.consumeLines(lines)
        if (chunk.done) break
      }
      if (buffer) this.consumeLines([buffer])
      this.flushFrame()
    }
    finally {
      reader.releaseLock()
    }
  }

  private consumeLines(lines: readonly string[]): void {
    for (const line of lines) {
      if (line === '') {
        this.flushFrame()
        continue
      }
      if (line.startsWith(':')) continue
      const separator = line.indexOf(':')
      const field = separator >= 0 ? line.slice(0, separator) : line
      const value = separator >= 0 ? line.slice(separator + 1).replace(/^ /, '') : ''
      if (field === 'event') this.frameEventName = value || 'message'
      else if (field === 'data') this.frameDataLines.push(value)
      else if (field === 'id') this.frameCursor = value
    }
  }

  private flushFrame(): void {
    if (!this.frameDataLines.length) {
      this.frameEventName = 'message'
      this.frameCursor = null
      return
    }
    const cursor = this.frameCursor ?? this.cursor
    if (this.frameCursor) this.cursor = this.frameCursor
    const message = classifyResearchSseFrame({
      eventName: this.frameEventName,
      data: this.frameDataLines.join('\n'),
      cursor,
    })
    this.options.onMessage?.(message)
    if (message.kind === 'control' && message.eventName === 'done') {
      this.setState('completed')
      this.stopped = true
    }
    this.frameEventName = 'message'
    this.frameDataLines = []
    this.frameCursor = null
  }

  private scheduleReconnect(): void {
    if (this.stopped || !this.options.autoReconnect || this.reconnectAttempts >= this.options.maxReconnectAttempts) {
      if (!this.stopped) this.setState('disconnected')
      return
    }
    this.reconnectAttempts += 1
    const delay = this.options.reconnectDelayMs * 1.5 ** (this.reconnectAttempts - 1)
    this.setState('reconnecting')
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      void this.open()
    }, delay)
  }

  private setState(state: ResearchTransportState): void {
    this.state = state
    this.options.onStateChange?.(state)
  }
}
