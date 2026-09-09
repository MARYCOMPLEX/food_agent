import {
  parseResearchEventV1,
  parseUserResearchProjectionV1,
  USER_RESEARCH_PROJECTION_SCHEMA_VERSION,
} from '../../../shared/contracts/research'
import type {
  ResearchEntityRefV1,
  ResearchEventV1,
  ResearchEvidenceItemV1,
  ResearchGapViewV1,
  ResearchJsonValue,
  ResearchPlanStepViewV1,
  ResearchRunStatusV1,
  ResearchStepStatusV1,
  UserResearchProjectionV1,
} from '../../../shared/contracts/research'

export const MAX_APPLIED_EVENT_IDS = 2_048

const TERMINAL_STATUSES = new Set<ResearchRunStatusV1>([
  'succeeded',
  'partial',
  'failed',
  'cancelled',
  'blocked',
])

const EMPTY_VALUES = new Set<unknown>([null, '', undefined])

export class ResearchProjectionError extends Error {
  readonly code: string

  constructor(code: string, message: string) {
    super(message)
    this.name = 'ResearchProjectionError'
    this.code = code
  }
}

export class ResearchProjectionIdentityError extends ResearchProjectionError {
  constructor(message: string) {
    super('identity_mismatch', message)
    this.name = 'ResearchProjectionIdentityError'
  }
}

export class ResearchProjectionSequenceError extends ResearchProjectionError {
  readonly expectedSequence: number
  readonly receivedSequence: number

  constructor(expectedSequence: number, receivedSequence: number, reason: string) {
    super('sequence_gap', `${reason}: expected ${expectedSequence}, received ${receivedSequence}`)
    this.name = 'ResearchProjectionSequenceError'
    this.expectedSequence = expectedSequence
    this.receivedSequence = receivedSequence
  }
}

export class ResearchProjectionTerminalError extends ResearchProjectionError {
  constructor(eventId: string) {
    super('terminal_projection', `terminal projection cannot apply event ${eventId}`)
    this.name = 'ResearchProjectionTerminalError'
  }
}

type UnknownObject = Record<string, unknown>

function isObject(value: unknown): value is UnknownObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function asObject(value: unknown, label: string): UnknownObject {
  if (!isObject(value)) {
    throw new ResearchProjectionError('invalid_payload', `${label} must be an object`)
  }
  return value
}

function asString(value: unknown): string | undefined {
  return typeof value === 'string' && value.length > 0 ? value : undefined
}

function asArray(value: unknown): unknown[] | undefined {
  return Array.isArray(value) ? value : undefined
}

function nowIso(): string {
  return new Date().toISOString()
}

export function createInitialResearchProjection(
  sessionId: string,
  taskId: string,
  turnId: number,
  runId?: string | null,
): UserResearchProjectionV1 {
  return parseUserResearchProjectionV1({
    schemaVersion: USER_RESEARCH_PROJECTION_SCHEMA_VERSION,
    sessionId,
    taskId,
    turnId,
    runId: runId ?? null,
    revision: 0,
    lastSequence: 0,
    status: 'queued',
    plan: [],
    evidence: [],
    controversies: [],
    profiles: [],
    recommendations: [],
    gaps: [],
    metrics: {},
    updatedAt: nowIso(),
    appliedEventIds: [],
  })
}

function checkIdentity(projection: UserResearchProjectionV1, event: ResearchEventV1): void {
  if (projection.sessionId !== event.sessionId) {
    throw new ResearchProjectionIdentityError('event sessionId does not match projection')
  }
  if (projection.taskId !== event.taskId) {
    throw new ResearchProjectionIdentityError('event taskId does not match projection')
  }
  if (projection.turnId !== event.turnId) {
    throw new ResearchProjectionIdentityError('event turnId does not match projection')
  }
  if (projection.runId && event.runId && projection.runId !== event.runId) {
    throw new ResearchProjectionIdentityError('event runId does not match projection')
  }
}

function isTerminal(projection: UserResearchProjectionV1): boolean {
  return TERMINAL_STATUSES.has(projection.status) || projection.termination != null
}

