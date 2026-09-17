<script setup lang="ts">
// 对话页：会话列表 + SSE 流式渲染 + HITL 确认卡片。
// 流式协议：POST /chat 返回 SSE 分帧（token/agent_trace/tool_calls/interrupt/done），
// fetch + ReadableStream 逐帧解析；interrupt 挂起后经 /chat/resume 恢复。
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getToken } from '@/api/http'
import { listConversations, createConversation, getMessages, deleteConversation } from '@/api/conversations'
import { uploadImage } from '@/api/uploads'
import { getErrorMessage } from '@/utils/error'
import { saveCurrentPlan } from '@/api/plans'
import ChatMessage from '@/components/ChatMessage.vue'
import CitationDrawer from '@/components/CitationDrawer.vue'
import HitlCard from '@/components/HitlCard.vue'
import type {
  ChatMessage as ChatMsg,
  Citation,
  Conversation,
  DietDraftItem,
  Message,
  SseEvent,
  ToolTraceEntry,
} from '@/types'

const convs = ref<Conversation[]>([])
const route = useRoute()
const router = useRouter()
const activeId = ref<string | null>(null)
const messages = ref<ChatMsg[]>([])
const input = ref('')
const streaming = ref(false)
const pendingMsg = ref<ChatMsg | null>(null)
const listEl = ref<HTMLElement | null>(null)
const imageUrl = ref<string | null>(null)
const uploading = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const citationDrawerVisible = ref(false)
const drawerCitations = ref<Citation[]>([])
const activeCitationIndex = ref<number | null>(null)

const busy = computed(() => streaming.value || !!pendingMsg.value)
const canSend = computed(() => !busy.value && (!!input.value.trim() || !!imageUrl.value))

const EXAMPLES = ['帮我记录午餐：一碗牛肉面', '我今天吃了多少卡路里？', '减脂期每天吃多少蛋白质？']

// ---- 工具 ----
let seq = 0
const uid = () => `t${Date.now()}_${seq++}`

