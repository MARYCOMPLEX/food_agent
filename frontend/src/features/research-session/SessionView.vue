<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AdaptiveContainer from '../../shared/ui/AdaptiveContainer.vue'
import type {
  ResearchEventV1,
  ResearchGapViewV1,
  ResearchJsonValue,
  ResearchProfileViewV1,
  ResearchRecommendationViewV1,
  ResearchRunStatusV1,
  ResearchStepStatusV1,
  UserResearchProjectionV1,
} from '../../shared/contracts/research'
import {
  RESEARCH_EVENT_SCHEMA_VERSION,
  parseUserResearchProjectionV1,
} from '../../shared/contracts/research'
import SessionHeader from './components/SessionHeader.vue'
import ReactAssistantIslandHost from './components/ReactAssistantIslandHost.vue'
import { ResearchSurface } from './components/research-surface'
import { sessionApi } from './api/sessionApi'
import {
  createInitialResearchProjection,
  useResearchSession,
} from './domain'
import { createAssistantExternalStore, projectResearchProjection } from '../assistant-runtime'
import type { AssistantDomainMessage } from '../assistant-runtime/types'

const route = useRoute()
const router = useRouter()
const sessionId = ref(String(route.params.sessionId ?? ''))
const followUpLoading = ref(false)
const bootstrapError = ref<string | null>(null)

const research = useResearchSession(sessionId.value, {
  // The deployed API currently exposes the stable legacy stream. The domain
  // adapter also accepts ResearchEvent v1 frames when the backend is upgraded.
  sseVersion: 'legacy',
  autoReconnect: true,
})
const assistantStore = createAssistantExternalStore()

const projection = research.projection
const researchState = research.state
const transportState = research.transportState

const connectionState = computed(() => {
  switch (transportState.value) {
    case 'connected': return 'connected'
    case 'reconnecting': return 'reconnecting'
    case 'connecting': return 'connecting'
    case 'completed': return 'completed'
    case 'error': return 'error'
    default: return 'disconnected'
  }
})

const terminalStatuses = new Set<ResearchRunStatusV1>(['succeeded', 'partial', 'failed', 'cancelled', 'blocked'])
const isComplete = computed(() => Boolean(projection.value && terminalStatuses.has(projection.value.status)))
const isLoading = computed(() => !isComplete.value && (
  projection.value?.status === 'queued'
  || projection.value?.status === 'running'
  || transportState.value === 'connecting'
  || transportState.value === 'connected'
  || transportState.value === 'reconnecting'
))
const errorMessage = computed(() => researchState.value.lastError?.message ?? bootstrapError.value)

function safeString(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined
}

function safeNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function asPublicJson(value: unknown): ResearchJsonValue {
  if (value === null || typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return value
  if (Array.isArray(value)) return value.map(asPublicJson)
  if (typeof value === 'object') {
    return Object.fromEntries(Object.entries(value as Record<string, unknown>).flatMap(([key, item]) => (
      item === undefined ? [] : [[key, asPublicJson(item)]]
    )))
  }
  return null
}

function statusForLegacyStep(value: unknown): ResearchStepStatusV1 {
  if (value === 'loading' || value === 'running') return 'running'
  if (value === 'done' || value === 'succeeded' || value === 'complete') return 'succeeded'
  if (value === 'error' || value === 'failed') return 'failed'
  return 'pending'
}

function eventForBootstrap(
  base: UserResearchProjectionV1,
  sequence: number,
  kind: ResearchEventV1['kind'],
  payload: ResearchJsonValue,
  status?: ResearchRunStatusV1,
  mutation: ResearchEventV1['mutation'] = 'upsert',
): ResearchEventV1 {
  return {
    schemaVersion: RESEARCH_EVENT_SCHEMA_VERSION,
    eventId: `bootstrap-${base.sessionId}-${sequence}-${kind}`,
    sessionId: base.sessionId,
    taskId: base.taskId,
    turnId: base.turnId,
    runId: base.runId ?? null,
    sequence,
    occurredAt: new Date().toISOString(),
    kind,
    status: status ?? null,
    mutation,
    payload,
  }
}

function profileFromRestaurant(restaurant: Record<string, unknown>, profileId: string): ResearchProfileViewV1 | null {
  const raw = restaurant.shopProfile
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null
  const profile = raw as Record<string, unknown>
  const strings = (value: unknown): string[] => Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
    : []
  const publicItems = (value: unknown): ResearchJsonValue[] => Array.isArray(value)
    ? value.map(asPublicJson)
    : []
  const images = publicItems(profile.images)
  const dishes = publicItems(profile.recommendedDishes)
  return {
    profileId,
    entityRef: { entityType: 'shop', entityId: profileId },
    providerRefs: typeof profile.providerRefs === 'object' && profile.providerRefs !== null && !Array.isArray(profile.providerRefs)
      ? Object.fromEntries(Object.entries(profile.providerRefs as Record<string, unknown>).flatMap(([key, value]) => {
          const ref = safeString(value)
          return ref ? [[key, ref]] : []
        }))
      : undefined,
    name: safeString(profile.name) ?? safeString(restaurant.name) ?? null,
    alias: safeString(profile.alias) ?? null,
    url: safeString(profile.url) ?? null,
    sourceUrl: safeString(profile.sourceUrl) ?? null,
    imageUrl: safeString(profile.imageUrl) ?? null,
    status: profile.profileOutcome === 'failed' ? 'failed' : profile.profileOutcome === 'partial' ? 'partial' : 'complete',
    address: safeString(profile.address) ?? safeString(profile.location) ?? null,
    city: safeString(profile.city) ?? null,
    district: safeString(profile.district) ?? null,
    region: safeString(profile.region) ?? null,
    businessArea: safeString(profile.businessArea) ?? null,
    location: safeString(profile.location) ?? null,
    latitude: safeNumber(profile.latitude) ?? null,
    longitude: safeNumber(profile.longitude) ?? null,
    coordinateSystem: safeString(profile.coordinateSystem) ?? null,
    phone: safeString(profile.phone) ?? null,
    rating: safeNumber(profile.rating) ?? null,
    reviewCount: safeNumber(profile.reviewCount) ?? null,
    averagePrice: safeNumber(profile.averagePrice) ?? null,
    category: safeString(profile.category) ?? null,
    openingHours: safeString(profile.openingHours) ?? null,
    images,
    recommendedDishes: dishes,
    promotions: Array.isArray(profile.promotions) ? profile.promotions.map(asPublicJson) : [],
    tags: strings(profile.tags),
    sourceRefs: Object.values(profile.providerRefs ?? {}).flatMap(value => {
      const ref = safeString(value)
      return ref ? [ref] : []
    }),
    attributes: typeof profile.attributes === 'object' && profile.attributes !== null && !Array.isArray(profile.attributes)
      ? asPublicJson(profile.attributes) as Record<string, ResearchJsonValue>
      : undefined,
    reviewCompleteness: typeof profile.reviewCompleteness === 'object' && profile.reviewCompleteness !== null && !Array.isArray(profile.reviewCompleteness)
      ? asPublicJson(profile.reviewCompleteness) as Record<string, ResearchJsonValue>
      : undefined,
    profileOutcome: safeString(profile.profileOutcome) ?? null,
    domainData: asPublicJson({
      profileGaps: profile.profileGaps,
    }) as Record<string, ResearchJsonValue>,
  }
}

function gapFromLegacy(raw: unknown, index: number): ResearchGapViewV1 | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null
  const value = raw as Record<string, unknown>
  const message = safeString(value.message) ?? safeString(value.detail)
  if (!message) return null
  return {
    gapId: safeString(value.gapId) ?? safeString(value.code) ?? `bootstrap-gap-${index + 1}`,
    source: safeString(value.source) ?? 'research',
    operation: safeString(value.operation) ?? 'enrichment',
    code: safeString(value.code) ?? 'partial_data',
    message,
    retryable: value.retryable === true,
    severity: value.severity === 'error' ? 'error' : value.severity === 'warning' ? 'warning' : 'info',
    status: value.status === 'resolved' ? 'resolved' : value.retryable === true ? 'open' : 'exhausted',
    occurredAt: new Date().toISOString(),
  }
}

