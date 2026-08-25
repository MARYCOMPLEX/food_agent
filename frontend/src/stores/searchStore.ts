import { create } from 'zustand'
import type { Restaurant } from '../types/restaurant'
import type { PipelineStep, ParsedIntent, Message } from '../types/search'
import { startSearch, createSSEConnection } from '../api/searchApi'

const DEFAULT_PIPELINE: PipelineStep[] = [
  { id: 'intent_parsing', label: '解析搜索意图', status: 'pending' },
  { id: 'xhs_search', label: '搜索小红书笔记', status: 'pending' },
  { id: 'comment_analysis', label: '分析评论内容', status: 'pending' },
  { id: 'cross_validation', label: '交叉验证店铺', status: 'pending' },
  { id: 'poi_enrichment', label: '获取地址信息', status: 'pending' },
  { id: 'result_generation', label: '生成推荐结果', status: 'pending' },
]

interface SearchState {
  sessionId: string | null
  messages: Message[]
  restaurants: Restaurant[]
  pipeline: PipelineStep[]
  status: 'idle' | 'searching' | 'completed' | 'error'
  intent: ParsedIntent | null
  summary: string
  eventSource: EventSource | null
  eventCount: number

  search: (query: string) => Promise<void>
  followUp: (query: string) => Promise<void>
  reset: () => void
}

export const useSearchStore = create<SearchState>((set, get) => ({
  sessionId: null,
  messages: [],
  restaurants: [],
  pipeline: [...DEFAULT_PIPELINE],
  status: 'idle',
  intent: null,
  summary: '',
  eventSource: null,
  eventCount: 0,

  search: async (query: string) => {
    const state = get()
    state.eventSource?.close()

    set({
      status: 'searching',
      restaurants: [],
      pipeline: DEFAULT_PIPELINE.map(s => ({ ...s, status: 'pending' as const })),
      intent: null,
      summary: '',
      eventCount: 0,
      messages: [...state.messages, {
        role: 'user',
        content: query,
        timestamp: Date.now(),
      }],
    })

    try {
      const res = await startSearch(query, state.sessionId || undefined)
      const sid = res.sessionId
      set({ sessionId: sid })
      connectSSE(sid, set, get)
    } catch {
      set({ status: 'error' })
    }
  },

  followUp: async (query: string) => {
    const state = get()
    if (!state.sessionId) return
    state.eventSource?.close()

    set({
      status: 'searching',
      restaurants: [],
      pipeline: DEFAULT_PIPELINE.map(s => ({ ...s, status: 'pending' as const })),
      intent: null,
      summary: '',
      eventCount: 0,
      messages: [...state.messages, {
        role: 'user',
        content: query,
        timestamp: Date.now(),
      }],
    })

    try {
      const res = await startSearch(query, state.sessionId)
      connectSSE(res.sessionId, set, get)
    } catch {
      set({ status: 'error' })
    }
  },

  reset: () => {
    get().eventSource?.close()
    set({
      sessionId: null,
      messages: [],
      restaurants: [],
      pipeline: [...DEFAULT_PIPELINE],
      status: 'idle',
      intent: null,
      summary: '',
      eventSource: null,
      eventCount: 0,
    })
  },
}))

function connectSSE(
  sessionId: string,
  set: (partial: Partial<SearchState>) => void,
  get: () => SearchState,
) {
  const es = createSSEConnection(sessionId, get().eventCount)
  set({ eventSource: es })

  es.addEventListener('step_start', (e) => {
    const data = JSON.parse(e.data)
    set({
      eventCount: get().eventCount + 1,
      pipeline: get().pipeline.map(s =>
        s.id === data.step ? { ...s, status: 'loading' as const, detail: data.detail } : s
      ),
    })
  })

  es.addEventListener('step_done', (e) => {
    const data = JSON.parse(e.data)
    set({
      eventCount: get().eventCount + 1,
      pipeline: get().pipeline.map(s =>
        s.id === data.step ? { ...s, status: 'done' as const, detail: data.detail } : s
      ),
    })
  })

  es.addEventListener('step_error', (e) => {
    const data = JSON.parse(e.data)
    set({
      eventCount: get().eventCount + 1,
      pipeline: get().pipeline.map(s =>
        s.id === data.step ? { ...s, status: 'error' as const, detail: data.detail } : s
      ),
    })
  })

  es.addEventListener('intent_parsed', (e) => {
    const data = JSON.parse(e.data)
    set({ eventCount: get().eventCount + 1, intent: data.intent })
  })

  es.addEventListener('restaurant', (e) => {
    const data = JSON.parse(e.data)
    if (data.restaurant) {
      set({
        eventCount: get().eventCount + 1,
        restaurants: [...get().restaurants, data.restaurant],
      })
    }
  })

  es.addEventListener('result', (e) => {
    const data = JSON.parse(e.data)
    set({ eventCount: get().eventCount + 1, summary: data.summary || '' })
  })

  es.addEventListener('done', () => {
    const state = get()
    set({
      eventCount: state.eventCount + 1,
      status: 'completed',
      messages: [...state.messages, {
        role: 'assistant',
        content: state.summary || `找到 ${state.restaurants.length} 家推荐餐厅`,
        restaurants: [...state.restaurants],
        pipeline: [...state.pipeline],
        intent: state.intent || undefined,
        summary: state.summary,
        timestamp: Date.now(),
      }],
    })
    es.close()
    set({ eventSource: null })
  })

  es.addEventListener('error', (e) => {
    // EventSource uses the same event name for transport failures. Those
    // events have no data and must reach `onerror` so the stream can reconnect.
    const raw = (e as MessageEvent<string>).data
    if (typeof raw !== 'string' || !raw.trim()) return
    set({ eventCount: get().eventCount + 1, status: 'error' })
    es.close()
    set({ eventSource: null })
  })

  es.onerror = () => {
    if (get().status === 'searching') {
      es.close()
      setTimeout(() => {
        if (get().status === 'searching') {
          connectSSE(sessionId, set, get)
        }
      }, 2000)
    }
  }
}
