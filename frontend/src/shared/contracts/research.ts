import { z } from 'zod'

/** JSON values allowed at the public research experience boundary. */
export type ResearchJsonValue =
  | string
  | number
  | boolean
  | null
  | ResearchJsonValue[]
  | { [key: string]: ResearchJsonValue }

export const RESEARCH_EVENT_SCHEMA_VERSION = 'research-event/v1' as const
export const USER_RESEARCH_PROJECTION_SCHEMA_VERSION = 'user-research-projection/v1' as const
export const PUBLIC_EXPERIENCE_MAX_EVENT_BYTES = 128_000 as const

export const researchEventKinds = [
  'run_started',
  'plan_updated',
  'action_started',
  'action_progress',
  'action_completed',
  'evidence_added',
  'controversy_upserted',
  'profile_upserted',
  'recommendation_upserted',
  'gap_upserted',
  'run_progress',
  'run_completed',
  'run_failed',
  'run_cancelled',
] as const

export type ResearchEventKindV1 =
  | (typeof researchEventKinds)[number]
  | `x.${string}.${string}`
export type ResearchMutationV1 = 'append' | 'upsert' | 'patch' | 'replace' | 'remove'
export type ResearchRunStatusV1 =
  | 'queued'
  | 'running'
  | 'succeeded'
  | 'partial'
  | 'failed'
  | 'cancelled'
  | 'blocked'
export type EvidenceStanceV1 = 'positive' | 'negative' | 'neutral' | 'mixed'
export type ControversyStatusV1 = 'unresolved' | 'partially_resolved' | 'resolved'
export type ProfileStatusV1 = 'pending' | 'partial' | 'complete' | 'unavailable' | 'failed'
export type RecommendationStatusV1 = 'candidate' | 'partial' | 'recommended' | 'filtered'
export type GapSeverityV1 = 'info' | 'warning' | 'error'
export type GapStatusV1 = 'open' | 'retrying' | 'resolved' | 'exhausted'
export type ResearchStepStatusV1 =
  | 'pending'
  | 'running'
  | 'succeeded'
  | 'partial'
  | 'failed'
  | 'skipped'

export interface ResearchEntityRefV1 {
  entityType: string
  entityId: string
  version?: number | null
}

export interface ResearchProvenanceRefV1 {
  source: string
  sourceRef?: string | null
  sourceUrl?: string | null
  noteRef?: string | null
  commentRef?: string | null
  capturedAt?: string | null
}

export interface ResearchEvidenceItemV1 {
  evidenceId: string
  source: string
  excerpt?: string
  title?: string | null
  stance?: EvidenceStanceV1
  entityRefs?: ResearchEntityRefV1[]
  claimRefs?: string[]
  provenance?: ResearchProvenanceRefV1[]
  noteRef?: string | null
  commentRef?: string | null
  capturedAt?: string | null
  confidence?: number | null
  extensions?: Record<string, ResearchJsonValue>
}

export interface ResearchControversySideV1 {
  sideId: string
  label: string
  summary?: string
  evidenceRefs?: string[]
  claimRefs?: string[]
}

export interface ResearchControversyViewV1 {
  controversyId: string
  entityRef?: ResearchEntityRefV1 | null
  topic: string
  summary?: string
  status?: ControversyStatusV1
  sides?: ResearchControversySideV1[]
  evidenceRefs?: string[]
  resolution?: string | null
  remainingQuestion?: string | null
  confidence?: number | null
  updatedAt?: string | null
  extensions?: Record<string, ResearchJsonValue>
}

export interface ResearchProfileViewV1 {
  profileId: string
  entityRef?: ResearchEntityRefV1 | null
  providerRefs?: Record<string, string>
  name?: string | null
  alias?: string | null
  url?: string | null
  sourceUrl?: string | null
  imageUrl?: string | null
  status?: ProfileStatusV1
  address?: string | null
  city?: string | null
  district?: string | null
  region?: string | null
  businessArea?: string | null
  location?: string | null
  latitude?: number | null
  longitude?: number | null
  coordinateSystem?: string | null
  geo?: Record<string, ResearchJsonValue>
  phone?: string | null
  rating?: number | null
  reviewCount?: number | null
  averagePrice?: number | null
  priceBand?: string | null
  category?: string | null
  openingHours?: string | null
  images?: ResearchJsonValue[]
  recommendedDishes?: ResearchJsonValue[]
  promotions?: ResearchJsonValue[]
  tags?: string[]
  sourceRefs?: string[]
  gapRefs?: string[]
  attributes?: Record<string, ResearchJsonValue>
  reviewCompleteness?: Record<string, ResearchJsonValue>
  profileOutcome?: string | null
  domainData?: Record<string, ResearchJsonValue>
  extensions?: Record<string, ResearchJsonValue>
  updatedAt?: string | null
}