function mergeSparse(existing: unknown, incoming: unknown): unknown {
  if (isObject(existing) && isObject(incoming)) {
    const result: UnknownObject = { ...existing }
    for (const [key, value] of Object.entries(incoming)) {
      if (key in result) {
        result[key] = mergeSparse(result[key], value)
      }
      else if (!EMPTY_VALUES.has(value) && !(Array.isArray(value) && value.length === 0)) {
        result[key] = value
      }
    }
    return result
  }
  if (EMPTY_VALUES.has(incoming) || (Array.isArray(incoming) && incoming.length === 0)) {
    return existing
  }
  return incoming
}

function payloadItems(payload: ResearchJsonValue, singular: string, plural: string): UnknownObject[] {
  const object = asObject(payload, `${singular} payload`)
  const collection = object[plural]
  if (collection !== undefined) {
    const items = asArray(collection)
    if (!items) {
      throw new ResearchProjectionError('invalid_payload', `payload.${plural} must be an array`)
    }
    return items.map((item, index) => asObject(item, `payload.${plural}[${index}]`))
  }
  for (const key of [singular, 'item', 'value']) {
    if (object[key] !== undefined) {
      return [asObject(object[key], `payload.${key}`)]
    }
  }
  return [object]
}

function entityId(item: UnknownObject, idKey: string, entity?: ResearchEntityRefV1 | null): string | undefined {
  return asString(item[idKey]) ?? entity?.entityId
}

function updateCollection<T extends { [key: string]: unknown }>(
  current: readonly T[],
  incoming: UnknownObject,
  idKey: string,
  mutation: ResearchEventV1['mutation'],
  entity?: ResearchEntityRefV1 | null,
): T[] {
  const id = entityId(incoming, idKey, entity)
  if (!id) {
    throw new ResearchProjectionError('invalid_payload', `${idKey} is required`)
  }
  const index = current.findIndex(item => item[idKey] === id)
  if (mutation === 'remove') {
    return index < 0 ? [...current] : current.filter((_, itemIndex) => itemIndex !== index)
  }
  if (index >= 0 && mutation === 'append') {
    return [...current]
  }
  const candidate = index < 0 || mutation === 'replace'
    ? { ...incoming, [idKey]: id }
    : { ...mergeSparse(current[index], incoming) as UnknownObject, [idKey]: id }
  if (index < 0) {
    return [...current, candidate as T]
  }
  return current.map((item, itemIndex) => itemIndex === index ? candidate as T : item)
}

function updateMetrics(projection: UserResearchProjectionV1): UserResearchProjectionV1['metrics'] {
  return {
    ...projection.metrics,
    evidenceItems: Math.max(projection.metrics.evidenceItems ?? 0, projection.evidence.length),
    commentEvidenceItems: Math.max(
      projection.metrics.commentEvidenceItems ?? 0,
      projection.evidence.filter(item => item.commentRef != null).length,
    ),
    profiles: Math.max(projection.metrics.profiles ?? 0, projection.profiles.length),
    controversies: Math.max(projection.metrics.controversies ?? 0, projection.controversies.length),
    gaps: Math.max(projection.metrics.gaps ?? 0, projection.gaps.length),
    actions: Math.max(projection.metrics.actions ?? 0, projection.plan.length),
  }
}

function withCursor(
  projection: UserResearchProjectionV1,
  event: ResearchEventV1,
  updates: Partial<UserResearchProjectionV1> = {},
): UserResearchProjectionV1 {
  const eventIds = [...(projection.appliedEventIds ?? []), event.eventId].slice(-MAX_APPLIED_EVENT_IDS)
  return parseUserResearchProjectionV1({
    ...projection,
    ...updates,
    schemaVersion: USER_RESEARCH_PROJECTION_SCHEMA_VERSION,
    lastSequence: event.sequence,
    revision: projection.revision + 1,
    updatedAt: event.occurredAt,
    appliedEventIds: eventIds,
    metrics: updateMetrics({ ...projection, ...updates }),
  })
}

function planItems(payload: ResearchJsonValue): UnknownObject[] {
  const object = asObject(payload, 'plan payload')
  const raw = object.steps ?? object.plan
  if (raw === undefined) return []
  const items = asArray(raw)
  if (!items) throw new ResearchProjectionError('invalid_payload', 'payload.steps must be an array')
  return items.map((item, index) => asObject(item, `payload.steps[${index}]`))
}

