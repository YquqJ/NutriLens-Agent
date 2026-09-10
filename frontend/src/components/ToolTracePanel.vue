<script setup lang="ts">
// 工具轨迹折叠面板（对齐 CookHero thinking block）：灰底圆角卡片头，流式中显示 spinner，展开列出各工具调用。
import { ref } from 'vue'
import { toolLabel } from '@/utils/labels'
import type { ToolTraceEntry } from '@/types'

defineProps<{ entries: ToolTraceEntry[]; streaming?: boolean }>()

const open = ref(false)
</script>

<template>
  <div v-if="entries.length || streaming" class="trace" :class="{ open }">
    <button class="trace-head" @click="open = !open">
      <span class="head-left">
        <!-- 流式：旋转 spinner；完成：CPU 图标 -->
        <svg v-if="streaming" class="spin" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M21 12a9 9 0 1 1-6.2-8.56" />
        </svg>
        <svg v-else class="cpu" viewBox="0 0 24 24" aria-hidden="true">
          <rect x="6" y="6" width="12" height="12" rx="2" />
          <rect x="9.5" y="9.5" width="5" height="5" />
          <path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3" />
        </svg>
        <span class="title">执行过程</span>
        <span v-if="entries.length" class="count">{{ entries.length }}</span>
      </span>
      <svg class="chev" :class="{ rot: open }" viewBox="0 0 24 24" aria-hidden="true">
        <path d="m6 9 6 6 6-6" />
      </svg>
    </button>

    <div v-show="open" class="trace-body">
      <div v-for="(e, i) in entries" :key="i" class="entry">
        <div class="entry-head">
          <span class="idx">{{ i + 1 }}</span>
          <span class="name">{{ toolLabel(e.name) }}</span>
        </div>
        <div v-if="e.result" class="result">{{ e.result }}</div>
        <div v-if="e.reason" class="reason">{{ e.reason }}</div>
        <div v-if="e.args && Object.keys(e.args).length" class="args">
          {{ JSON.stringify(e.args) }}
        </div>
      </div>
      <div v-if="streaming && !entries.length" class="pending">等待工具调用…</div>
    </div>
  </div>
</template>

<style scoped>
.trace {
  max-width: 100%;
  /* width: 100%; */
  margin-top: 8px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface);
  overflow: hidden;
}
.trace-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 7px 12px;
  border: none;
  background: none;
  cursor: pointer;
  color: var(--muted);
  font-size: 13px;
  font-family: var(--font);
}
.trace-head:hover {
  color: var(--text);
}
.head-left {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-right: 4px;
}
.title {
  font-weight: 500;
}
.spin {
  width: 14px;
  height: 14px;
  fill: none;
  stroke: #f59e0b;
  stroke-width: 2.5;
  stroke-linecap: round;
  animation: rot 0.9s linear infinite;
}
@keyframes rot {
  to { transform: rotate(360deg); }
}
.cpu {
  width: 14px;
  height: 14px;
  fill: none;
  stroke: var(--primary);
  stroke-width: 1.7;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.chev {
  width: 15px;
  height: 15px;
  fill: none;
  stroke: currentColor;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
  transition: transform 0.15s;
}
.chev.rot {
  transform: rotate(180deg);
}
.count {
  padding: 0 6px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 999px;
  font-size: 11px;
  color: var(--muted);
  font-family: var(--font-num);
}
.trace-body {
  padding: 0 12px 10px;
  border-top: 1px solid var(--border);
  background: var(--bg-elevated);
}
.pending {
  padding: 8px 0;
  font-size: 12px;
  color: var(--muted-2);
}
.entry {
  padding: 8px 0;
  border-top: 1px solid var(--surface-hover);
}
.entry:first-child {
  border-top: none;
}
.entry-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.idx {
  color: var(--muted-2);
  font-size: 12px;
  font-family: var(--font-num);
}
.name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}
.result {
  margin-top: 4px;
  font-size: 13px;
  color: var(--muted);
  white-space: pre-wrap;
  word-break: break-word;
}
.reason {
  margin-top: 2px;
  font-size: 12px;
  color: var(--muted-2);
}
.args {
  margin-top: 4px;
  padding: 4px 8px;
  background: var(--surface);
  border-radius: 4px;
  font-size: 12px;
  font-family: var(--font-num);
  color: var(--muted);
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
