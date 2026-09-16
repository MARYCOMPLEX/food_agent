import { useMemo } from 'react'
import { attachCursor } from './attachCursor'
import { renderMarkdown } from './renderMarkdown'
import './markdown.css'

export interface MarkdownContentProps {
  /** markdown 源文本（来自后端 summary / SSE chunk 累积） */
  content: string
  /** 是否正在流式输出，为 true 时在末尾追加打字机光标 */
  streaming?: boolean
  /** 正文字号，默认 14 */
  fontSize?: number
}

/**
 * 渲染助手回复的 markdown 正文。
 *
 * 这里用 dangerouslySetInnerHTML 是刻意的：HTML 全部由 markdown-it 在
 * `html: false` 下生成，不含任何来源不可控的标签，详见 renderMarkdown.ts。
 */
export function MarkdownContent({ content, streaming = false, fontSize = 14 }: MarkdownContentProps) {
  const html = useMemo(() => {
    const rendered = renderMarkdown(content)
    return streaming ? attachCursor(rendered) : rendered
  }, [content, streaming])

  return (
    <div
      className="md-content"
      style={{ fontSize, lineHeight: 1.8 }}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}