export interface ResearchRecommendationViewV1 {
  recommendationId: string
  entityRef?: ResearchEntityRefV1 | null
  title: string
  summary?: string
  status?: RecommendationStatusV1
  rank?: number | null
  confidence?: number | null
  evidenceRefs?: string[]
  controversyRefs?: string[]
  profileRef?: string | null
  highlights?: string[]
  warnings?: string[]
  domainData?: Record<string, ResearchJsonValue>
  extensions?: Record<string, ResearchJsonValue>
  updatedAt?: string | null
}

export interface ResearchGapViewV1 {
  gapId: string
  source: string
  operation: string
  code: string
  message: string
  retryable?: boolean
  severity?: GapSeverityV1
  status?: GapStatusV1
  affectedRefs?: ResearchEntityRefV1[]
  continuationRef?: string | null
  occurredAt?: string | null
  extensions?: Record<string, ResearchJsonValue>
}

export interface ResearchPlanStepViewV1 {
  stepId: string
  label: string
  phase?: string
  status?: ResearchStepStatusV1
  actionName?: string | null
  detail?: string
  counts?: Record<string, number>
  startedAt?: string | null
  completedAt?: string | null
}

export interface ResearchIntentViewV1 {
  objective?: string
  location?: string | null
  constraints?: string[]
  exclusions?: string[]
  extensions?: Record<string, ResearchJsonValue>
}

export interface ResearchCoverageDimensionV1 {
  dimension: string
  observed?: number | null
  expected?: number | null
  ratio?: number | null
  status?: 'unknown' | 'partial' | 'sufficient'
}

export interface ResearchCoverageViewV1 {
  dimensions?: ResearchCoverageDimensionV1[]
  unresolvedControversies?: number
  candidateEntityCount?: number
  missing?: string[]
}

export interface ResearchMetricsV1 {
  rounds?: number
  actions?: number
  evidenceItems?: number
  commentEvidenceItems?: number
  profiles?: number
  controversies?: number
  gaps?: number
}

export interface ResearchTerminationViewV1 {
  status: ResearchRunStatusV1
  reason: string
  message?: string
  resumable?: boolean
  continuationRef?: string | null
  completedAt?: string | null
}

/** The public ResearchEvent v1 envelope; transport cursors are separate. */
export interface ResearchEventV1 {
  schemaVersion: typeof RESEARCH_EVENT_SCHEMA_VERSION
  eventId: string
  sessionId: string
  taskId: string
  turnId: number
  runId?: string | null
  sequence: number
  occurredAt: string
  kind: ResearchEventKindV1
  phase?: string | null
  status?: ResearchRunStatusV1 | null
  mutation?: ResearchMutationV1
  entity?: ResearchEntityRefV1 | null
  payload: ResearchJsonValue
  extensions?: Record<string, ResearchJsonValue>
}

/** Complete public snapshot obtained by reducing ResearchEvent v1 deltas. */
export interface UserResearchProjectionV1 {
  schemaVersion: typeof USER_RESEARCH_PROJECTION_SCHEMA_VERSION
  sessionId: string
  taskId: string
  turnId: number
  runId?: string | null
  revision: number
  lastSequence: number
  status: ResearchRunStatusV1
  phase?: string
  summary?: string
  intent?: ResearchIntentViewV1 | null
  plan: ResearchPlanStepViewV1[]
  evidence: ResearchEvidenceItemV1[]
  controversies: ResearchControversyViewV1[]
  profiles: ResearchProfileViewV1[]
  recommendations: ResearchRecommendationViewV1[]
  gaps: ResearchGapViewV1[]
  coverage?: ResearchCoverageViewV1 | null
  metrics: ResearchMetricsV1
  termination?: ResearchTerminationViewV1 | null
  updatedAt: string
  extensions?: Record<string, ResearchJsonValue>
  appliedEventIds?: string[]
}

