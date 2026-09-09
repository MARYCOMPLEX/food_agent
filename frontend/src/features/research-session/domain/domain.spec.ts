import { describe, expect, it } from 'vitest'
import {
  createInitialResearchProjection,
  createResearchSessionStore,
  classifyResearchSseFrame,
  dispatchLegacyTransportMessage,
  legacyToResearchEvents,
  normalizeLegacyTransportMessage,
} from './index'
import { RESEARCH_EVENT_SCHEMA_VERSION } from '../../../shared/contracts/research'
import type { ResearchEventV1 } from '../../../shared/contracts/research'

const occurredAt = '2026-09-09T00:00:00.000Z'

function event(sequence: number, kind: ResearchEventV1['kind'], payload: ResearchEventV1['payload'] = {}): ResearchEventV1 {
  return {
    schemaVersion: RESEARCH_EVENT_SCHEMA_VERSION,
    eventId: `event-${sequence}`,
    sessionId: 'session-1',
    taskId: 'task-1',
    turnId: 1,
    runId: 'run-1',
    sequence,
    occurredAt,
    kind,
    mutation: kind === 'evidence_added' ? 'append' : kind === 'run_started' ? 'replace' : 'upsert',
    payload,
  }
}

describe('research session domain', () => {
  it('initializes snapshots, deduplicates events, buffers gaps and drains them in order', () => {
    const store = createResearchSessionStore({
      snapshot: createInitialResearchProjection('session-1', 'task-1', 1, 'run-1'),
    })

    expect(store.appendEvent(event(1, 'run_started', { summary: '开始研究' })).accepted).toBe(true)
    expect(store.appendEvent(event(1, 'run_started', { summary: '重复' })).duplicate).toBe(true)
    expect(store.appendEvent(event(3, 'evidence_added', {
      evidence: { evidenceId: 'evidence-3', source: 'xhs', excerpt: '第三条' },
    })).buffered).toBe(true)
    expect(store.getState().sequenceGap?.expectedSequence).toBe(2)
    expect(store.appendEvent(event(2, 'evidence_added', {
      evidence: { evidenceId: 'evidence-2', source: 'xhs', excerpt: '第二条', commentRef: 'comment-2' },
    })).accepted).toBe(true)

    const projection = store.getState().projection
    expect(projection?.lastSequence).toBe(3)
    expect(projection?.evidence.map(item => item.evidenceId)).toEqual(['evidence-2', 'evidence-3'])
    expect(store.getState().sequenceGap).toBeNull()
  })

  it('does not allow an older snapshot to overwrite a newer revision', () => {
    const store = createResearchSessionStore()
    const current = createInitialResearchProjection('session-1', 'task-1', 1, 'run-1')
    const accepted = store.initializeSnapshot({ ...current, revision: 4, lastSequence: 4 })
    expect(accepted.accepted).toBe(true)
    const stale = store.initializeSnapshot({ ...current, revision: 2, lastSequence: 2 })
    expect(stale.ignored).toBe(true)
    expect(store.getState().projection?.revision).toBe(4)
    expect(store.getState().ignoredSnapshotCount).toBe(1)
  })

  it('keeps legacy transport explicit and maps only safe partial semantics', () => {
    const message = classifyResearchSseFrame({
      eventName: 'result',
      cursor: 'cursor-1',
      data: JSON.stringify({
        summary: '找到一家店',
        recommendations: [{ id: 'shop-1', name: '小店', oneLiner: '评论里反复提到的招牌菜' }],
      }),
    })
    expect(message.kind).toBe('legacy')
    if (message.kind === 'legacy') {
      expect(normalizeLegacyTransportMessage(message).compatibility).toBe('partial')
      const events = legacyToResearchEvents(message, {
        sessionId: 'session-1',
        taskId: 'task-1',
        turnId: 1,
        runId: 'run-1',
        startSequence: 1,
      })
      expect(events[0]?.kind).toBe('recommendation_upserted')
      expect(events[0]?.payload).toMatchObject({ recommendation: { title: '小店' } })

      const store = createResearchSessionStore()
      const results = dispatchLegacyTransportMessage(store, 'session-1', message)
      expect(results[0]?.accepted).toBe(true)
      expect(store.getState().projection?.recommendations[0]?.title).toBe('小店')
    }
  })

  it('maps legacy action milestones and explicit restaurant candidates without fabricating evidence', () => {
    const context = {
      sessionId: 'session-1',
      taskId: 'task-1',
      turnId: 1,
      startSequence: 1,
      occurredAt,
    }
    const actionCases: Array<[string, string]> = [
      ['intent_parsed', 'action_completed'],
      ['analysis_done', 'action_completed'],
      ['step_start', 'action_started'],
      ['step_done', 'action_completed'],
      ['step_error', 'action_progress'],
    ]
    for (const [eventName, expectedKind] of actionCases) {
      const legacy = { kind: 'legacy' as const, eventName, data: { step: 'step1', message: '阶段信息' }, cursor: null }
      const normalized = normalizeLegacyTransportMessage(legacy)
      expect(normalized.semantic).toBe('action')
      const mapped = legacyToResearchEvents(legacy, context)
      expect(mapped[0]?.kind).toBe(expectedKind)
      expect(mapped[0]?.payload).not.toHaveProperty('evidence')
    }

    const restaurant = {
      kind: 'legacy' as const,
      eventName: 'restaurant',
      data: { restaurant: { id: 'shop-9', name: '单店候选', oneLiner: '评论提及' } },
      cursor: null,
    }
    const restaurantEvent = legacyToResearchEvents(restaurant, context)[0]
    expect(restaurantEvent?.kind).toBe('recommendation_upserted')
    expect(restaurantEvent?.payload).toMatchObject({ recommendation: { title: '单店候选', status: 'candidate' } })

    const notes = {
      kind: 'legacy' as const,
      eventName: 'notes_found',
      data: { restaurants: [{ id: 'shop-10', name: '笔记提到的店' }] },
      cursor: null,
    }
    const noteEvent = legacyToResearchEvents(notes, context)[0]
    expect(noteEvent?.kind).toBe('recommendation_upserted')
    expect(noteEvent?.payload).toMatchObject({ recommendation: { title: '笔记提到的店', status: 'candidate' } })

    const ordinaryNote = {
      kind: 'legacy' as const,
      eventName: 'notes_found',
      data: { items: [{ id: 'note-1', title: '普通笔记标题' }] },
      cursor: null,
    }
    expect(legacyToResearchEvents(ordinaryNote, context)[0]?.kind).toBe('action_completed')
  })
})