function applyPlan(projection: UserResearchProjectionV1, event: ResearchEventV1): UserResearchProjectionV1 {
  const steps = planItems(event.payload)
    .map((item) => ({
      ...item,
      stepId: asString(item.stepId) ?? asString(item.id),
      label: asString(item.label) ?? asString(item.actionName) ?? asString(item.stepId) ?? 'Research step',
    }))
    .filter((item): item is UnknownObject & { stepId: string, label: string } => Boolean(item.stepId))
  if (event.mutation === 'replace') {
    return { ...projection, plan: steps as unknown as ResearchPlanStepViewV1[] }
  }
  let current = [...projection.plan] as unknown as UnknownObject[]
  for (const step of steps) current = updateCollection(current, step, 'stepId', 'upsert')
  return { ...projection, plan: current as unknown as ResearchPlanStepViewV1[] }
}

function applyAction(projection: UserResearchProjectionV1, event: ResearchEventV1): UserResearchProjectionV1 {
  const object = asObject(event.payload, 'action payload')
  const rawStep = isObject(object.step) ? object.step : {}
  const stepId = asString(rawStep.stepId) ?? asString(object.stepId) ?? asString(object.actionId) ?? event.entity?.entityId
  if (!stepId) {
    return { ...projection, phase: event.phase ?? projection.phase, status: event.status ?? 'running' }
  }
  const statusByKind: Record<string, ResearchStepStatusV1> = {
    action_started: 'running',
    action_progress: 'running',
    action_completed: 'succeeded',
  }
  const step: UnknownObject = {
    ...rawStep,
    stepId,
    label: asString(rawStep.label) ?? asString(object.label) ?? asString(object.actionName) ?? stepId,
    status: asString(rawStep.status) ?? asString(object.stepStatus) ?? statusByKind[event.kind] ?? 'running',
    ...(event.phase ? { phase: event.phase } : {}),
  }
  const plan = updateCollection(
    projection.plan as unknown as UnknownObject[],
    step,
    'stepId',
    'upsert',
  ) as unknown as ResearchPlanStepViewV1[]
  return { ...projection, plan, phase: event.phase ?? projection.phase, status: event.status ?? 'running' }
}

function applyEntities(projection: UserResearchProjectionV1, event: ResearchEventV1): UserResearchProjectionV1 {
  if (event.kind === 'evidence_added') {
    if (event.mutation !== 'append') {
      throw new ResearchProjectionError('append_only', 'evidence_added is append-only')
    }
    let evidence = [...projection.evidence] as unknown as UnknownObject[]
    for (const item of payloadItems(event.payload, 'evidence', 'items')) {
      evidence = updateCollection(evidence, item, 'evidenceId', 'append', event.entity)
    }
    return { ...projection, evidence: evidence as unknown as ResearchEvidenceItemV1[] }
  }
  const definitions: Record<string, { singular: string, plural: string, idKey: string }> = {
    controversy_upserted: { singular: 'controversy', plural: 'controversies', idKey: 'controversyId' },
    profile_upserted: { singular: 'profile', plural: 'profiles', idKey: 'profileId' },
    recommendation_upserted: { singular: 'recommendation', plural: 'recommendations', idKey: 'recommendationId' },
    gap_upserted: { singular: 'gap', plural: 'gaps', idKey: 'gapId' },
  }
  const definition = definitions[event.kind]
  if (!definition) return projection
  const collectionName = definition.plural as 'controversies' | 'profiles' | 'recommendations' | 'gaps'
  let current = [...projection[collectionName]] as unknown as UnknownObject[]
  for (const item of payloadItems(event.payload, definition.singular, definition.plural)) {
    const mutation = event.mutation === 'append' ? 'upsert' : event.mutation
    current = updateCollection(current, item, definition.idKey, mutation, event.entity)
  }
  const updated = { ...projection, [collectionName]: current }
  if (collectionName !== 'gaps') return updated
  const gapRefs = current as unknown as ResearchGapViewV1[]
  const profiles = projection.profiles.map((profile) => {
    const refs = gapRefs.filter(gap => gap.affectedRefs?.some(ref => (
      ['profile', 'shop'].includes(ref.entityType)
      && (ref.entityId === profile.profileId || ref.entityId === profile.entityRef?.entityId)
    )))
    if (!refs.length) return profile
    return {
      ...profile,
      status: profile.status === 'pending' ? 'partial' : profile.status,
      gapRefs: [...new Set([...(profile.gapRefs ?? []), ...refs.map(gap => gap.gapId)])],
    }
  })
  return { ...updated, profiles }
}

