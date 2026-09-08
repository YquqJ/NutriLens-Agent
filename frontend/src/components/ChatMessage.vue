<script setup lang="ts">
// 单条对话消息：用户（右对齐气泡，可带图片）与助手（左对齐，agent 徽章 + 文本 + 工具轨迹）。
import { agentLabel } from '@/utils/labels'
import ToolTracePanel from './ToolTracePanel.vue'
import type { ChatMessage } from '@/types'

defineProps<{ message: ChatMessage }>()
</script>

<template>
  <div class="msg" :class="message.role">
    <!-- 助手：agent 徽章 -->
    <div v-if="message.role === 'assistant'" class="assistant">
      <div v-if="message.agentName" class="badge">{{ agentLabel(message.agentName) }}</div>
      <div class="content">
        <template v-if="message.content">{{ message.content }}</template>
        <span v-else-if="message.streaming" class="typing">正在思考…</span>
      </div>
      <ToolTracePanel :entries="message.toolTrace" />
    </div>

    <!-- 用户 -->
    <div v-else class="user">
      <div class="bubble">
        <img v-if="message.imageUrl" :src="message.imageUrl" class="pic" alt="食物图片" />
        <div class="content">{{ message.content }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.msg {
  display: flex;
  margin-bottom: 18px;
}
.msg.user {
  justify-content: flex-end;
}
.msg.assistant {
  justify-content: flex-start;
}

/* 用户气泡 */
.user .bubble {
  max-width: 72%;
  background: var(--primary-soft);
  border: 1px solid #d3e6de;
  border-radius: 12px 12px 2px 12px;
  padding: 10px 14px;
}
.user .content {
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--ink);
}
.pic {
  display: block;
  max-width: 240px;
  max-height: 200px;
  border-radius: 6px;
  margin-bottom: 8px;
  object-fit: cover;
}

/* 助手 */
.assistant {
  max-width: 82%;
  min-width: 0;
}
.badge {
  display: inline-block;
  padding: 1px 8px;
  margin-bottom: 6px;
  background: var(--bg-elevated);
  border: 1px solid var(--line-strong);
  border-radius: 999px;
  color: var(--primary-deep);
  font-size: 12px;
  font-weight: 600;
}
.assistant .content {
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--ink);
  line-height: 1.7;
}
.typing {
  color: var(--ink-3);
  font-size: 13px;
}
</style>
