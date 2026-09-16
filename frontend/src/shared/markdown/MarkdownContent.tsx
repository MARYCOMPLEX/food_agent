import { useMemo } from 'react'
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

/** 打字机光标。样式见 markdown.css 的 .md-cursor（复用 design-tokens.css 的 cursorBlink）。 */
const CURSOR_HTML = '<span class="md-cursor" aria-hidden="true"></span>'

const TRAILING_BLOCK_RE = /<\/(?:p|li|h[1-6]|td|th|blockquote)>\s*$/u

/**
 * 把光标插进最后一个块级元素内部。
 * 直接拼在 HTML 末尾的话，光标会掉到块元素下面另起一行，视觉上会和文字断开。
 */
function attachCursor(html: string): string {
  const match = html.match(TRAILING_BLOCK_RE)
  if (!match || match.index === undefined) {
    return html + CURSOR_HTML
  }
  return html.slice(0, match.index) + CURSOR_HTML + html.slice(match.index)
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
