// 后端 API 契约对应的 TS 类型（字段名与 backend/app/schemas 一一对应）。

// ---- 认证 ----
export interface TokenResponse {
  token: string
  username: string
}
export interface UserMe {
  id: number
  username: string
}

// ---- 档案 ----
export type Gender = 'male' | 'female'
export type ActivityLevel = 'sedentary' | 'light' | 'moderate' | 'active'
export type Goal = 'lose' | 'maintain' | 'gain'

export interface UserProfile {
  gender: Gender | null
  age: number | null
  height_cm: number | null
  weight_kg: number | null
  activity_level: ActivityLevel | null
  goal: Goal | null
  goal_note: string
  bmr: number | null
  tdee: number | null
  calorie_target: number | null
}

// ---- 饮食 / 运动记录 ----
export interface DietItem {
  id: number
  food_name: string
  grams: number
  calories: number
  protein: number
  fat: number
  carbs: number
  confidence: 'db_exact' | 'db_prefix' | 'llm_estimate'
}

export interface DietRecord {
  id: number
  meal_type: string
  source: string
  record_date: string
  totals: { calories: number; protein: number; fat: number; carbs: number }
  items: DietItem[]
}

export interface ExerciseRecord {
  id: number
  exercise_type: string
  duration_minutes: number
  met: number
  calories_burned: number
  record_date: string
}

// ---- 看板 ----
export interface DailySummary {
  date: string
  intake: number
  burned: number
  net: number
  calorie_target: number | null
  remaining: number | null
  macros: { protein: number; fat: number; carbs: number }
}

export interface TrendPoint {
  date: string
  intake: number
  burned: number
  calorie_target: number | null
}
export interface TrendSeries {
  days: number
  series: TrendPoint[]
}

// ---- 会话 / 消息 ----
export interface Conversation {
  id: string
  title: string
  updated_at: string
}

export interface Message {
  id: number
  role: 'user' | 'assistant'
  content: string
  image_url: string | null
  agent_name: string | null
  tool_trace: string | null // JSON 字符串，前端解析
  created_at: string
}

// 工具轨迹单条（tool_trace 解析后的元素）
export interface ToolTraceEntry {
  name: string
  args: Record<string, unknown>
  result: string
  reason?: string
}

// ---- HITL 确认卡片（diet_agent 的 create_diet_record 中断载荷）----
export interface DietDraftItem {
  food_name: string
  grams: number
  calories: number
  protein: number
  fat: number
  carbs: number
  confidence: string
}
export interface DietConfirmPayload {
  type: 'diet_confirm'
  meal_type: string
  record_date: string
  items: DietDraftItem[]
}

// ---- 对话页本地消息（历史 + 流式实时合一的 UI 结构）----
export interface ChatMessage {
  key: string
  role: 'user' | 'assistant'
  content: string
  imageUrl: string | null
  agentName: string | null
  toolTrace: ToolTraceEntry[]
  streaming: boolean
  interrupt: DietConfirmPayload | null
}

// ---- SSE 事件（后端 chat.py 分帧协议）----
export type SseEvent =
  | { type: 'token'; content: string }
  | { type: 'agent_trace'; to: string; task: string }
  | { type: 'tool_calls'; entry: ToolTraceEntry }
  | { type: 'interrupt'; payload: DietConfirmPayload }
  | { type: 'done'; interrupted: boolean; agent_name?: string; persisted?: boolean; content?: string }
  | { type: 'error'; message: string }
