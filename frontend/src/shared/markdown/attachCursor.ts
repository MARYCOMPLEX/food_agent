/** 打字机光标。样式见 markdown.css 的 .md-cursor（复用 design-tokens.css 的 cursorBlink）。 */
export const CURSOR_HTML = '<span class="md-cursor" aria-hidden="true"></span>'

/** markdown-it 在 html:false 下会产出的块级闭合标签。 */
const CLOSING_BLOCK_TAGS = [
  'p', 'li', 'ul', 'ol', 'dl', 'dt', 'dd',
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'blockquote', 'pre', 'code',
  'table', 'thead', 'tbody', 'tfoot', 'tr', 'td', 'th',
].join('|')

/**
 * 匹配结尾处连续的一整段闭合标签。光标插在这段之前——也就是最后一个
 * 有文字内容的块级元素内部。
 *
 * 为什么不能写 `<\/(?:p|li|...)>\s*$`：流式输出列表时结尾是
 * `</li>\n</ul>\n`，那个 `</li>` 后面还跟着 `</ul>`，`\s*$` 匹配不上，
 * 光标就会掉到 `</ul>` 之后另起一行。嵌套列表更极端，收尾是
 * `</li></ul></li></ul>` 这种连续串，任何「单个标签 + \s*$」的写法都救不了。
 *
 * 换成「吃掉整段收尾标签」之后，无论嵌套多深，光标都紧跟在最后一段文字
 * 后面。正则未加 g 标志，exec 每次都是无状态的左匹配。
 */
const TRAILING_CLOSERS_RE = new RegExp(`(?:</(?:${CLOSING_BLOCK_TAGS})>\\s*)+$`)

/**
 * 把光标插进最后一个块级元素内部。
 * 直接拼在 HTML 末尾的话，光标会掉到块元素下面另起一行，视觉上会和文字断开。
 * 找不到合适位置（例如纯文本、代码块尚未收尾）时退化为追加到末尾。
 */
export function attachCursor(html: string): string {
  const match = TRAILING_CLOSERS_RE.exec(html)
  if (!match) {
    return html + CURSOR_HTML
  }
  return html.slice(0, match.index) + CURSOR_HTML + html.slice(match.index)
}
