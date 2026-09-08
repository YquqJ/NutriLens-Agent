<script setup lang="ts">
// 对话页：会话列表 + SSE 流式渲染 + HITL 确认卡片。
// 流式协议：POST /chat 返回 SSE 分帧（token/agent_trace/tool_calls/interrupt/done），
// fetch + ReadableStream 逐帧解析；interrupt 挂起后经 /chat/resume 恢复。
import { computed, nextTick, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getToken } from '@/api/http'
import { listConversations, createConversation, getMessages, deleteConversation } from '@/api/conversations'
import { uploadImage } from '@/api/uploads'
import { getErrorMessage } from '@/utils/error'
import ChatMessage from '@/components/ChatMessage.vue'
import HitlCard from '@/components/HitlCard.vue'
import type {
  ChatMessage as ChatMsg,
  Conversation,
  DietDraftItem,
  Message,
  SseEvent,
  ToolTraceEntry,
} from '@/types'

const convs = ref<Conversation[]>([])
const activeId = ref<string | null>(null)
const messages = ref<ChatMsg[]>([])
const input = ref('')
const streaming = ref(false)
const pendingMsg = ref<ChatMsg | null>(null)
const listEl = ref<HTMLElement | null>(null)
const imageUrl = ref<string | null>(null)
const uploading = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

const busy = computed(() => streaming.value || !!pendingMsg.value)
const canSend = computed(() => !busy.value && (!!input.value.trim() || !!imageUrl.value))

const EXAMPLES = ['帮我记录午餐：一碗牛肉面', '我今天吃了多少卡路里？', '减脂期每天吃多少蛋白质？']

// ---- 工具 ----
let seq = 0
const uid = () => `t${Date.now()}_${seq++}`

function toChatMessage(m: Message): ChatMsg {
  let toolTrace: ToolTraceEntry[] = []
  if (m.tool_trace) {
    try {
      toolTrace = JSON.parse(m.tool_trace)
    } catch {
      toolTrace = []
    }
  }
  return {
    key: `m${m.id}`,
    role: m.role,
    content: m.content,
    imageUrl: m.image_url,
    agentName: m.agent_name,
    toolTrace,
    streaming: false,
    interrupt: null,
  }
}

function scrollBottom() {
  nextTick(() => {
    if (listEl.value) listEl.value.scrollTop = listEl.value.scrollHeight
  })
}

function formatTime(iso: string) {
  const d = new Date(iso)
  const now = new Date()
  const sameDay = d.toDateString() === now.toDateString()
  const pad = (n: number) => String(n).padStart(2, '0')
  if (sameDay) return `${pad(d.getHours())}:${pad(d.getMinutes())}`
  return `${d.getMonth() + 1}/${d.getDate()}`
}

