import type { Restaurant } from './restaurant'

export interface PipelineStep {
  id: string
  label: string
  status: 'pending' | 'loading' | 'done' | 'error'
  detail?: string
}

export interface ParsedIntent {
  location: string
  food_type: string | null
  requirements: string[]
  exclude_keywords: string[]
}

export interface Message {
  role: 'user' | 'assistant'
  content: string
  restaurants?: Restaurant[]
  pipeline?: PipelineStep[]
  intent?: ParsedIntent
  summary?: string
  timestamp: number
}

export interface SearchSession {
  sessionId: string
  messages: Message[]
  restaurants: Restaurant[]
  pipeline: PipelineStep[]
  status: 'idle' | 'searching' | 'completed' | 'error'
  intent?: ParsedIntent
  summary?: string
  turnCount: number
}

export type SSEEventType =
  | 'step_start' | 'step_done' | 'step_error'
  | 'progress' | 'intent_parsed' | 'notes_found'
  | 'analysis_done' | 'restaurant' | 'result'
  | 'error' | 'done'