const forbiddenKey = /(prompt|scratch|chainofthought|hiddenreasoning|raw|cookie|credential|authorization|accesstoken|apikey|arguments|callargs|password|privatekey|refreshtoken|secret|mcparg|toolargs|toolinput|requestheaders|providerresponse|providerpayload)/i
const forbiddenQueryKey = /^(access_token|api_key|apikey|authorization|credential|password|secret|sig|signature|token)$/i

function assertPublicJson(value: unknown, path = '$', depth = 0): void {
  if (depth > 8) throw new Error(`public payload nesting exceeds the v1 limit at ${path}`)
  if (typeof value === 'string') {
    if (value.length > 4096) throw new Error(`public text exceeds the v1 limit at ${path}`)
    if (value.includes('://')) {
      try {
        const query = new URL(value).searchParams
        for (const key of query.keys()) {
          if (forbiddenQueryKey.test(key)) throw new Error(`credential-bearing URL at ${path}`)
        }
      } catch (error) {
        if (error instanceof Error && error.message.includes('credential-bearing')) throw error
      }
    }
    return
  }
  if (value === null || typeof value === 'boolean' || typeof value === 'number') return
  if (Array.isArray(value)) {
    if (value.length > 256) throw new Error(`public array has too many items at ${path}`)
    value.forEach((item, index) => assertPublicJson(item, `${path}[${index}]`, depth + 1))
    return
  }
  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>)
    if (entries.length > 256) throw new Error(`public object has too many fields at ${path}`)
    for (const [key, item] of entries) {
      if (forbiddenKey.test(key)) throw new Error(`forbidden private field ${key} at ${path}`)
      assertPublicJson(item, `${path}.${key}`, depth + 1)
    }
    return
  }
  throw new Error(`unsupported public value at ${path}`)
}

