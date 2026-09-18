<script setup lang="ts">
// 计划页读取后端当前计划；新计划由 plan_agent 完成回复时自动归档。
import { onMounted, ref } from 'vue'
import { Calendar, ChatDotRound, Food, MagicStick, Timer } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { getCurrentPlan } from '@/api/plans'
import MarkdownContent from '@/components/MarkdownContent.vue'
import { getErrorMessage } from '@/utils/error'
import type { HealthPlan } from '@/types'

const router = useRouter()
const loading = ref(false)
const plan = ref<HealthPlan | null>(null)

function startPlanConversation() {
  router.push({
    path: '/chat',
    query: { prompt: '帮我生成一份包含饮食和运动安排的计划。' },
  })
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit',
  }).format(new Date(value))
}

async function load() {
  loading.value = true
  try {
    plan.value = await getCurrentPlan()
  } catch (error) {
    ElMessage.error(getErrorMessage(error, '计划读取失败'))
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="plan-page page-wrapper">
    <header class="page-head plan-head">
      <div>
        <span class="page-kicker">我的健康计划</span>
        <h1>{{ plan ? '这是你正在执行的健康计划' : '把目标拆成每天能做到的事' }}</h1>
        <p>{{ plan ? '饮食与运动安排来自 AI 对话，并已同步为当前计划。' : '饮食和运动会在同一份计划里协同安排，并依据你的档案和记录持续调整。' }}</p>
      </div>
      <el-button v-if="plan" type="primary" @click="startPlanConversation"><el-icon><MagicStick /></el-icon>&nbsp;生成新计划</el-button>
    </header>

    <template v-if="plan">
      <section class="active-plan panel">
        <header class="active-head">
          <div class="plan-badge"><el-icon><Calendar /></el-icon><span>当前计划</span></div>
          <span class="updated-at">更新于 {{ formatTime(plan.updated_at) }}</span>
        </header>
        <div class="plan-title-row"><h2>{{ plan.title }}</h2><span class="plan-state">进行中</span></div>
        <MarkdownContent class="plan-content" :content="plan.content" />
        <footer class="plan-footer"><span>计划包含饮食与运动安排；下一份计划会自动替换当前版本。</span><router-link to="/chat"><el-icon><ChatDotRound /></el-icon>继续与 AI 调整</router-link></footer>
      </section>
    </template>

    <template v-else>
      <section class="plan-hero panel">
        <div class="hero-copy">
          <span class="hero-kicker">由 NutriLens Agent 生成</span>
          <h2>从一次对话开始，建立属于你的健康节奏。</h2>
          <p>告诉助手你的目标、饮食偏好和运动频率。生成完成后，饮食与运动建议会自动同步到这里。</p>
          <el-button type="primary" @click="startPlanConversation"><el-icon><MagicStick /></el-icon>&nbsp;生成饮食与运动计划</el-button>
        </div>
        <div class="plan-preview" aria-hidden="true">
          <div class="preview-head"><span>计划草案</span><b>等待生成</b></div>
          <div class="preview-row"><span class="row-icon meal"><el-icon><Food /></el-icon></span><span><b>饮食安排</b><small>热量、宏量与餐次建议</small></span></div>
          <div class="preview-row"><span class="row-icon exercise"><el-icon><Timer /></el-icon></span><span><b>运动安排</b><small>频率、项目与训练时长</small></span></div>
        </div>
      </section>
      <section class="how-it-works">
        <article class="step panel"><span class="step-number">01</span><h2>说明你的目标</h2><p>例如减脂周期、训练频率、食物偏好或不适合的食材。</p></article>
        <article class="step panel"><span class="step-number">02</span><h2>确认计划草案</h2><p>在对话中补充细节，AI 会给出饮食和运动的完整安排。</p></article>
        <article class="step panel"><span class="step-number">03</span><h2>自动同步</h2><p>计划生成完成后，这里会展示最新版本，后续可继续在对话中调整。</p></article>
      </section>
    </template>
  </div>
</template>

<style scoped lang="scss">
.plan-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow-y: hidden;
}
.plan-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.plan-head h1 {
  font-size: 32px;
}
.eyebrow {
  display: block;
  margin-bottom: 7px;
  color: var(--primary-deep);
  font-size: 11px;
  font-weight: 750;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}
.plan-hero {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(260px, 0.9fr);
  gap: 28px;
  margin-top: 26px;
  padding: 30px;
  background: var(--primary-soft);
  border-color: var(--primary-line);
}
.hero-kicker {
  color: var(--primary-deep);
  font-size: 13px;
  font-weight: 650;
}
.hero-copy h2 {
  max-width: 560px;
  margin: 10px 0 0;
  font-size: 29px;
  line-height: 1.25;
  letter-spacing: 0;
}
.hero-copy p {
  max-width: 560px;
  margin: 12px 0 22px;
  color: var(--ink-2);
  font-size: 14px;
}
.plan-preview {
  align-self: center;
  padding: 18px;
  background: var(--bg-elevated);
  border: 1px solid var(--primary-line);
  border-radius: var(--radius);
}
.preview-head {
  display: flex;
  justify-content: space-between;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--line);
  color: var(--ink-3);
  font-size: 12px;
}
.preview-head b {
  color: var(--primary-deep);
}
.preview-row {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 15px 0 0;
}
.row-icon,
.focus-icon {
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  border-radius: 7px;
}
.row-icon.meal,
.focus-icon.meal {
  color: var(--primary-deep);
  background: var(--primary-soft);
}
.row-icon.exercise,
.focus-icon.exercise {
  color: var(--info);
  background: #eef6ff;
}
.preview-row b,
.preview-row small {
  display: block;
}
.preview-row b {
  font-size: 14px;
}
.preview-row small {
  margin-top: 2px;
  color: var(--ink-3);
  font-size: 12px;
}
.active-plan {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 16px 28px;
  margin-top: 12px;
  border-top: 3px solid var(--primary);
  overflow: hidden;
}
.active-head,
.plan-title-row,
.plan-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}
.plan-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--primary-deep);
  font-size: 12px;
  font-weight: 750;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.updated-at {
  color: var(--ink-3);
  font-size: 12px;
}
.plan-title-row {
  margin-top: 14px;
  align-items: flex-start;
}
.plan-title-row h2 {
  margin: 0;
  font-size: 25px;
  line-height: 1.25;
}
.plan-state {
  padding: 4px 8px;
  border-radius: 999px;
  background: var(--primary-soft);
  color: var(--primary-deep);
  font-size: 12px;
  font-weight: 700;
}
.plan-content {
  flex: 1;
  margin-top: 20px;
  padding: 22px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: #fbfefb;
  color: var(--ink);
  font-size: 15px;
  line-height: 1.9;
  word-break: break-word;
  overflow-y: auto;
}
.plan-footer {
  margin-top: 18px;
  padding-top: 16px;
  border-top: 1px solid var(--line);
  color: var(--ink-3);
  font-size: 13px;
}
.plan-footer a {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  flex: none;
  font-weight: 650;
}
.plan-focus {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-top: 18px;
}
.focus-card {
  display: flex;
  align-items: flex-start;
  gap: 13px;
  padding: 20px;
}
.focus-card h2 {
  margin: 0;
  font-size: 16px;
}
.focus-card p {
  margin: 5px 0 0;
  color: var(--ink-3);
  font-size: 13px;
}
.how-it-works {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
  margin-top: 20px;
}
.step {
  padding: 20px;
}
.step-number {
  color: var(--primary-deep);
  font-family: var(--font-num);
  font-size: 13px;
  font-weight: 700;
}
.step h2 {
  margin: 10px 0 0;
  font-size: 17px;
}
.step p {
  margin: 6px 0 0;
  color: var(--ink-3);
  font-size: 13px;
}
@media (max-width: 840px) {
  .plan-hero,
  .how-it-works,
  .plan-focus {
    grid-template-columns: 1fr;
  }
  .plan-head h1 {
    font-size: 27px;
  }
}
.plan-head > .el-button {
  flex: none;
}
@media (max-width: 600px) {
  .plan-head {
    display: block;
  }
  .plan-head > .el-button {
    margin-top: 14px;
  }
  .plan-hero,
  .active-plan {
    padding: 20px 16px;
  }
  .hero-copy h2 {
    font-size: 25px;
  }
  .active-head,
  .plan-title-row,
  .plan-footer {
    align-items: flex-start;
    flex-direction: column;
  }
  .plan-content {
    padding: 16px;
    font-size: 14px;
  }
  .plan-focus {
    grid-template-columns: 1fr;
  }
}
</style>
