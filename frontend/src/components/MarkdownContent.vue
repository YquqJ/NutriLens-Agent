<script setup lang="ts">
import { computed } from 'vue'
import type { Citation } from '@/types'
import { renderMarkdown } from '@/utils/markdown'

const props = withDefaults(
  defineProps<{
    content: string
    citations?: Citation[]
  }>(),
  {
    citations: () => [],
  },
)

const emit = defineEmits<{
  (event: 'citation-click', citation: Citation): void
}>()

const renderedContent = computed(() => renderMarkdown(props.content, props.citations))

function handleClick(event: MouseEvent) {
  const target = event.target
  if (!(target instanceof Element)) return

  const button = target.closest<HTMLButtonElement>('[data-citation-index]')
  if (!button) return

  const index = Number(button.dataset.citationIndex)
  const citation = props.citations.find((item) => item.index === index)
  if (citation) emit('citation-click', citation)
}
</script>

<template>
  <div class="markdown-content" v-html="renderedContent" @click="handleClick"></div>
</template>

<style scoped lang="scss">
.markdown-content {
  min-width: 0;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.markdown-content :deep(> :first-child) {
  margin-top: 0;
}

.markdown-content :deep(> :last-child) {
  margin-bottom: 0;
}

.markdown-content :deep(p) {
  margin: 0.65em 0;
}

.markdown-content :deep(h1),
.markdown-content :deep(h2),
.markdown-content :deep(h3),
.markdown-content :deep(h4) {
  margin: 1.25em 0 0.55em;
  color: var(--ink);
  line-height: 1.35;
}

.markdown-content :deep(h1) {
  font-size: 1.45em;
}

.markdown-content :deep(h2) {
  font-size: 1.28em;
}

.markdown-content :deep(h3) {
  font-size: 1.14em;
}

.markdown-content :deep(h4) {
  font-size: 1em;
}

.markdown-content :deep(ul),
.markdown-content :deep(ol) {
  margin: 0.7em 0;
  padding-left: 1.65em;
}

.markdown-content :deep(li + li) {
  margin-top: 0.32em;
}

.markdown-content :deep(blockquote) {
  margin: 0.9em 0;
  padding: 0.2em 0 0.2em 1em;
  border-left: 3px solid var(--primary-line);
  color: var(--ink-2);
}

.markdown-content :deep(a) {
  color: var(--primary-deep);
  font-weight: 600;
  text-decoration: underline;
  text-decoration-color: var(--primary-line);
  text-underline-offset: 3px;
}

.markdown-content :deep(code) {
  padding: 0.12em 0.38em;
  border: 1px solid var(--line);
  border-radius: 4px;
  background: var(--surface-hover);
  font-family: Consolas, 'Courier New', monospace;
  font-size: 0.9em;
}

.markdown-content :deep(pre) {
  max-width: 100%;
  margin: 0.9em 0;
  padding: 14px 16px;
  overflow-x: auto;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: #f7faf8;
}

.markdown-content :deep(pre code) {
  padding: 0;
  border: none;
  background: transparent;
  font-size: 0.88em;
}

.markdown-content :deep(table) {
  width: 100%;
  margin: 0.9em 0;
  border-collapse: collapse;
  font-size: 0.94em;
}

.markdown-content :deep(th),
.markdown-content :deep(td) {
  padding: 8px 10px;
  border: 1px solid var(--line);
  text-align: left;
  vertical-align: top;
}

.markdown-content :deep(th) {
  background: var(--primary-soft);
  color: var(--primary-deep);
  font-weight: 700;
}

.markdown-content :deep(hr) {
  margin: 1.2em 0;
  border: none;
  border-top: 1px solid var(--line);
}

.markdown-content :deep(.markdown-citation) {
  display: inline;
  padding: 0 2px;
  border: none;
  border-radius: 3px;
  background: none;
  color: #2563eb;
  font: inherit;
  font-weight: 700;
  cursor: pointer;
  text-decoration: underline;
  text-decoration-color: #bfdbfe;
  text-underline-offset: 2px;
}

.markdown-content :deep(.markdown-citation:hover) {
  color: #1d4ed8;
  text-decoration-color: currentColor;
}

.markdown-content :deep(.markdown-citation:focus-visible) {
  outline: 2px solid #93c5fd;
  outline-offset: 2px;
}
</style>