const jsonValue = z.unknown().superRefine((value, ctx) => {
  try {
    assertPublicJson(value)
  } catch (error) {
    ctx.addIssue({ code: z.ZodIssueCode.custom, message: String(error) })
  }
})
const jsonRecord = z.record(z.string(), jsonValue)
const id = z.string().min(1).max(256)
const timestamp = z.string().datetime({ offset: true })
const entityRef = z.object({ entityType: id, entityId: id, version: z.number().int().positive().nullable().optional() }).strict()
const provenance = z.object({
  source: id,
  sourceRef: id.nullable().optional(),
  sourceUrl: z.string().max(4096).nullable().optional(),
  noteRef: id.nullable().optional(),
  commentRef: id.nullable().optional(),
  capturedAt: timestamp.nullable().optional(),
}).strict()
const evidence = z.object({
  evidenceId: id,
  source: id,
  excerpt: z.string().max(2000).optional(),
  title: z.string().max(4096).nullable().optional(),
  stance: z.enum(['positive', 'negative', 'neutral', 'mixed']).optional(),
  entityRefs: z.array(entityRef).max(256).optional(),
  claimRefs: z.array(id).max(256).optional(),
  provenance: z.array(provenance).max(256).optional(),
  noteRef: id.nullable().optional(),
  commentRef: id.nullable().optional(),
  capturedAt: timestamp.nullable().optional(),
  confidence: z.number().min(0).max(1).nullable().optional(),
  extensions: jsonRecord.optional(),
}).strict()
const controversySide = z.object({
  sideId: id,
  label: z.string().min(1).max(512),
  summary: z.string().max(4096).optional(),
  evidenceRefs: z.array(id).max(256).optional(),
  claimRefs: z.array(id).max(256).optional(),
}).strict()
const controversy = z.object({
  controversyId: id,
  entityRef: entityRef.nullable().optional(),
  topic: z.string().min(1).max(512),
  summary: z.string().max(4096).optional(),
  status: z.enum(['unresolved', 'partially_resolved', 'resolved']).optional(),
  sides: z.array(controversySide).max(256).optional(),
  evidenceRefs: z.array(id).max(256).optional(),
  resolution: z.string().max(4096).nullable().optional(),
  remainingQuestion: z.string().max(4096).nullable().optional(),
  confidence: z.number().min(0).max(1).nullable().optional(),
  updatedAt: timestamp.nullable().optional(),
  extensions: jsonRecord.optional(),
}).strict()
const profile = z.object({
  profileId: id,
  entityRef: entityRef.nullable().optional(),
  providerRefs: z.record(z.string(), id).optional(),
  name: z.string().max(4096).nullable().optional(),
  alias: z.string().max(4096).nullable().optional(),
  url: z.string().max(4096).nullable().optional(),
  sourceUrl: z.string().max(4096).nullable().optional(),
  imageUrl: z.string().max(4096).nullable().optional(),
  status: z.enum(['pending', 'partial', 'complete', 'unavailable', 'failed']).optional(),
  address: z.string().max(4096).nullable().optional(),
  city: z.string().max(4096).nullable().optional(),
  district: z.string().max(4096).nullable().optional(),
  region: z.string().max(4096).nullable().optional(),
  businessArea: z.string().max(4096).nullable().optional(),
  location: z.string().max(4096).nullable().optional(),
  latitude: z.number().min(-90).max(90).nullable().optional(),
  longitude: z.number().min(-180).max(180).nullable().optional(),
  coordinateSystem: z.string().max(256).nullable().optional(),
  geo: jsonRecord.optional(),
  phone: z.string().max(4096).nullable().optional(),
  rating: z.number().min(0).max(10).nullable().optional(),
  reviewCount: z.number().int().nonnegative().nullable().optional(),
  averagePrice: z.number().nonnegative().nullable().optional(),
  category: z.string().max(4096).nullable().optional(),
  openingHours: z.string().max(4096).nullable().optional(),
  images: z.array(jsonValue).max(256).optional(),
  recommendedDishes: z.array(jsonValue).max(256).optional(),
  promotions: z.array(jsonValue).max(256).optional(),
  tags: z.array(z.string().max(4096)).max(256).optional(),
  sourceRefs: z.array(id).max(256).optional(),
  gapRefs: z.array(id).max(256).optional(),
  attributes: jsonRecord.optional(),
  reviewCompleteness: jsonRecord.optional(),
  profileOutcome: z.string().max(4096).nullable().optional(),
  domainData: jsonRecord.optional(),
  extensions: jsonRecord.optional(),
  updatedAt: timestamp.nullable().optional(),
}).strict()
const recommendation = z.object({
  recommendationId: id,
  entityRef: entityRef.nullable().optional(),
  title: z.string().min(1).max(4096),
  summary: z.string().max(4096).optional(),
  status: z.enum(['candidate', 'partial', 'recommended', 'filtered']).optional(),
  rank: z.number().int().positive().nullable().optional(),
  confidence: z.number().min(0).max(1).nullable().optional(),
  evidenceRefs: z.array(id).max(256).optional(),
  controversyRefs: z.array(id).max(256).optional(),
  profileRef: id.nullable().optional(),
  highlights: z.array(z.string().max(4096)).max(256).optional(),
  warnings: z.array(z.string().max(4096)).max(256).optional(),
  domainData: jsonRecord.optional(),
  extensions: jsonRecord.optional(),
  updatedAt: timestamp.nullable().optional(),
}).strict()
const gap = z.object({
  gapId: id,
  source: id,
  operation: z.string().min(1).max(4096),
  code: id,
  message: z.string().min(1).max(4096),
  retryable: z.boolean().optional(),
  severity: z.enum(['info', 'warning', 'error']).optional(),
  status: z.enum(['open', 'retrying', 'resolved', 'exhausted']).optional(),
  affectedRefs: z.array(entityRef).max(256).optional(),
  continuationRef: id.nullable().optional(),
  occurredAt: timestamp.nullable().optional(),
  extensions: jsonRecord.optional(),
}).strict()
const planStep = z.object({
  stepId: id,
  label: z.string().min(1).max(512),
  phase: z.string().max(4096).optional(),
  status: z.enum(['pending', 'running', 'succeeded', 'partial', 'failed', 'skipped']).optional(),
  actionName: z.string().max(4096).nullable().optional(),
  detail: z.string().max(4096).optional(),
  counts: z.record(z.string(), z.number().int().nonnegative()).optional(),
  startedAt: timestamp.nullable().optional(),
  completedAt: timestamp.nullable().optional(),
}).strict()
const intent = z.object({
  objective: z.string().max(4096).optional(),
  location: z.string().max(4096).nullable().optional(),
  constraints: z.array(z.string().max(4096)).max(256).optional(),
  exclusions: z.array(z.string().max(4096)).max(256).optional(),
  extensions: jsonRecord.optional(),
}).strict()
const coverage = z.object({
  dimensions: z.array(z.object({
    dimension: id,
    observed: z.number().int().nonnegative().nullable().optional(),
    expected: z.number().int().nonnegative().nullable().optional(),
    ratio: z.number().min(0).max(1).nullable().optional(),
    status: z.enum(['unknown', 'partial', 'sufficient']).optional(),
  }).strict()).max(256).optional(),
  unresolvedControversies: z.number().int().nonnegative().optional(),
  candidateEntityCount: z.number().int().nonnegative().optional(),
  missing: z.array(z.string().max(4096)).max(256).optional(),
}).strict()
const metrics = z.object({
  rounds: z.number().int().nonnegative().optional(),
  actions: z.number().int().nonnegative().optional(),
  evidenceItems: z.number().int().nonnegative().optional(),
  commentEvidenceItems: z.number().int().nonnegative().optional(),
  profiles: z.number().int().nonnegative().optional(),
  controversies: z.number().int().nonnegative().optional(),
  gaps: z.number().int().nonnegative().optional(),
}).strict()
const termination = z.object({
  status: z.enum(['queued', 'running', 'succeeded', 'partial', 'failed', 'cancelled', 'blocked']),
  reason: id,
  message: z.string().max(4096).optional(),
  resumable: z.boolean().optional(),
  continuationRef: id.nullable().optional(),
  completedAt: timestamp.nullable().optional(),
}).strict()

