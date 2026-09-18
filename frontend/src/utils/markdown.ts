import type { Citation } from '@/types'
import MarkdownIt from 'markdown-it'

const markdown = new MarkdownIt({
  breaks: true,
  html: false,
  linkify: true,
  typographer: false,
})

markdown.inline.ruler.before('link', 'citation', (state, silent) => {
  const match = state.src.slice(state.pos).match(/^\[(\d+)]/)
  if (!match) return false

  const index = Number(match[1])
  const citationIndexes = state.env.citationIndexes as Set<number> | undefined
  if (!citationIndexes?.has(index)) return false

  if (!silent) {
    const token = state.push('citation', '', 0)
    token.meta = { index }
  }
  state.pos += match[0].length
  return true
})

markdown.renderer.rules.citation = (tokens, tokenIndex) => {
  const index = Number(tokens[tokenIndex].meta?.index)
  return `<button type="button" class="markdown-citation" data-citation-index="${index}" title="查看引用 ${index}" aria-label="查看引用 ${index}">[${index}]</button>`
}

export function renderMarkdown(content: string, citations: Citation[] = []) {
  return markdown.render(content, {
    citationIndexes: new Set(citations.map((citation) => citation.index)),
  })
}
