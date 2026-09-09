import type { Component } from 'vue'
import type {
  ResearchJsonValue,
  ResearchRunStatusV1,
  UserResearchProjectionV1,
} from '../../shared/contracts/research'

/**
 * Domain-owned message parts. These are deliberately not assistant-ui types.
 * A future React island can project these values into ThreadMessageLike without
 * making the transport or persistence layers depend on assistant-ui.
 */
export type AssistantMessagePart =
  | {
    id: string
    kind: 'text'
    text: string
  }
  | {
    id: string
    kind: 'reasoning'
    text: string
    collapsed?: boolean
  }
  | {
    id: string
    kind: 'tool'
    toolCallId: string
    toolName: string
    argsText?: string
    result?: ResearchJsonValue
    status: 'running' | 'complete' | 'error' | 'cancelled'
  }
  | {
    id: string
    kind: 'ui'
    blockId: string
  }

export interface AssistantDomainMessage {
  id: string
  parentId?: string | null
  role: 'user' | 'assistant' | 'system'
  parts: AssistantMessagePart[]
  status: 'running' | 'complete' | 'error' | 'cancelled'
  createdAt: string
  metadata?: Record<string, ResearchJsonValue>
}

export type AssistantUiBlockStatus = 'pending' | 'streaming' | 'ready' | 'error' | 'cancelled'

export interface AssistantUiAction {
  id: string
  label: string
  payload?: ResearchJsonValue
  disabled?: boolean
}

export interface AssistantUiBlock {
  id: string
  renderer: string
  schemaVersion: number
  revision: number
  status: AssistantUiBlockStatus
  data: ResearchJsonValue
  actions?: AssistantUiAction[]
  artifactRefs?: string[]
}

export interface AssistantStoreSnapshot {
  threadId: string
  messages: AssistantDomainMessage[]
  uiBlocks: Record<string, AssistantUiBlock>
  isRunning: boolean
  runStatus?: ResearchRunStatusV1 | null
  lastSequence: number
  syncStatus: 'idle' | 'streaming' | 'synced' | 'gap-detected' | 'error'
}

export interface AssistantStoreListener {
  (snapshot: AssistantStoreSnapshot): void
}

export interface AssistantTransport {
  sendMessage?: (input: { threadId: string, message: AssistantDomainMessage }) => Promise<void>
  cancelRun?: (threadId: string) => Promise<void>
  reloadThread?: (threadId: string) => Promise<void>
}

export interface AssistantExternalStoreRuntime {
  readonly store: AssistantExternalStoreLike
  getSnapshot: () => AssistantStoreSnapshot
  subscribe: (listener: AssistantStoreListener) => () => void
  sendMessage: (content: string) => Promise<void>
  cancel: () => Promise<void>
  reload: () => Promise<void>
}

export interface AssistantExternalStoreLike {
  getSnapshot: () => AssistantStoreSnapshot
  subscribe: (listener: AssistantStoreListener) => () => void
  replace: (snapshot: AssistantStoreSnapshot) => void
  setMessages: (messages: AssistantDomainMessage[]) => void
  upsertMessage: (message: AssistantDomainMessage) => void
  upsertBlock: (block: AssistantUiBlock) => void
  removeBlock: (blockId: string) => void
  setRunState: (patch: Pick<AssistantStoreSnapshot, 'isRunning' | 'runStatus' | 'lastSequence' | 'syncStatus'>) => void
}

export interface AssistantUiBlockRendererProps {
  block: AssistantUiBlock
  data: unknown
}

export interface AssistantUiBlockSchema {
  safeParse: (value: unknown) => {
    success: boolean
    data?: unknown
    error?: unknown
  }
}

export interface AssistantUiBlockRendererEntry {
  renderer: string
  component: Component
  schema?: AssistantUiBlockSchema
}

export interface AssistantUiBlockRegistry {
  get: (renderer: string) => AssistantUiBlockRendererEntry | undefined
  register: (entry: AssistantUiBlockRendererEntry) => void
  unregister: (renderer: string) => void
  list: () => AssistantUiBlockRendererEntry[]
}

export interface ResearchProjectionAdapterOptions {
  threadId?: string
  includeEmptyCollections?: boolean
}

export type ResearchProjectionInput = Pick<
  UserResearchProjectionV1,
  | 'sessionId'
  | 'taskId'
  | 'turnId'
  | 'runId'
  | 'status'
  | 'summary'
  | 'intent'
  | 'plan'
  | 'evidence'
  | 'controversies'
  | 'profiles'
  | 'recommendations'
  | 'gaps'
  | 'coverage'
  | 'metrics'
  | 'termination'
  | 'updatedAt'
  | 'lastSequence'
>