async function loadExistingState(): Promise<void> {
  bootstrapError.value = null
  const [statusResult, resultsResult] = await Promise.allSettled([
    sessionApi.getStatus(sessionId.value),
    sessionApi.getResults(sessionId.value),
  ])
  const statusData = statusResult.status === 'fulfilled' ? statusResult.value : null
  const resultsData = resultsResult.status === 'fulfilled' ? resultsResult.value : null
  if (!statusData && !resultsData) {
    bootstrapError.value = '暂时无法读取会话快照，仍会继续尝试连接实时研究流。'
  }

  const candidateProjection = (statusData as unknown as Record<string, unknown> | null)?.projection
    ?? (resultsData as unknown as Record<string, unknown> | null)?.projection
  if (candidateProjection) {
    try {
      research.initializeSnapshot(parseUserResearchProjectionV1(candidateProjection))
      return
    }
    catch {
      // Fall through to the explicit legacy response adapter below.
    }
  }

  const statusRecord = (statusData ?? {}) as unknown as Record<string, unknown>
  const resultRecord = (resultsData ?? {}) as unknown as Record<string, unknown>
  const taskId = safeString(statusRecord.taskId) ?? safeString(resultRecord.taskId) ?? `legacy-task-${sessionId.value}`
  const turnId = Math.max(1, Math.floor(safeNumber(resultRecord.turnId) ?? safeNumber(statusRecord.turnId) ?? 1))
  const base = createInitialResearchProjection(sessionId.value, taskId, turnId)
  research.initializeSnapshot(base)
  let sequence = 1

  const steps = Array.isArray(statusRecord.steps)
    ? statusRecord.steps.map((raw, index) => {
        const step = (raw ?? {}) as Record<string, unknown>
        return {
          stepId: safeString(step.id) ?? `step-${index + 1}`,
          label: safeString(step.label) ?? safeString(step.id) ?? `调查步骤 ${index + 1}`,
          status: statusForLegacyStep(step.status),
          detail: safeString(step.detail),
        }
      })
    : []
  if (steps.length) {
    research.appendEvent(eventForBootstrap(base, sequence++, 'plan_updated', asPublicJson({ steps }), undefined, 'replace'))
  }

  const recommendations = Array.isArray(resultRecord.recommendations) ? resultRecord.recommendations : []
  for (const [index, raw] of recommendations.entries()) {
    const restaurant = (raw ?? {}) as Record<string, unknown>
    const id = safeString(restaurant.id) ?? `legacy-shop-${index + 1}`
    const profileId = `profile-${id}`
    const profile = profileFromRestaurant(restaurant, profileId)
    if (profile) {
      research.appendEvent(eventForBootstrap(base, sequence++, 'profile_upserted', asPublicJson({ profile }), undefined, 'upsert'))
    }
    const pros = Array.isArray(restaurant.pros) ? restaurant.pros.filter((item): item is string => typeof item === 'string') : []
    const cons = Array.isArray(restaurant.cons) ? restaurant.cons.filter((item): item is string => typeof item === 'string') : []
    const evidenceRefs = Array.isArray(restaurant.evidenceRefs) ? restaurant.evidenceRefs.filter((item): item is string => typeof item === 'string') : []
    const recommendation: ResearchRecommendationViewV1 = {
      recommendationId: id,
      entityRef: { entityType: 'shop', entityId: id },
      title: safeString(restaurant.name) ?? id,
      summary: safeString(restaurant.oneLiner) ?? safeString(restaurant.location) ?? '',
      status: restaurant.is_recommended === false ? 'filtered' : 'recommended',
      rank: index + 1,
      confidence: safeNumber(restaurant.confidence) ?? (safeNumber(restaurant.trustScore) !== undefined ? Math.max(0, Math.min(1, Number(restaurant.trustScore) / 100)) : null),
      evidenceRefs,
      profileRef: profile ? profileId : null,
      highlights: pros,
      warnings: cons.concat(safeString(restaurant.warning) ? [safeString(restaurant.warning)!] : []),
      domainData: {
        chnName: asPublicJson(restaurant.chnName),
        distance: asPublicJson(restaurant.distance),
        price: asPublicJson(restaurant.price),
        trustScore: asPublicJson(restaurant.trustScore),
        isNegativeOneLiner: asPublicJson(restaurant.isNegativeOneLiner),
        tags: asPublicJson(restaurant.tags ?? []),
        coverImage: asPublicJson(restaurant.coverImage),
        address: asPublicJson(restaurant.address),
        phone: asPublicJson(restaurant.phone),
        hours: asPublicJson(restaurant.hours),
        rating: asPublicJson(restaurant.rating),
        authenticity: asPublicJson(restaurant.authenticity),
        sourceNotesCount: asPublicJson(restaurant.sourceNotesCount),
        sourceCommentsCount: asPublicJson(restaurant.sourceCommentsCount),
        updatedAt: asPublicJson(restaurant.updatedAt),
        features: asPublicJson(restaurant.features ?? []),
        mustTry: asPublicJson(restaurant.mustTry ?? []),
        blackList: asPublicJson(restaurant.blackList ?? []),
        stats: asPublicJson(restaurant.stats ?? {}),
        evidenceSummary: asPublicJson(restaurant.evidenceSummary ?? {}),
      },
    }
    research.appendEvent(eventForBootstrap(base, sequence++, 'recommendation_upserted', asPublicJson({ recommendation }), undefined, 'upsert'))

    const sourceGaps = Array.isArray(restaurant.sourceGaps) ? restaurant.sourceGaps : []
    for (const [gapIndex, rawGap] of sourceGaps.entries()) {
      const gap = gapFromLegacy(rawGap, gapIndex)
      if (gap) {
        research.appendEvent(eventForBootstrap(base, sequence++, 'gap_upserted', asPublicJson({ gap }), undefined, 'upsert'))
      }
    }
  }

  const summary = safeString(resultRecord.summary)
  if (summary) {
    research.appendEvent(eventForBootstrap(base, sequence++, 'run_progress', { summary }, 'running', 'patch'))
  }

  const rawStatus = safeString(resultRecord.status) ?? safeString(statusRecord.status)
  if (rawStatus && ['completed', 'done', 'succeeded', 'partial', 'failed', 'error', 'cancelled'].includes(rawStatus)) {
    const terminalStatus: ResearchRunStatusV1 = rawStatus === 'partial'
      ? 'partial'
      : ['failed', 'error'].includes(rawStatus)
        ? 'failed'
        : rawStatus === 'cancelled' ? 'cancelled' : 'succeeded'
    const terminalKind: ResearchEventV1['kind'] = terminalStatus === 'cancelled' ? 'run_cancelled' : terminalStatus === 'failed' ? 'run_failed' : 'run_completed'
    research.appendEvent(eventForBootstrap(base, sequence, terminalKind, {
      message: summary ?? (terminalStatus === 'succeeded' ? '研究快照已加载' : '研究快照包含未完成项'),
      reason: rawStatus,
    }, terminalStatus, 'patch'))
  }
}

