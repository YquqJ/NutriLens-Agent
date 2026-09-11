<script setup lang="ts">
// 证据抽屉：同一回答的多条引用纵向列出，点击正文中的任一 [n] 后定位到对应卡片。
import { nextTick, watch } from 'vue'
import type { Citation } from '@/types'

const props = defineProps<{
  visible: boolean
  citations: Citation[]
  activeIndex: number | null
}>()
const emit = defineEmits<{ (e: 'update:visible', value: boolean): void }>()

function scrollToActive() {
  if (!props.visible || props.activeIndex === null) return
  nextTick(() => {
    document.getElementById(`citation-card-${props.activeIndex}`)?.scrollIntoView({
      block: 'nearest',
      behavior: 'smooth',
    })
  })
}

watch(() => [props.visible, props.activeIndex], scrollToActive)
</script>

<template>
  <el-drawer
    :model-value="visible"
    direction="rtl"
    size="min(480px, 100vw)"
    @update:model-value="emit('update:visible', $event)"
  >
    <template #header>
      <div class="drawer-head">
        <span class="title">引用证据</span>
        <span class="count">{{ citations.length }} 条</span>
      </div>
    </template>

    <div class="citation-list">
      <article
        v-for="citation in citations"
        :id="`citation-card-${citation.index}`"
        :key="citation.index"
        class="citation-card"
        :class="{ active: citation.index === activeIndex }"
      >
        <div class="citation-top">
          <span class="citation-index">[{{ citation.index }}]</span>
          <span class="citation-source">{{ citation.source_title }}</span>
        </div>
        <div class="citation-meta">{{ citation.section }}</div>
        <div class="citation-location">
          第 {{ citation.page_number ?? '未知' }} 页 · 片段 {{ citation.chunk_index === null ? '未知' : citation.chunk_index + 1 }}
        </div>
        <div class="citation-content">{{ citation.content }}</div>
      </article>
    </div>
  </el-drawer>
</template>

<style scoped>
.drawer-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.title { font-size: 16px; font-weight: 650; color: var(--text); }
.count { font-size: 12px; color: var(--muted-2); }
.citation-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: calc(100vh - 96px);
  max-height: 100%;
  overflow-y: auto;
  padding: 2px 2px 24px;
}
.citation-card {
  scroll-margin-top: 12px;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--bg-elevated);
  transition: border-color .16s, background .16s;
}
.citation-card.active { border-color: #60a5fa; background: #eff6ff; }
.citation-top { display: flex; align-items: baseline; gap: 8px; }
.citation-index { color: #2563eb; font-family: var(--font-num); font-weight: 700; }
.citation-source { color: var(--text); font-size: 14px; font-weight: 600; }
.citation-meta { margin-top: 7px; color: var(--ink-2); font-size: 13px; line-height: 1.55; }
.citation-location { margin-top: 4px; color: var(--muted-2); font-size: 12px; }
.citation-content {
  margin-top: 12px;
  padding: 10px 11px;
  border-radius: 7px;
  background: var(--surface);
  color: var(--ink-2);
  font-size: 13px;
  line-height: 1.72;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
