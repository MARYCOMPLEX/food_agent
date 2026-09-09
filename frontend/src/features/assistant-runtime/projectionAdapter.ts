import type {
  ResearchJsonValue,
  UserResearchProjectionV1,
} from '../../shared/contracts/research'
import type {
  AssistantDomainMessage,
  AssistantMessagePart,
  AssistantStoreSnapshot,
  AssistantUiBlock,
  ResearchProjectionAdapterOptions,
  ResearchProjectionInput,
} from './types'

function asJson(value: unknown): ResearchJsonValue {
  return value as ResearchJsonValue
}

function isTerminal(status: UserResearchProjectionV1['status']): boolean {
  return ['succeeded', 'partial', 'failed', 'cancelled', 'blocked'].includes(status)
}

function makeBlock(
  projection: ResearchProjectionInput,
  renderer: string,
  data: Record<string, unknown>,
  index: number,
): AssistantUiBlock {
  return {
    id: `research-${projection.runId ?? projection.sessionId}-${renderer}-${index}`,
    renderer,
    schemaVersion: 1,
    revision: projection.lastSequence,
    status: 'ready',
    data: asJson(data),
  }
}

function collectionBlock(
  blocks: Record<string, AssistantUiBlock>,
  parts: AssistantMessagePart[],
  projection: ResearchProjectionInput,
  renderer: string,
  title: string,
  items: unknown[],
  index: number,
  includeEmpty: boolean,
): void {
  if (!items.length && !includeEmpty) return
  const block = makeBlock(projection, renderer, { title, items }, index)
  blocks[block.id] = block
  parts.push({ id: `${block.id}-part`, kind: 'ui', blockId: block.id })
}

/**
 * Converts the public research projection into assistant-runtime domain data.
 * This is the only place where ResearchEvent/Projection vocabulary enters the
 * conversational renderer. It is pure and can be reused by SSE, snapshot, or
 * a future assistant-ui React adapter.
 */
export function projectResearchProjection(
  projection: UserResearchProjectionV1,
  options: ResearchProjectionAdapterOptions = {},
): AssistantStoreSnapshot {
  const blocks: Record<string, AssistantUiBlock> = {}
  const parts: AssistantMessagePart[] = []
  const includeEmpty = options.includeEmptyCollections ?? false

  if (projection.summary) {
    const block = makeBlock(projection, 'research.summary@1', {
      title: '研究摘要',
      text: projection.summary,
    }, 0)
    blocks[block.id] = block
    parts.push({ id: `${block.id}-part`, kind: 'ui', blockId: block.id })
  }

  collectionBlock(blocks, parts, projection, 'research.plan@1', '研究计划', projection.plan, 1, includeEmpty)
  collectionBlock(blocks, parts, projection, 'research.evidence@1', '评论证据', projection.evidence, 2, includeEmpty)
  collectionBlock(blocks, parts, projection, 'research.controversy@1', '争议与分歧', projection.controversies, 3, includeEmpty)
  collectionBlock(blocks, parts, projection, 'research.profile@1', '店铺档案', projection.profiles, 4, includeEmpty)
  collectionBlock(blocks, parts, projection, 'research.recommendation@1', '值得去看', projection.recommendations, 5, includeEmpty)
  collectionBlock(blocks, parts, projection, 'research.gap@1', '数据缺口', projection.gaps, 6, includeEmpty)

  if (projection.coverage) {
    collectionBlock(
      blocks,
      parts,
      projection,
      'research.coverage@1',
      '研究覆盖度',
      projection.coverage.dimensions ?? [],
      7,
      includeEmpty,
    )
  }

  const message: AssistantDomainMessage = {
    id: `research-run-${projection.runId ?? projection.sessionId}`,
    role: 'assistant',
    parts,
    status: isTerminal(projection.status) ? 'complete' : 'running',
    createdAt: projection.updatedAt,
    metadata: {
      taskId: projection.taskId,
      turnId: projection.turnId,
      status: projection.status,
    },
  }

  return {
    threadId: options.threadId ?? projection.sessionId,
    messages: [message],
    uiBlocks: blocks,
    isRunning: !isTerminal(projection.status),
    runStatus: projection.status,
    lastSequence: projection.lastSequence,
    syncStatus: 'synced',
  }
}

export function replaceWithResearchProjection(
  store: { replace: (snapshot: AssistantStoreSnapshot) => void },
  projection: UserResearchProjectionV1,
  options?: ResearchProjectionAdapterOptions,
): void {
  store.replace(projectResearchProjection(projection, options))
}