function applyRunStarted(projection: UserResearchProjectionV1, event: ResearchEventV1): UserResearchProjectionV1 {
  const payload = asObject(event.payload, 'run_started payload')
  let next: UserResearchProjectionV1 = { ...projection, status: event.status ?? 'running', phase: event.phase ?? asString(payload.phase) ?? projection.phase, summary: asString(payload.summary) ?? projection.summary }
  if (isObject(payload.intent)) next = { ...next, intent: payload.intent as UserResearchProjectionV1['intent'] }
  if (payload.plan !== undefined || payload.steps !== undefined) next = applyPlan(next, event)
  return next
}

function applyProgress(projection: UserResearchProjectionV1, event: ResearchEventV1): UserResearchProjectionV1 {
  const payload = asObject(event.payload, 'run_progress payload')
  return {
    ...projection,
    status: event.status ?? 'running',
    phase: event.phase ?? asString(payload.phase) ?? projection.phase,
    summary: asString(payload.summary) ?? projection.summary,
    coverage: isObject(payload.coverage) ? payload.coverage as UserResearchProjectionV1['coverage'] : projection.coverage,
    metrics: isObject(payload.metrics) ? { ...projection.metrics, ...payload.metrics as UserResearchProjectionV1['metrics'] } : projection.metrics,
  }
}

function applyTerminal(projection: UserResearchProjectionV1, event: ResearchEventV1): UserResearchProjectionV1 {
  const payload = isObject(event.payload) ? event.payload : {}
  const status: ResearchRunStatusV1 = event.kind === 'run_completed'
    ? event.status === 'partial' || payload.status === 'partial' ? 'partial' : 'succeeded'
    : event.kind === 'run_cancelled' ? 'cancelled' : 'failed'
  const message = asString(payload.message) ?? asString(payload.summary) ?? ''
  const reason = asString(payload.reason) ?? asString(payload.code) ?? event.kind
  return {
    ...projection,
    status,
    phase: event.phase ?? projection.phase,
    summary: message || projection.summary,
    termination: {
      status,
      reason,
      message,
      resumable: payload.resumable === true,
      continuationRef: asString(payload.continuationRef) ?? null,
      completedAt: event.occurredAt,
    },
  }
}

function applyBody(projection: UserResearchProjectionV1, event: ResearchEventV1): UserResearchProjectionV1 {
  switch (event.kind) {
    case 'run_started': return applyRunStarted(projection, event)
    case 'plan_updated': return applyPlan(projection, event)
    case 'action_started':
    case 'action_progress':
    case 'action_completed': return applyAction(projection, event)
    case 'evidence_added':
    case 'controversy_upserted':
    case 'profile_upserted':
    case 'recommendation_upserted':
    case 'gap_upserted': return applyEntities(projection, event)
    case 'run_progress': return applyProgress(projection, event)
    case 'run_completed':
    case 'run_failed':
    case 'run_cancelled': return applyTerminal(projection, event)
    default: return projection
  }
}

export class ResearchProjectionReducer {
  apply(input: UserResearchProjectionV1, rawEvent: ResearchEventV1): UserResearchProjectionV1 {
    const event = parseResearchEventV1(rawEvent)
    checkIdentity(input, event)
    if (input.appliedEventIds?.includes(event.eventId)) return input
    if (event.sequence !== input.lastSequence + 1) {
      throw new ResearchProjectionSequenceError(input.lastSequence + 1, event.sequence, event.sequence > input.lastSequence ? 'sequence gap' : 'stale replay')
    }
    if (isTerminal(input)) throw new ResearchProjectionTerminalError(event.eventId)
    return withCursor(applyBody(input, event), event)
  }

  reduce(input: UserResearchProjectionV1, events: readonly ResearchEventV1[]): UserResearchProjectionV1 {
    return events.reduce((projection, event) => this.apply(projection, event), input)
  }
}

export const researchProjectionReducer = new ResearchProjectionReducer()

export function reduceResearchProjection(
  projection: UserResearchProjectionV1,
  event: ResearchEventV1,
): UserResearchProjectionV1 {
  return researchProjectionReducer.apply(projection, event)
}
