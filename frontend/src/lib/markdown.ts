/**
 * Markdown → HTML：marked 渲染 + highlight.js 代码高亮 + DOMPurify 兜底。
 *
 * 为什么要 sanitize：回答里可能包含从 CSV / 数据库读出来的值，
 * 直接 v-html 会把数据里的 <script> 当代码执行。
 *
 * 高亮只注册常用语言（hljs 全量包约 1MB，按需注册后 ~60KB）。
 */
import DOMPurify from 'dompurify'
import hljs from 'highlight.js/lib/core'
import bash from 'highlight.js/lib/languages/bash'
import javascript from 'highlight.js/lib/languages/javascript'
import json from 'highlight.js/lib/languages/json'
import plaintext from 'highlight.js/lib/languages/plaintext'
import python from 'highlight.js/lib/languages/python'
import sql from 'highlight.js/lib/languages/sql'
import typescript from 'highlight.js/lib/languages/typescript'
import { marked } from 'marked'

hljs.registerLanguage('sql', sql)
hljs.registerLanguage('json', json)
hljs.registerLanguage('javascript', javascript)
hljs.registerLanguage('typescript', typescript)
hljs.registerLanguage('python', python)
hljs.registerLanguage('bash', bash)
hljs.registerLanguage('plaintext', plaintext)
hljs.registerLanguage('text', plaintext)

interface CodeToken {
  text: string
  lang?: string
  escaped?: boolean
}

const renderer = new marked.Renderer()

renderer.code = ({ text, lang }: CodeToken): string => {
  const language = lang && hljs.getLanguage(lang) ? lang : ''
  const highlighted = language
    ? hljs.highlight(text, { language }).value
    : hljs.highlightAuto(text).value
  const label = language || 'text'
  return (
    `<pre class="hljs-block"><div class="hljs-bar"><span>${label}</span></div>` +
    `<code class="hljs language-${label}">${highlighted}</code></pre>`
  )
}

marked.use({ renderer, gfm: true, breaks: true })

export function renderMarkdown(text: string): string {
  if (!text) return ''
  const html = marked.parse(text, { async: false }) as string
  return DOMPurify.sanitize(html, { ADD_ATTR: ['target'] })
}

/** 轻量清洗：给表格/纯文本场景复用。 */
export function sanitizeHtml(html: string): string {
  return DOMPurify.sanitize(html)
}
