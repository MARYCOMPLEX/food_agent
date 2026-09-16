import { describe, expect, it } from 'vitest'
import { attachCursor, CURSOR_HTML } from './attachCursor'
import { renderMarkdown } from './renderMarkdown'

/**
 * 回归测试：助手回复的 markdown 渲染 + 流式光标定位。
 *
 * 背景：后端 prompt（orchestrator.py）要求 LLM 输出 markdown，前端此前
 * 用 `whiteSpace: 'pre-line'` 当纯文本渲染，导致 `**粗体**`、`- 列表`、
 * `### 标题` 全部以字面量露出来。改成 markdown-it 渲染后，这里锁住行为，
 * 避免以后再退化回去。
 *
 * 下面 attachCursor 的断言全部按 markdown-it 的真实输出写死（含换行位置），
 * 不靠 `\s*` 之类的模糊匹配——模糊匹配正是当初漏掉嵌套列表这个 bug 的原因。
 */

describe('renderMarkdown', () => {
  it('renders bold, list and heading syntax instead of leaking literals', () => {
    const html = renderMarkdown(
      '我是你的**探店向导**\n\n我能帮你：\n\n- **按城市找馆子**：挑合适的\n- **扒真实口碑**：避开营销店',
    )

    expect(html).toContain('<strong>探店向导</strong>')
    expect(html).toContain('<ul>')
    expect(html).toContain('<li>')
    expect(html).toContain('<strong>按城市找馆子</strong>')
    // 语法字符不能以字面量形式漏出来
    expect(html).not.toContain('**')
  })

  it('renders ### headings and tables', () => {
    expect(renderMarkdown('### 老王面馆')).toContain('<h3>')

    const table = renderMarkdown('| 店名 | 位置 |\n| --- | --- |\n| 老王面馆 | 青羊区 |')
    expect(table).toContain('<table>')
    expect(table).toContain('<th>')
    expect(table).toContain('<td>')
  })

  it('keeps single newlines as <br> (breaks: true, matches the backend prompt template)', () => {
    const html = renderMarkdown('**位置**: 成都市青羊区\n**推荐菜**: 素椒杂酱面')
    expect(html).toContain('<br>')
    expect(html).toContain('<strong>位置</strong>')
    expect(html).toContain('<strong>推荐菜</strong>')
  })

  it('returns empty string for empty input', () => {
    expect(renderMarkdown('')).toBe('')
  })

  it('escapes raw HTML from untrusted LLM output (html: false)', () => {
    const script = renderMarkdown('正常文字 <script>alert(1)</script> 结尾')
    expect(script).not.toContain('<script>')
    expect(script).toContain('&lt;script&gt;')

    const img = renderMarkdown('<img src=x onerror=alert(1)>')
    expect(img).not.toContain('<img')

    // markdown-it 的 validateLink 直接拒绝 javascript: 协议，压根不生成 <a>
    const js = renderMarkdown('[点我](javascript:alert(1))')
    expect(js).not.toMatch(/<a[\s>]/i)
  })

  it('adds target/rel to external links only', () => {
    const external = renderMarkdown('见 https://example.com/x')
    expect(external).toContain('target="_blank"')
    expect(external).toContain('rel="noopener noreferrer nofollow"')

    const internal = renderMarkdown('[详情](/restaurants/42)')
    expect(internal).toContain('href="/restaurants/42"')
    expect(internal).not.toContain('target="_blank"')
  })
})

describe('attachCursor', () => {
  /** markdown-it 的产物带结尾换行，断言前统一去掉。 */
  const trimmed = (source: string) => attachCursor(renderMarkdown(source)).trimEnd()

  it('places the cursor inside the trailing paragraph', () => {
    expect(trimmed('正在为你查找**成都**的馆子'))
      .toBe(`<p>正在为你查找<strong>成都</strong>的馆子${CURSOR_HTML}</p>`)
  })

  // 回归点 1：`<\/(?:p|li|...)>\s*$` 在列表结尾会失配——`</li>` 后面还跟着
  // `</ul>`，`\s*$` 匹配不上，光标掉到列表外面另起一行。
  it('places the cursor inside the last <li> when the stream ends with a list', () => {
    const html = trimmed('- 第一项\n- 第二项')
    expect(html).toBe(
      `<ul>\n<li>第一项</li>\n<li>第二项${CURSOR_HTML}</li>\n</ul>`,
    )
  })

  // 回归点 2：嵌套列表收尾是 `</li></ul></li></ul>` 这种连续串，
  // 「单个标签 + 收尾 </ul>」的写法依然救不了，必须吃掉整段收尾标签。
  it('places the cursor right after the last text run in a nested list', () => {
    const html = trimmed('- 外层\n  - 内层')
    expect(html).toBe(
      `<ul>\n<li>外层\n<ul>\n<li>内层${CURSOR_HTML}</li>\n</ul>\n</li>\n</ul>`,
    )
  })

  it('keeps the cursor inside the trailing table cell', () => {
    const html = trimmed('| 店名 |\n| --- |\n| 老王面馆 |')
    expect(html).toBe(
      '<table>\n<thead>\n<tr>\n<th>店名</th>\n</tr>\n</thead>\n<tbody>\n<tr>\n'
      + `<td>老王面馆${CURSOR_HTML}</td>\n</tr>\n</tbody>\n</table>`,
    )
  })

  it('keeps the cursor inside the trailing fenced code block', () => {
    expect(trimmed('```js\nconst a = 1\n```'))
      .toBe(`<pre><code class="language-js">const a = 1\n${CURSOR_HTML}</code></pre>`)
  })

  it('places the cursor inside the trailing paragraph after a heading', () => {
    expect(trimmed('### 标题\n\n正文**粗体**'))
      .toBe(`<h3>标题</h3>\n<p>正文<strong>粗体</strong>${CURSOR_HTML}</p>`)
  })

  it('falls back to appending when there is no trailing block element', () => {
    expect(attachCursor('裸文本')).toBe(`裸文本${CURSOR_HTML}`)
    expect(attachCursor('')).toBe(CURSOR_HTML)
  })

  it('inserts the cursor exactly once', () => {
    expect(attachCursor(renderMarkdown('- 一\n- 二\n\n结束')).split(CURSOR_HTML)).toHaveLength(2)
  })
})
