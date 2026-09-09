import React, { useMemo, useSyncExternalStore, type ReactNode } from 'react'
import {
  AssistantRuntimeProvider,
  ComposerPrimitive,
  useExternalStoreRuntime,
} from '@assistant-ui/react'
import type {
  AssistantDomainMessage,
  AssistantExternalStoreLike,
  AssistantUiBlock,
} from './types'
import { createAssistantUiExternalStoreAdapter } from './reactAdapter'
import './reactIsland.css'

export type ReactUiBlockRenderer = (block: AssistantUiBlock) => ReactNode

export interface ReactAssistantUiRegistry {
  get: (renderer: string) => ReactUiBlockRenderer | undefined
}

function asRecord(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function asText(value: unknown, fallback = ''): string {
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return fallback
}

function compactItem(item: unknown, renderer: string, index: number): ReactNode {
  const value = asRecord(item)
  const title = asText(value.title || value.name || value.topic || value.label || value.code, `项目 ${index + 1}`)
  const summary = asText(value.summary || value.excerpt || value.message || value.detail || value.address)
  const source = asText(value.source || value.status || value.stance || value.severity)
  const meta = [source, value.confidence !== undefined ? `置信度 ${Math.round(Number(value.confidence) * 100)}%` : '']
    .filter(Boolean)
    .join(' · ')

  return (
    <li className="assistant-ui-research-item" key={`${renderer}-${index}`}>
      <strong>{title}</strong>
      {summary ? <span>{summary}</span> : null}
      {meta ? <small>{meta}</small> : null}
    </li>
  )
}

function defaultResearchBlock(block: AssistantUiBlock): ReactNode {
  const data = asRecord(block.data)
  const title = asText(data.title, block.renderer)
  if (block.renderer === 'research.summary@1') {
    return (
      <section className="assistant-ui-research-block">
        <h3>{title}</h3>
        <p>{asText(data.text, '研究正在整理中')}</p>
      </section>
    )
  }

  const items = Array.isArray(data.items) ? data.items : []
  return (
    <section className="assistant-ui-research-block">
      <div className="assistant-ui-research-block__heading">
        <h3>{title}</h3>
        <small>{items.length} 项</small>
      </div>
      {items.length ? (
        <ul>{items.slice(0, 6).map((item, index) => compactItem(item, block.renderer, index))}</ul>
      ) : (
        <p className="assistant-ui-research-block__empty">暂无已确认内容</p>
      )}
    </section>
  )
}

export function createReactAssistantUiRegistry(
  entries: Record<string, ReactUiBlockRenderer> = {},
): ReactAssistantUiRegistry {
  const defaultEntries: Record<string, ReactUiBlockRenderer> = {
    'research.summary@1': defaultResearchBlock,
    'research.plan@1': defaultResearchBlock,
    'research.evidence@1': defaultResearchBlock,
    'research.controversy@1': defaultResearchBlock,
    'research.profile@1': defaultResearchBlock,
    'research.recommendation@1': defaultResearchBlock,
    'research.gap@1': defaultResearchBlock,
    'research.coverage@1': defaultResearchBlock,
  }
  const renderers = { ...defaultEntries, ...entries }
  return {
    get: renderer => renderers[renderer],
  }
}

function DefaultReactBlock({ block, registry }: { block: AssistantUiBlock, registry: ReactAssistantUiRegistry }): ReactNode {
  const renderer = registry.get(block.renderer)
  if (renderer) return renderer(block)
  return (
    <div className="assistant-ui-unknown-block" data-renderer={block.renderer} role="status">
      <strong>暂不支持的内容类型</strong>
      <span>{block.renderer} · v{block.schemaVersion}</span>
    </div>
  )
}

function ReactDomainMessage({
  message,
  blocks,
  registry,
}: {
  message: AssistantDomainMessage
  blocks: Record<string, AssistantUiBlock>
  registry: ReactAssistantUiRegistry
}): ReactNode {
  return (
    <article className={`assistant-ui-message assistant-ui-message--${message.role}`}>
      <div className="assistant-ui-message__role">{message.role === 'user' ? '你' : '研究助手'}</div>
      <div className="assistant-ui-message__parts">
        {message.parts.map((part) => {
          if (part.kind === 'text') return <p key={part.id}>{part.text}</p>
          if (part.kind === 'reasoning') {
            return <details key={part.id}><summary>研究思路摘要</summary><p>{part.text}</p></details>
          }
          if (part.kind === 'tool') {
            return <div key={part.id} className="assistant-ui-tool-call"><strong>{part.toolName}</strong><span>{part.status}</span></div>
          }
          const block = blocks[part.blockId]
          return block
            ? <DefaultReactBlock key={part.id} block={block} registry={registry} />
            : <div key={part.id} className="assistant-ui-unknown-block" role="status">内容暂时不可用</div>
        })}
      </div>
    </article>
  )
}

export interface ReactAssistantIslandProps {
  store: AssistantExternalStoreLike
  registry?: ReactAssistantUiRegistry
  onNew?: (message: AssistantDomainMessage) => Promise<void>
  onCancel?: () => Promise<void>
  className?: string
}

/**
 * Optional React island. Vue remains the default renderer, but this entry is
 * a real assistant-ui runtime boundary and can be mounted into one DOM island
 * when the host page is ready. It does not import Vue or know SSE details.
 */
export function ReactAssistantIsland({
  store,
  registry = createReactAssistantUiRegistry(),
  onNew,
  onCancel,
  className,
}: ReactAssistantIslandProps): ReactNode {
  // React invokes these callbacks without the store as their receiver. Bind
  // them once so class-backed stores keep their subscription state intact.
  const subscribe = useMemo(() => store.subscribe.bind(store), [store])
  const getSnapshot = useMemo(() => store.getSnapshot.bind(store), [store])
  const snapshot = useSyncExternalStore(subscribe, getSnapshot, getSnapshot)
  const adapter = useMemo(
    () => createAssistantUiExternalStoreAdapter(store, snapshot, { onNew, onCancel }),
    [onCancel, onNew, snapshot, store],
  )
  const runtime = useExternalStoreRuntime(adapter)

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <section className={className ?? 'assistant-ui-island'} aria-label="研究对话">
        <div className="assistant-ui-island__messages">
          {snapshot.messages.map(message => (
            <ReactDomainMessage key={message.id} message={message} blocks={snapshot.uiBlocks} registry={registry} />
          ))}
        </div>
        <ComposerPrimitive.Root className="assistant-ui-island__composer">
          <ComposerPrimitive.Input placeholder="继续追问这次研究…" />
          {snapshot.isRunning && onCancel ? (
            <button
              type="button"
              className="assistant-ui-island__cancel"
              onClick={() => { void onCancel() }}
            >
              停止研究
            </button>
          ) : null}
          <ComposerPrimitive.Send>发送</ComposerPrimitive.Send>
        </ComposerPrimitive.Root>
      </section>
    </AssistantRuntimeProvider>
  )
}

export default ReactAssistantIsland