// ---- SSE 流 ----
async function streamRequest(url: string, body: unknown, live: ChatMsg) {
  const resp = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${getToken()}` },
    body: JSON.stringify(body),
  })
  if (!resp.ok || !resp.body) {
    throw new Error(`请求失败（HTTP ${resp.status}）`)
  }
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  const handle = (e: SseEvent) => {
    switch (e.type) {
      case 'token':
        live.content += e.content
        scrollBottom()
        break
      case 'agent_trace':
        live.agentName = e.to
        break
      case 'tool_calls':
        live.toolTrace.push(e.entry)
        break
      case 'interrupt':
        live.interrupt = e.payload
        live.streaming = false
        pendingMsg.value = live
        break
      case 'done':
        live.streaming = false
        if (!e.interrupted) live.agentName = e.agent_name || live.agentName
        break
      case 'error':
        live.content += `\n[出错了] ${e.message}`
        live.streaming = false
        break
    }
  }
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let idx: number
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const frame = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      let event = ''
      let data = ''
      for (const line of frame.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) data = line.slice(5).trim()
      }
      if (event && data) {
        try {
          handle(JSON.parse(data) as SseEvent)
        } catch {
          /* 忽略解析失败的帧 */
        }
      }
    }
  }
}

// ---- 会话管理 ----
async function loadConversations() {
  convs.value = await listConversations()
  if (convs.value.length) await selectConversation(convs.value[0].id)
  else await newConversation()
}

async function selectConversation(id: string) {
  activeId.value = id
  pendingMsg.value = null
  streaming.value = false
  try {
    messages.value = (await getMessages(id)).map(toChatMessage)
  } catch (e) {
    ElMessage.error(getErrorMessage(e))
  }
  scrollBottom()
}

async function newConversation() {
  const c = await createConversation()
  convs.value.unshift(c)
  activeId.value = c.id
  messages.value = []
  pendingMsg.value = null
}

async function removeConversation(id: string) {
  try {
    await ElMessageBox.confirm('删除该会话？历史消息将一并清除。', '删除会话', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  await deleteConversation(id)
  convs.value = convs.value.filter((c) => c.id !== id)
  if (activeId.value === id) {
    if (convs.value.length) await selectConversation(convs.value[0].id)
    else await newConversation()
  }
}

// ---- 发送 / 恢复 ----
function pickImage() {
  fileInput.value?.click()
}

async function onFileChange(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  ;(e.target as HTMLInputElement).value = ''
  if (!file) return
  uploading.value = true
  try {
    imageUrl.value = await uploadImage(file)
  } catch (err) {
    ElMessage.error(getErrorMessage(err, '图片上传失败'))
  } finally {
    uploading.value = false
  }
}

function clearImage() {
  imageUrl.value = null
}

async function send(text?: string) {
  const typed = (text ?? input.value).trim()
  const img = imageUrl.value
  if (busy.value || !activeId.value) return
  if (!typed && !img) return
  const content = typed || '识别这张图'
  input.value = ''
  imageUrl.value = null
  messages.value.push({
    key: uid(), role: 'user', content, imageUrl: img,
    agentName: null, toolTrace: [], streaming: false, interrupt: null,
  })
  const live: ChatMsg = {
    key: uid(), role: 'assistant', content: '', imageUrl: null,
    agentName: null, toolTrace: [], streaming: true, interrupt: null,
  }
  messages.value.push(live)
  streaming.value = true
  scrollBottom()
  try {
    await streamRequest(
      `/api/conversations/${activeId.value}/chat`,
      { content, image_url: img },
      live,
    )
  } catch (e) {
    live.content += `\n[请求失败] ${getErrorMessage(e)}`
    live.streaming = false
  } finally {
    streaming.value = false
    scrollBottom()
  }
  if (!live.interrupt) await refreshList()
}

async function confirmDiet(items: DietDraftItem[]) {
  const live = pendingMsg.value
  if (!live || !activeId.value) return
  live.interrupt = null
  live.streaming = true
  pendingMsg.value = null
  streaming.value = true
  try {
    await streamRequest(`/api/conversations/${activeId.value}/chat/resume`, { value: { items } }, live)
  } catch (e) {
    live.content += `\n[请求失败] ${getErrorMessage(e)}`
    live.streaming = false
  } finally {
    streaming.value = false
    await refreshList()
  }
}

async function cancelDiet() {
  const live = pendingMsg.value
  if (!live || !activeId.value) return
  live.interrupt = null
  live.streaming = true
  pendingMsg.value = null
  streaming.value = true
  try {
    await streamRequest(`/api/conversations/${activeId.value}/chat/resume`, { value: false }, live)
  } catch (e) {
    live.content += `\n[请求失败] ${getErrorMessage(e)}`
    live.streaming = false
  } finally {
    streaming.value = false
    await refreshList()
  }
}

async function refreshList() {
  convs.value = await listConversations()
}

onMounted(loadConversations)
</script>

<template>
  <div class="chat">
    <!-- 会话列表 -->
    <aside class="convs">
      <el-button class="new-btn" type="primary" plain @click="newConversation">
        <el-icon><Plus /></el-icon>&nbsp;新会话
      </el-button>
      <div class="conv-list">
        <div
          v-for="c in convs"
          :key="c.id"
          class="conv-item"
          :class="{ active: c.id === activeId }"
          @click="selectConversation(c.id)"
        >
          <span class="conv-title">{{ c.title }}</span>
          <span class="conv-time">{{ formatTime(c.updated_at) }}</span>
          <el-icon class="conv-del" @click.stop="removeConversation(c.id)"><Close /></el-icon>
        </div>
      </div>
    </aside>

    <!-- 消息区 -->
    <section class="main">
      <div ref="listEl" class="messages">
        <div v-if="!messages.length" class="empty">
          <p class="empty-title">记录你吃了什么、做了什么运动</p>
          <p class="empty-sub">直接描述，或从下面的问题开始：</p>
          <div class="examples">
            <button v-for="ex in EXAMPLES" :key="ex" class="chip" @click="send(ex)">{{ ex }}</button>
          </div>
        </div>

        <template v-for="m in messages" :key="m.key">
          <ChatMessage :message="m" />
          <HitlCard
            v-if="m.interrupt"
            :payload="m.interrupt"
            @confirm="confirmDiet"
            @cancel="cancelDiet"
          />
        </template>
      </div>

      <!-- 输入区 -->
      <div class="composer-wrap">
        <div v-if="imageUrl" class="preview">
          <img :src="imageUrl" alt="待发送图片" />
          <button class="preview-rm" title="移除图片" @click="clearImage">
            <el-icon><Close /></el-icon>
          </button>
        </div>

        <div class="composer">
          <input ref="fileInput" type="file" accept="image/*" hidden @change="onFileChange" />
          <el-button class="img-btn" :disabled="busy" :loading="uploading" @click="pickImage">
            <el-icon><Picture /></el-icon>
          </el-button>
          <el-input
            v-model="input"
            type="textarea"
            :rows="1"
            :autosize="{ minRows: 1, maxRows: 4 }"
            resize="none"
            placeholder="描述你的饮食或运动，如「午餐吃了一碗牛肉面」"
            :disabled="busy"
            @keydown.enter.exact.prevent="send()"
          />
          <el-button
            type="primary"
            :disabled="!canSend"
            :loading="streaming"
            @click="send()"
          >
            发送
          </el-button>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.chat {
  display: flex;
  height: 100%;
  gap: 20px;
}
.convs {
  width: 220px;
  flex: none;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.new-btn {
  width: 100%;
}
.conv-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.conv-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 12px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  color: var(--ink-2);
}
.conv-item:hover {
  background: var(--bg);
}
.conv-item.active {
  background: var(--primary-soft);
  color: var(--primary-deep);
}
.conv-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  font-weight: 500;
}
.conv-time {
  font-size: 11px;
  color: var(--ink-3);
}
.conv-del {
  opacity: 0;
  font-size: 14px;
  color: var(--ink-3);
  transition: opacity 0.12s;
}
.conv-item:hover .conv-del {
  opacity: 1;
}
.conv-del:hover {
  color: var(--warn);
}

.main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.messages {
  flex: 1;
  overflow-y: auto;
  padding: 8px 4px 20px;
}
.empty {
  max-width: 460px;
  margin: 10vh auto 0;
  text-align: center;
}
.empty-title {
  font-size: 17px;
  font-weight: 600;
  margin: 0 0 4px;
}
.empty-sub {
  color: var(--ink-3);
  font-size: 13px;
  margin: 0 0 16px;
}
.examples {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
}
.chip {
  padding: 7px 14px;
  border: 1px solid var(--line-strong);
  border-radius: 999px;
  background: var(--bg-elevated);
  color: var(--ink-2);
  font-size: 13px;
  cursor: pointer;
  font-family: var(--font);
  transition: border-color 0.12s, color 0.12s;
}
.chip:hover {
  border-color: var(--primary);
  color: var(--primary-deep);
}

.composer-wrap {
  border-top: 1px solid var(--line);
  padding-top: 12px;
}
.preview {
  position: relative;
  display: inline-block;
  margin-bottom: 10px;
}
.preview img {
  display: block;
  max-width: 160px;
  max-height: 120px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--line-strong);
  object-fit: cover;
}
.preview-rm {
  position: absolute;
  top: -8px;
  right: -8px;
  width: 20px;
  height: 20px;
  display: grid;
  place-items: center;
  border: 1px solid var(--line-strong);
  border-radius: 50%;
  background: var(--bg-elevated);
  color: var(--ink-3);
  cursor: pointer;
  font-size: 12px;
}
.preview-rm:hover {
  color: var(--warn);
}
.composer {
  display: flex;
  gap: 10px;
  align-items: flex-end;
}
.composer :deep(.el-textarea__inner) {
  border-radius: var(--radius-sm);
}
.composer .el-button {
  height: 38px;
}
.img-btn {
  width: 38px;
  flex: none;
}
</style>
