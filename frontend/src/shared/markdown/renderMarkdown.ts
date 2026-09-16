import MarkdownIt from 'markdown-it'

/**
 * 唯一的 markdown 渲染实例。
 *
 * 安全前提：`html: false`。
 * LLM 的输出是不可信内容，禁用源码内联 HTML 后，markdown-it 会把所有
 * `<`、`>`、`&` 转义成实体，因此产物只可能由 markdown 语法生成，
 * 不存在注入任意标签/脚本的路径。链接另有 markdown-it 内置的
 * `validateLink` 兜底（拦截 javascript: / vbscript: / file: 等协议）。
 */
const md = new MarkdownIt({
  html: false,
  linkify: true,
  // 后端 prompt 的模板用单个换行分隔 "**位置**: xxx" 这类字段，
  // breaks 打开才能得到预期的换行，而不是被折成一整段。
  breaks: true,
  typographer: false,
})

// 外链补 target/rel，避免反向 tabnabbing；站内相对链接不动。
md.renderer.rules.link_open = (tokens, idx, options, _env, self) => {
  const token = tokens[idx]
  const href = token.attrGet('href') ?? ''
  if (/^https?:\/\//i.test(href)) {
    token.attrSet('target', '_blank')
    token.attrSet('rel', 'noopener noreferrer nofollow')
  }
  return self.renderToken(tokens, idx, options)
}

/** 把 markdown 源文本渲染为安全的 HTML 字符串。 */
export function renderMarkdown(source: string): string {
  if (!source) {
    return ''
  }
  return md.render(source)
}
