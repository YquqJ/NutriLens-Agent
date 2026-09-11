<script setup lang="ts">
// 单条对话消息（对齐 CookHero 观感）：
// 用户＝蓝色实心气泡白字右对齐（图片内嵌不溢出）；助手＝机器人头像 + 白底细边气泡 + 下方元信息行。
import { agentLabel } from '@/utils/labels'
import ToolTracePanel from './ToolTracePanel.vue'
import { computed } from 'vue'
import type { ChatMessage, Citation } from '@/types'

const props = defineProps<{ message: ChatMessage }>()
const emit = defineEmits<{ (e: 'citation-click', citation: Citation): void }>()

type ContentPart = { type: 'text'; value: string } | { type: 'citation'; citation: Citation }

// 不使用 v-html：只把后端结构化 citations 中存在的 [n] 渲染成按钮，避免回答文本注入 HTML。
const contentParts = computed<ContentPart[]>(() => {
  const citations = new Map(props.message.citations.map((citation) => [citation.index, citation]))
  const parts: ContentPart[] = []
  const pattern = /\[(\d+)]/g
  let start = 0
  for (const match of props.message.content.matchAll(pattern)) {
    const index = Number(match[1])
    const citation = citations.get(index)
    if (!citation || match.index === undefined) continue
    if (match.index > start) parts.push({ type: 'text', value: props.message.content.slice(start, match.index) })
    parts.push({ type: 'citation', citation })
    start = match.index + match[0].length
  }
  if (start < props.message.content.length) parts.push({ type: 'text', value: props.message.content.slice(start) })
  return parts.length ? parts : [{ type: 'text', value: props.message.content }]
})

// 各 agent 标签配色（淡底 + 深字 + 圆点），通过 CSS 变量注入
const AGENT_TONES: Record<string, string> = {
  diet_agent: 'tone-diet',
  exercise_agent: 'tone-exercise',
  plan_agent: 'tone-plan',
  qa_agent: 'tone-qa',
  supervisor: 'tone-supervisor',
}
function toneClass(name: string | null) {
  return (name && AGENT_TONES[name]) || 'tone-supervisor'
}

