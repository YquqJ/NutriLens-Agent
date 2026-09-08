<script setup lang="ts">
// 工具轨迹折叠面板：展示一轮里 Agent 调用的工具（名称 + 参数 + 结果）。
// 折叠默认收起，避免打断阅读流；展开后按调用顺序列出。
import { ref } from 'vue'
import { toolLabel } from '@/utils/labels'
import type { ToolTraceEntry } from '@/types'

defineProps<{ entries: ToolTraceEntry[] }>()

const open = ref(false)
</script>

<template>
  <div v-if="entries.length" class="trace">
    <button class="trace-head" @click="open = !open">
      <el-icon :class="{ rot: open }"><ArrowRight /></el-icon>
      <span>执行过程</span>
      <span class="count">{{ entries.length }}</span>
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
    </div>
  </div>
</template>

<style scoped>
.trace {
  margin-top: 12px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--bg-elevated);
  overflow: hidden;
}
.trace-head {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 8px 12px;
  border: none;
  background: none;
  cursor: pointer;
  color: var(--ink-3);
  font-size: 13px;
  font-family: var(--font);
}
.trace-head:hover {
  color: var(--ink-2);
}
.trace-head .el-icon {
  transition: transform 0.15s;
  font-size: 13px;
}
.trace-head .el-icon.rot {
  transform: rotate(90deg);
}
.count {
  margin-left: 2px;
  padding: 0 6px;
  background: var(--bg);
  border-radius: 999px;
  font-size: 12px;
  color: var(--ink-3);
}
.trace-body {
  padding: 4px 12px 12px;
}
.entry {
  padding: 8px 0;
  border-top: 1px solid var(--line);
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
  color: var(--ink-3);
  font-size: 12px;
  font-family: var(--font-num);
}
.name {
  font-size: 13px;
  font-weight: 600;
  color: var(--primary-deep);
}
.result {
  margin-top: 4px;
  font-size: 13px;
  color: var(--ink-2);
  white-space: pre-wrap;
  word-break: break-word;
}
.reason {
  margin-top: 2px;
  font-size: 12px;
  color: var(--ink-3);
}
.args {
  margin-top: 4px;
  padding: 4px 8px;
  background: var(--bg);
  border-radius: 4px;
  font-size: 12px;
  font-family: var(--font-num);
  color: var(--ink-3);
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
