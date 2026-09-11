import { describe, expect, it } from 'vitest'
import {
  createInitialResearchProjection,
  createResearchSessionStore,
} from '../features/research-session/domain'
import { dispatchLegacyTransportMessageToStore } from '../features/research-session/domain/useResearchSessionReact'
import { classifyResearchSseFrame } from '../features/research-session/domain/transport'
import { RESEARCH_EVENT_SCHEMA_VERSION } from '../shared/contracts/research'
import type { ResearchEventV1 } from '../shared/contracts/research'

describe('reactSession domain bridge', () => {
  it('handles React store updates and legacy frame dispatching cleanly', () => {
    const store = createResearchSessionStore({
      snapshot: createInitialResearchProjection('session-react-1', 'task-react-1', 1, 'run-1'),
    })

    const event: ResearchEventV1 = {
      schemaVersion: RESEARCH_EVENT_SCHEMA_VERSION,
      eventId: 'ev-1',
      sessionId: 'session-react-1',
      taskId: 'task-react-1',
      turnId: 1,
      runId: 'run-1',
      sequence: 1,
      occurredAt: new Date().toISOString(),
      kind: 'evidence_added',
      mutation: 'append',
      payload: {
        evidence: {
          evidenceId: 'ev-item-1',
          source: 'xhs_pc',
          excerpt: '锅底香气很足，辣而不燥，老店确实名不虚传',
          stance: 'positive',
        },
      },
    }

    const res = store.appendEvent(event)
    expect(res.accepted).toBe(true)
    expect(store.getState().projection?.evidence).toHaveLength(1)
    expect(store.getState().projection?.evidence[0]?.stance).toBe('positive')

    // Test legacy frame dispatch via dispatchLegacyTransportMessageToStore
    const frame = classifyResearchSseFrame({
      eventName: 'result',
      cursor: 'cur-100',
      data: JSON.stringify({
        summary: '经过深入调查，为您推荐一家本地人认可的老店',
        recommendations: [
          {
            id: 'rec-1',
            name: '蜀九香老火锅',
            oneLiner: '评论一致赞誉牛油锅底醇厚',
          },
        ],
      }),
    })

    if (frame.kind === 'legacy') {
      const dispatched = dispatchLegacyTransportMessageToStore(store, 'session-react-1', frame)
      expect(dispatched.length).toBeGreaterThan(0)
      expect(dispatched[0]?.accepted).toBe(true)
      expect(store.getState().projection?.recommendations[0]?.title).toBe('蜀九香老火锅')
    }
  })
})
