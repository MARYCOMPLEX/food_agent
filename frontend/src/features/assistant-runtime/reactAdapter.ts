import type {
  AppendMessage,
  ExternalStoreAdapter,
  ThreadMessageLike,
} from '@assistant-ui/react'
import type {
  AssistantDomainMessage,
  AssistantExternalStoreLike,
  AssistantUiBlock,
} from './types'

function messageStatus(message: AssistantDomainMessage): ThreadMessageLike['status'] {
  if (message.status === 'running') return { type: 'running' }
  if (message.status === 'error') return { type: 'incomplete', reason: 'error' }
  if (message.status === 'cancelled') return { type: 'incomplete', reason: 'cancelled' }
  return { type: 'complete', reason: 'stop' }
}

export function projectDomainMessageToAssistantUi(
  message: AssistantDomainMessage,
  blocks: Record<string, AssistantUiBlock>,
): ThreadMessageLike {
  const content = message.parts.map((part) => {
    if (part.kind === 'text') return { type: 'text' as const, text: part.text }
    if (part.kind === 'reasoning') return { type: 'reasoning' as const, text: part.text }
    if (part.kind === 'tool') {
      return {
        type: 'tool-call' as const,
        toolCallId: part.toolCallId,
        toolName: part.toolName,
        args: {},
        argsText: part.argsText ?? '',
        result: part.result,
        isError: part.status === 'error',
      }
    }

    return {
      type: 'data' as const,
      name: 'app.ui.block',
      data: blocks[part.blockId] ?? {
        id: part.blockId,
        renderer: 'app.missing-block@1',
        schemaVersion: 1,
        revision: 0,
        status: 'error',
        data: null,
      },
    }
  })

  return {
    id: message.id,
    role: message.role,
    content,
    createdAt: new Date(message.createdAt),
    ...(message.role === 'assistant' ? { status: messageStatus(message) } : {}),
    metadata: { custom: message.metadata ?? {} },
  }
}

function textFromAppendMessage(message: AppendMessage): string {
  if (typeof message.content === 'string') return message.content
  return message.content
    .filter((part): part is { type: 'text', text: string } => part.type === 'text')
    .map(part => part.text)
    .join('')
}

/**
 * Adapter for the real assistant-ui ExternalStoreRuntime. The adapter owns
 * only a projection boundary; the application store remains the source of
 * truth and can still be consumed by the Vue shell or another renderer.
 */
export function createAssistantUiExternalStoreAdapter(
  store: AssistantExternalStoreLike,
  snapshot = store.getSnapshot(),
  handlers: {
    onNew?: (message: AssistantDomainMessage) => Promise<void>
    onCancel?: () => Promise<void>
    onRefetchThread?: () => Promise<void>
  } = {},
): ExternalStoreAdapter<AssistantDomainMessage> {
  return {
    messages: snapshot.messages,
    isRunning: snapshot.isRunning,
    isSendDisabled: snapshot.isRunning,
    convertMessage: message => projectDomainMessageToAssistantUi(message, snapshot.uiBlocks),
    onNew: async (message) => {
      const text = textFromAppendMessage(message)
      if (!text.trim()) return
      const domainMessage: AssistantDomainMessage = {
        id: `user-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        role: 'user',
        parts: [{ id: `text-${Date.now()}`, kind: 'text', text }],
        status: 'complete',
        createdAt: new Date().toISOString(),
      }
      store.upsertMessage(domainMessage)
      await handlers.onNew?.(domainMessage)
    },
    onCancel: async () => {
      await handlers.onCancel?.()
    },
    onRefetchThread: async () => {
      await handlers.onRefetchThread?.()
    },
    setMessages: (messages) => {
      store.setMessages([...messages])
    },
  }
}
