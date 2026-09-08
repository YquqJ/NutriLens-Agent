// 领域枚举 → 中文展示文案（agent / 餐次 / 工具 / 置信度）。集中在单一来源，避免散落各处。

export const AGENT_LABELS: Record<string, string> = {
  diet_agent: '饮食',
  exercise_agent: '运动',
  plan_agent: '计划',
  qa_agent: '问答',
  supervisor: '调度',
}

export const MEAL_LABELS: Record<string, string> = {
  breakfast: '早餐',
  lunch: '午餐',
  dinner: '晚餐',
  snack: '加餐',
}

export const TOOL_LABELS: Record<string, string> = {
  search_food: '检索食物',
  analyze_food_image: '识别图片',
  create_diet_record: '写入饮食记录',
  get_diet_records: '查询饮食记录',
  delete_diet_record: '删除饮食记录',
  create_exercise_record: '写入运动记录',
  get_exercise_records: '查询运动记录',
  delete_exercise_record: '删除运动记录',
  retrieve_knowledge: '检索知识',
  self_check: '检索自检',
}

export const CONFIDENCE_LABELS: Record<string, string> = {
  db_exact: '库内精确',
  db_prefix: '库内匹配',
  db_fuzzy: '库内模糊',
  llm_estimate: '估算值',
}

export function agentLabel(name: string | null): string {
  return (name && AGENT_LABELS[name]) || name || ''
}
export function toolLabel(name: string): string {
  return TOOL_LABELS[name] || name
}
export function mealLabel(meal: string): string {
  return MEAL_LABELS[meal] || meal
}
export function confidenceLabel(c: string): string {
  return CONFIDENCE_LABELS[c] || c
}