export const researchEventV1Schema = z.object({
  schemaVersion: z.literal(RESEARCH_EVENT_SCHEMA_VERSION),
  eventId: id,
  sessionId: id,
  taskId: id,
  turnId: z.number().int().positive(),
  runId: id.nullable().optional(),
  sequence: z.number().int().positive(),
  occurredAt: timestamp,
  kind: z.union([
    z.enum(researchEventKinds),
    z.string().regex(/^x\.[a-z][a-z0-9_-]{0,63}\.[a-z][a-z0-9_.-]{0,127}$/),
  ]),
  phase: z.string().max(4096).nullable().optional(),
  status: z.enum(['queued', 'running', 'succeeded', 'partial', 'failed', 'cancelled', 'blocked']).nullable().optional(),
  mutation: z.enum(['append', 'upsert', 'patch', 'replace', 'remove']).optional(),
  entity: entityRef.nullable().optional(),
  payload: jsonValue,
  extensions: jsonRecord.optional(),
}).strict()

export const userResearchProjectionV1Schema = z.object({
  schemaVersion: z.literal(USER_RESEARCH_PROJECTION_SCHEMA_VERSION),
  sessionId: id,
  taskId: id,
  turnId: z.number().int().positive(),
  runId: id.nullable().optional(),
  revision: z.number().int().nonnegative(),
  lastSequence: z.number().int().nonnegative(),
  status: z.enum(['queued', 'running', 'succeeded', 'partial', 'failed', 'cancelled', 'blocked']),
  phase: z.string().max(4096).optional(),
  summary: z.string().max(4096).optional(),
  intent: intent.nullable().optional(),
  plan: z.array(planStep).max(256),
  evidence: z.array(evidence).max(256),
  controversies: z.array(controversy).max(256),
  profiles: z.array(profile).max(256),
  recommendations: z.array(recommendation).max(256),
  gaps: z.array(gap).max(256),
  coverage: coverage.nullable().optional(),
  metrics,
  termination: termination.nullable().optional(),
  updatedAt: timestamp,
  extensions: jsonRecord.optional(),
  appliedEventIds: z.array(id).max(2048).optional(),
}).strict()

export function parseResearchEventV1(value: unknown): ResearchEventV1 {
  const parsed = researchEventV1Schema.parse(value) as ResearchEventV1
  if (new TextEncoder().encode(JSON.stringify(parsed)).byteLength > PUBLIC_EXPERIENCE_MAX_EVENT_BYTES) {
    throw new Error('ResearchEvent v1 exceeds the maximum wire size')
  }
  return parsed
}

export function parseUserResearchProjectionV1(value: unknown): UserResearchProjectionV1 {
  return userResearchProjectionV1Schema.parse(value) as UserResearchProjectionV1
}