function toChatMessage(m: Message): ChatMsg {
  let toolTrace: ToolTraceEntry[] = []
  let citations: Citation[] = []
  if (m.tool_trace) {
    try {
      toolTrace = JSON.parse(m.tool_trace)
    } catch {
      toolTrace = []
    }
  }
  if (m.citations) {
    try {
      citations = JSON.parse(m.citations)
    } catch {
      citations = []
    }
  }
  return {
    key: `m${m.id}`,
    role: m.role,
    content: m.content,
    imageUrl: m.image_url,
    agentName: m.agent_name,
    toolTrace,
    citations,
    streaming: false,
    interrupt: null,
    createdAt: m.created_at,
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
async function streamRequest(
  url: string,
  body: unknown,
  live: ChatMsg,
  timing?: { firstToken: number },
) {
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
        if (timing && timing.firstToken === 0) timing.firstToken = Date.now()
        live.content += e.content
        scrollBottom()
        break
      case 'agent_trace':
        // supervisor 收尾时 next_agent=FINISH，不是真实 agent，不更新徽章
        if (e.to && e.to !== 'FINISH') live.agentName = e.to
        break
      case 'tool_calls':
        live.toolTrace.push(e.entry)
        break
      case 'citations':
        live.citations = e.items
        break
      case 'interrupt':
        live.interrupt = e.payload
        live.streaming = false
        pendingMsg.value = live
        break
      case 'done':
        live.streaming = false
        // interrupt 结束帧也会携带图片识别摘要，用它覆盖暂存/空白正文，
        // 避免确认卡片出现时助手气泡仍显示原始结构化 JSON。
        if (e.content) live.content = e.content
        if (!e.interrupted) {
          live.agentName = e.agent_name || live.agentName
          // 用后端权威终稿替换流式累积的 token 文本：token 流可能混入
          // react agent 的工具间叙述（"现在我将…"），终稿才是干净的最终回答
          if (e.citations) live.citations = e.citations
        }
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
          // 事件类型在 SSE 的 event: 行里，data JSON 本身不含 type 字段；
          // tool_calls 的 data 直接就是 ToolTraceEntry，需包成 entry
          const parsed = JSON.parse(data)
          handle(
            event === 'tool_calls'
              ? { type: event, entry: parsed }
              : ({ ...parsed, type: event } as SseEvent),
          )
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

function openCitation(citation: Citation, message: ChatMsg) {
  drawerCitations.value = message.citations
  activeCitationIndex.value = citation.index
  citationDrawerVisible.value = true
}

async function send(text?: string) {
  const typed = (text ?? input.value).trim()
  const img = imageUrl.value
  if (busy.value || !activeId.value) return
  if (!typed && !img) return
  const content = typed || '识别这张图'
  input.value = ''
  imageUrl.value = null
  const now = new Date().toISOString()
  messages.value.push({
    key: uid(), role: 'user', content, imageUrl: img,
    agentName: null, toolTrace: [], citations: [], streaming: false, interrupt: null,
    createdAt: now,
  })
  // reactive 包装：SSE 事件流中会持续 mutate 此对象（token 追加/轨迹 push），
  // 普通对象 push 进 reactive 数组后，对原始引用的 mutate 不触发重渲染
  const live = reactive<ChatMsg>({
    key: uid(), role: 'assistant', content: '', imageUrl: null,
    agentName: null, toolTrace: [], citations: [], streaming: true, interrupt: null,
    createdAt: now,
  })
  messages.value.push(live)
  streaming.value = true
  scrollBottom()
  const start = Date.now()
  const timing = { firstToken: 0 }
  try {
    await streamRequest(
      `/api/conversations/${activeId.value}/chat`,
      { content, image_url: img },
      live,
      timing,
    )
  } catch (e) {
    live.content += `\n[请求失败] ${getErrorMessage(e)}`
    live.streaming = false
  } finally {
    streaming.value = false
    scrollBottom()
  }
  if (timing.firstToken > 0) {
    live.thinkingMs = timing.firstToken - start
    if (!live.interrupt) live.answerMs = Date.now() - timing.firstToken
  }
  if (!live.interrupt) await refreshList()
}

async function confirmDiet(items: DietDraftItem[], allergyAcknowledged: boolean) {
  const live = pendingMsg.value
  if (!live || !activeId.value) return
  live.interrupt = null
  live.streaming = true
  pendingMsg.value = null
  streaming.value = true
  try {
    await streamRequest(
      `/api/conversations/${activeId.value}/chat/resume`,
      { value: { items, allergy_acknowledged: allergyAcknowledged } },
      live,
    )
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

async function syncPlan(message: ChatMsg) {
  if (!message.content) return
  try {
    await saveCurrentPlan({
      content: message.content,
      conversation_id: activeId.value,
    })
    ElMessage.success('计划已同步到饮食计划')
  } catch (error) {
    ElMessage.error(getErrorMessage(error, '计划同步失败'))
  }
}

function applyPlanPrompt() {
  const prompt = typeof route.query.prompt === 'string' ? route.query.prompt.trim() : ''
  if (!prompt || !activeId.value) return
  input.value = prompt
  router.replace({ query: {} })
}

onMounted(async () => {
  await loadConversations()
  applyPlanPrompt()
})

watch(
  () => route.query.prompt,
  () => applyPlanPrompt(),
)
</script>

<template>
  <div class="chat-page">
    <header class="page-head chat-topbar">
      <div><span class="page-kicker">AI 健康助手</span><h1>智能健康对话</h1></div>
      <span class="chat-status">饮食、运动与计划都可以在这里完成</span>
    </header>

    <div class="page-body">
      <!-- 会话列表 -->
      <aside class="convs">
        <el-button class="new-btn" type="primary" @click="newConversation">
          <el-icon><Plus /></el-icon>&nbsp;新会话
        </el-button>
        <div class="conv-list">
          <div v-if="convs.length" class="conv-label">最近会话</div>
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
          <div class="col">
            <div v-if="!messages.length" class="empty">
              <p class="empty-title">记录你吃了什么、做了什么运动</p>
              <p class="empty-sub">直接描述，或从下面的问题开始：</p>
              <div class="examples">
                <button v-for="ex in EXAMPLES" :key="ex" class="chip" @click="send(ex)">{{ ex }}</button>
              </div>
            </div>

            <template v-for="m in messages" :key="m.key">
              <ChatMessage :message="m" @citation-click="openCitation($event, m)" @sync-plan="syncPlan" />
              <div v-if="m.interrupt" class="hitl-slot">
                <HitlCard
                  :payload="m.interrupt"
                  @confirm="confirmDiet"
                  @cancel="cancelDiet"
                />
              </div>
            </template>
          </div>
        </div>

        <!-- 输入区 -->
        <div class="composer-wrap">
          <div class="col">
            <div v-if="imageUrl" class="preview">
              <img :src="imageUrl" alt="待发送图片" />
              <button class="preview-rm" title="移除图片" @click="clearImage">
                <el-icon><Close /></el-icon>
              </button>
            </div>

            <div class="composer">
              <input ref="fileInput" type="file" accept="image/*" hidden @change="onFileChange" />
              <el-button
                class="img-btn"
                :disabled="busy"
                :loading="uploading"
                title="上传食物照片"
                @click="pickImage"
              >
                <el-icon style="font-size: 18px;"><Picture /></el-icon>
              </el-button>
              <el-input
                v-model="input"
                type="textarea"
                class="composer-input"
                :rows="1"
                :autosize="{ minRows: 1, maxRows: 5 }"
                resize="none"
                placeholder="描述你的饮食或运动，如「午餐吃了一碗牛肉面 / 今天跑了30分钟」"
                :disabled="busy"
                @keydown.enter.exact.prevent="send()"
              />
              <el-button
                type="primary"
                class="send-btn"
                circle
                :disabled="!canSend"
                :loading="streaming"
                title="发送"
                @click="send()"
              >
                <el-icon v-if="!streaming"><Promotion /></el-icon>
              </el-button>
            </div>
          </div>
        </div>
      </section>
    </div>

    <CitationDrawer
      v-model:visible="citationDrawerVisible"
      :citations="drawerCitations"
      :active-index="activeCitationIndex"
    />
  </div>
</template>

<style scoped>
.chat-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  gap: 0;
  background: var(--bg-elevated);
}
.page-body {
  flex: 1;
  display: flex;
  width: 100%;
  overflow: hidden;
}
.convs {
  width: 224px;
  flex: none;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  border-right: 1px solid var(--border);
}
.new-btn {
  width: 100%;
  height: 36px;
  border-radius: 10px;
  font-weight: 600;
}
.conv-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.conv-label {
  padding: 6px 10px 4px;
  font-size: 11px;
  letter-spacing: 0.04em;
  color: var(--muted-2);
}
.conv-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 10px;
  border-radius: 10px;
  cursor: pointer;
  color: var(--muted);
  transition: background 0.12s, color 0.12s;
}
.conv-item:hover {
  background: var(--surface-hover);
  color: var(--text);
}
.conv-item.active {
  background: var(--primary-soft);
  color: var(--primary-deep);
}
.conv-item.active .conv-title {
  font-weight: 600;
}
.conv-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13.5px;
  font-weight: 500;
}
.conv-time {
  flex: none;
  font-size: 11px;
  color: var(--muted-2);
}
.conv-item.active .conv-time {
  color: var(--primary-deep);
  opacity: 0.7;
}
.conv-del {
  flex: none;
  width: 16px;
  opacity: 0;
  font-size: 14px;
  color: var(--muted-2);
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
  padding: 24px 8px 24px;
  background: linear-gradient(180deg, var(--bg-elevated), var(--surface));
}
/* 居中阅读列：消息与输入框共用同一宽度，避免超长行与两侧空旷 */
.col {
  max-width: 800px;
  margin: 0 auto;
  width: 100%;
}
.empty {
  max-width: 520px;
  margin: 12vh auto 0;
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
  padding: 12px 0 12px;
}
/* HITL 卡片对齐到助手内容列（头像 32 + 间距 12），并限制宽度 */
.hitl-slot {
  margin: -12px 0 24px 44px;
  max-width: 640px;
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

/* 单行输入框：上传按钮（左） + textarea（占满） + 发送按钮（右），聚焦不变色 */
.composer {
  display: flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--border);
  border-radius: 16px;
  background: var(--bg-elevated);
  padding: 8px 10px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
}
.composer-input {
  flex: 1;
  min-width: 0;
}
.composer :deep(.el-textarea__inner) {
  border: none;
  box-shadow: none;
  background: transparent;
  padding: 7px 4px;
  font-size: 14px;
  line-height: 1.6;
}
/* 聚焦不显示边框/高亮（覆盖全局 .el-textarea__inner:focus 的绿色 inset ring） */
.composer :deep(.el-textarea__inner:focus) {
  box-shadow: none !important;
  border: none !important;
}
.img-btn {
  flex: none;
  border: none;
  background: transparent;
  box-shadow: none;
  padding: 8px;
  height: auto;
  color: var(--muted);
  border-radius: 8px;
}
.img-btn:hover {
  color: var(--text);
  background: var(--surface-hover);
}
.hint {
  margin-top: 6px;
  padding: 0 4px;
  font-size: 12px;
  color: var(--muted-2);
}
.send-btn {
  flex: none;
  width: 34px;
  height: 34px;
  border-radius: 50%;
  --el-button-bg-color: var(--primary);
  --el-button-border-color: var(--primary);
  --el-button-text-color: #fff;
  --el-button-hover-bg-color: var(--primary-deep);
  --el-button-hover-border-color: var(--primary-deep);
  --el-button-active-bg-color: #0f8a3f;
  --el-button-active-border-color: #0f8a3f;
  --el-button-disabled-bg-color: var(--border);
  --el-button-disabled-border-color: var(--border);
  --el-button-disabled-text-color: var(--muted-2);
}

.chat-topbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin: 0; padding: 22px 24px 20px; border-bottom: 1px solid var(--line); background: var(--bg-elevated); }.chat-topbar h1 { margin: 0; font-size: 32px; line-height: 1.22; }.chat-topbar .page-kicker { margin-bottom: 7px; }.chat-status { padding: 7px 11px; border: 1px solid var(--primary-line); border-radius: 999px; background: var(--primary-soft); color: var(--primary-deep); font-size: 13px; }
.convs { padding: 16px 12px; background: #fff; }.new-btn { height: 40px; font-size: 14px; }.conv-label { padding-top: 12px; font-size: 12px; }.conv-item { padding: 11px 10px; }.conv-title { font-size: 14px; }.messages { padding: 28px 24px; background: var(--surface); }.col { max-width: 80%; }.empty { margin-top: 10vh; padding: 30px; border: 1px solid var(--primary-line); border-radius: var(--radius); background: var(--bg-elevated); box-shadow: 0 8px 26px rgba(20, 79, 45, .04); }.empty-title { color: var(--ink); font-size: 21px; }.empty-sub { font-size: 14px; }.chip { padding: 8px 14px; font-size: 13px; }.composer-wrap { padding: 14px 24px; background: var(--bg-elevated); }.composer { border-radius: 12px; padding: 8px 10px; box-shadow: 0 5px 18px rgba(20, 79, 45, .06); }

@media (max-width: 760px) {
  .chat-page {
    height: calc(100dvh - 57px);
    min-height: 560px;
  }
  .convs {
    display: none;
  }
  .messages {
    padding: 18px 0;
  }
  .chat-topbar { padding: 14px 0; background: transparent; }.chat-topbar h1 { font-size: 27px; }.chat-status { display: none; }
  .col {
    max-width: none;
  }
  .empty {
    margin: 8vh 0 0;
    padding: 24px 14px;
  }
  .composer-wrap {
    padding: 10px 0;
  }
  .composer {
    border-radius: 12px;
    padding: 6px 8px;
  }
  .hitl-slot {
    margin-left: 0;
  }
}
</style>