function formatDuration(ms: number) {
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`
}

function formatTime(iso: string | null | undefined) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`
  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const startOfMsgDay = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  const diffDays = Math.round((startOfToday.getTime() - startOfMsgDay.getTime()) / 86400000)
  if (diffDays === 0) return hm
  if (diffDays === 1) return `昨天 ${hm}`
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${hm}`
}
</script>

<template>
  <div class="msg" :class="message.role">
    <!-- 助手 -->
    <div v-if="message.role === 'assistant'" class="assistant">
      <div class="avatar">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="12" cy="2.6" r="1.15" />
          <path d="M12 3.8v2.2" />
          <rect x="4" y="6" width="16" height="12" rx="4" />
          <circle cx="9.2" cy="11.4" r="1.15" />
          <circle cx="14.8" cy="11.4" r="1.15" />
          <path d="M9.8 14.9h4.4" />
          <path d="M2.1 10.2v3.4M21.9 10.2v3.4" />
        </svg>
      </div>

      <div class="body">
        <span v-if="message.agentName" class="agent" :class="toneClass(message.agentName)">{{ agentLabel(message.agentName) }}</span>

        <div class="bubble assistant-bubble">
          <template v-if="message.content">
            <template v-for="(part, index) in contentParts" :key="index">
              <button
                v-if="part.type === 'citation'"
                class="citation-link"
                type="button"
                :title="`查看 ${part.citation.label}`"
                @click="emit('citation-click', part.citation)"
              >[{{ part.citation.index }}]</button>
              <template v-else>{{ part.value }}</template>
            </template>
          </template>
          <span v-else-if="message.streaming" class="typing">
            <svg class="spin" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M21 12a9 9 0 1 1-6.2-8.56" />
            </svg>
            正在思考…
          </span>
        </div>

        <ToolTracePanel :entries="message.toolTrace" :streaming="message.streaming" />

        <!-- 元信息行：时间 · 思考/生成耗时 · 复制 -->
        <div class="meta">
          <span v-if="message.createdAt" class="time">{{ formatTime(message.createdAt) }}</span>
          <template v-if="!message.streaming && (message.thinkingMs !== undefined || message.answerMs !== undefined)">
            <svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3.5 2" /></svg>
            <span v-if="message.thinkingMs !== undefined && message.answerMs !== undefined">
              思考 {{ formatDuration(message.thinkingMs) }} · 生成 {{ formatDuration(message.answerMs) }}
            </span>
            <span v-else-if="message.thinkingMs !== undefined">耗时 {{ formatDuration(message.thinkingMs) }}</span>
          </template>
          <!-- <button v-if="message.content" class="copy" title="复制" @click="copy">
            <svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="9" width="12" height="12" rx="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></svg>
          </button> -->
        </div>
      </div>
    </div>

    <!-- 用户 -->
    <div v-else class="user">
      <div class="bubble user-bubble">
        <img v-if="message.imageUrl" :src="message.imageUrl" class="pic" alt="食物图片" />
        <span v-if="message.content" class="content">{{ message.content }}</span>
      </div>
      <div class="meta user-meta">
        <span v-if="message.createdAt" class="time">{{ formatTime(message.createdAt) }}</span>
        <!-- <button v-if="message.content" class="copy" title="复制" @click="copy">
          <svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="9" width="12" height="12" rx="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></svg>
        </button> -->
      </div>
    </div>
  </div>
</template>

<style scoped>
.msg {
  display: flex;
  margin-bottom: 20px;
}

/* ---- 助手 ---- */
.assistant {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  width: 100%;
  min-width: 0;
}
.avatar {
  width: 32px;
  height: 32px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: 10px;
  background: var(--primary-soft);
  border: 1px solid var(--primary-line);
  color: var(--primary-deep);
  margin-top: 1px;
}
.avatar svg {
  width: 20px;
  height: 20px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.6;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.avatar svg circle {
  fill: currentColor;
  stroke: none;
}
.body {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  min-width: 0;
  flex: 1;
}
.agent {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
  padding: 2px 10px;
  font-size: 11.5px;
  font-weight: 600;
  color: var(--tone-fg, var(--primary-deep));
  background: var(--tone-bg, var(--primary-soft));
  border: 1px solid var(--tone-line, var(--primary-line));
  border-radius: 999px;
  letter-spacing: 0.01em;
}
.agent::before {
  content: '';
  width: 5px;
  height: 5px;
  flex: none;
  border-radius: 50%;
  background: var(--tone-dot, var(--primary));
}
.tone-diet { --tone-bg: #e7f6ee; --tone-fg: #15803d; --tone-line: #c9ecd6; --tone-dot: #16a34a; }
.tone-exercise { --tone-bg: #fdf1e7; --tone-fg: #b4542a; --tone-line: #f0d7c4; --tone-dot: #e07b39; }
.tone-plan { --tone-bg: #e8f1fb; --tone-fg: #2563eb; --tone-line: #c9dcf5; --tone-dot: #3b82f6; }
.tone-qa { --tone-bg: #f3ecfb; --tone-fg: #7c3aed; --tone-line: #e0d1f5; --tone-dot: #8b5cf6; }
.tone-supervisor { --tone-bg: #f1f3f5; --tone-fg: #4a5568; --tone-line: #e2e6ea; --tone-dot: #718096; }
.assistant-bubble {
  max-width: 100%;
  padding: 11px 16px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 16px;
  color: var(--text);
  font-size: 14px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}
.citation-link {
  display: inline;
  padding: 0 1px;
  border: none;
  background: none;
  color: #2563eb;
  font: inherit;
  font-weight: 650;
  cursor: pointer;
  text-decoration: underline;
  text-decoration-color: #bfdbfe;
  text-underline-offset: 2px;
}
.citation-link:hover { color: #1d4ed8; text-decoration-color: currentColor; }
.citation-link:focus-visible { outline: 2px solid #93c5fd; outline-offset: 2px; border-radius: 3px; }
.typing {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: var(--muted-2);
  font-size: 13px;
}
.typing .spin {
  width: 15px;
  height: 15px;
  fill: none;
  stroke: var(--muted-2);
  stroke-width: 2.5;
  stroke-linecap: round;
  animation: rot 0.9s linear infinite;
}
@keyframes rot {
  to { transform: rotate(360deg); }
}

/* ---- 元信息行（时间 · 耗时 · 复制）---- */
.meta {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
  font-size: 12px;
  color: var(--muted-2);
}
.time {
  margin-right: 2px;
}
.ic {
  width: 13px;
  height: 13px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.copy {
  display: grid;
  place-items: center;
  padding: 3px;
  border: none;
  background: none;
  color: var(--muted-2);
  cursor: pointer;
  border-radius: 6px;
}
.copy:hover {
  color: var(--muted);
  background: var(--surface-hover);
}

/* ---- 用户：淡绿气泡 ---- */
.user {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  width: 100%;
  min-width: 0;
}
.user-bubble {
  max-width: min(78%, 560px);
  padding: 10px 16px;
  background: var(--primary-soft);
  border: 1px solid var(--primary-line);
  border-radius: 16px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.06);
}
.user .content {
  display: block;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--primary-deep);
  font-size: 14px;
  line-height: 1.65;
}
.pic {
  display: block;
  max-width: 100%;
  max-height: 240px;
  border-radius: 10px;
  object-fit: cover;
}
.pic + .content {
  margin-top: 8px;
}
.user-meta {
  margin-top: 5px;
}
</style>