function syncAssistantProjection(nextProjection: UserResearchProjectionV1 | null): void {
  if (!nextProjection) return
  const previousUsers = assistantStore.getSnapshot().messages.filter(message => message.role === 'user')
  const next = projectResearchProjection(nextProjection, { includeEmptyCollections: true })
  assistantStore.replace({ ...next, messages: [...previousUsers, ...next.messages] })
}

async function submitFollowUp(message: AssistantDomainMessage): Promise<void> {
  const query = message.parts
    .filter((part): part is Extract<AssistantDomainMessage['parts'][number], { kind: 'text' }> => part.kind === 'text')
    .map(part => part.text)
    .join(' ')
    .trim()
  if (!query) return
  followUpLoading.value = true
  try {
    await sessionApi.refineQuery(sessionId.value, query)
    research.start()
  }
  catch (error) {
    bootstrapError.value = error instanceof Error ? error.message : '追问未能提交'
  }
  finally {
    followUpLoading.value = false
  }
}

async function retryGap(_gap: ResearchGapViewV1): Promise<void> {
  try {
    await sessionApi.recoverSession(sessionId.value)
    research.start()
  }
  catch (error) {
    bootstrapError.value = error instanceof Error ? error.message : '重试未能提交'
  }
}

function cancelResearch(): Promise<void> {
  research.stop()
  return Promise.resolve()
}

function goBack(): void {
  router.push('/app/explore')
}

watch(projection, syncAssistantProjection, { deep: true })

watch(
  () => route.params.sessionId,
  async (value) => {
    if (typeof value !== 'string' || value === sessionId.value) return
    sessionId.value = value
    research.reset()
    await loadExistingState()
    research.start()
  },
)

onMounted(async () => {
  await loadExistingState()
  research.start()
})
</script>

<template>
  <AdaptiveContainer max-width="xl" class="research-session-page space-y-5 pb-12">
    <SessionHeader
      :session-id="sessionId"
      :connection-state="connectionState"
      :is-complete="isComplete"
      @reconnect="research.start"
      @recover="research.start"
    />

    <div class="research-session-intro">
      <button type="button" class="research-session-back" @click="goBack">← 返回探索</button>
      <span class="research-session-caption">增量研究工作台</span>
    </div>

    <ReactAssistantIslandHost
      :store="assistantStore"
      :on-new="submitFollowUp"
      :on-cancel="cancelResearch"
    />

    <ResearchSurface
      :projection="projection"
      :loading="isLoading || followUpLoading"
      :error="errorMessage"
      @retry="research.start"
      @retry-gap="retryGap"
    />
  </AdaptiveContainer>
</template>

<style scoped>
.research-session-intro {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: var(--color-text-tertiary);
  font-size: 11px;
}

.research-session-back {
  border: 0;
  background: transparent;
  color: var(--color-brand-700);
  cursor: pointer;
  font-size: 12px;
  font-weight: 700;
  padding: 0;
}

.research-session-caption {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  letter-spacing: .08em;
  text-transform: uppercase;
}
</style>
