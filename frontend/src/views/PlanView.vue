<script setup lang="ts">
// 计划后端尚未落地：本页只承接用户到 plan_agent 对话，避免伪造已保存的计划数据。
import { useRouter } from 'vue-router'
import { Food, MagicStick, Timer } from '@element-plus/icons-vue'

const router = useRouter()

function startPlanConversation() {
  router.push({
    path: '/chat',
    query: { prompt: '帮我生成一份包含饮食和运动安排的计划。' },
  })
}
</script>

<template>
  <div class="plan-page">
    <header class="page-head">
      <div>
        <span class="eyebrow">Personal plan</span>
        <h1>把目标拆成每天能做到的事</h1>
        <p>饮食和运动会在同一份计划里协同安排，并依据你的档案和记录持续调整。</p>
      </div>
    </header>

    <section class="plan-hero panel">
      <div class="hero-copy">
        <span class="hero-kicker">由 NutriLens Agent 生成</span>
        <h2>从一次对话开始，建立属于你的健康节奏。</h2>
        <p>告诉助手你的目标、饮食偏好和运动频率。确认后，计划会在这里展示每日餐次与训练安排。</p>
        <el-button type="primary" @click="startPlanConversation">
          <el-icon><MagicStick /></el-icon>&nbsp;生成饮食与运动计划
        </el-button>
      </div>
      <div class="plan-preview" aria-hidden="true">
        <div class="preview-head"><span>计划草案</span><b>待生成</b></div>
        <div class="preview-row">
          <span class="row-icon meal"><el-icon><Food /></el-icon></span>
          <span><b>饮食安排</b><small>热量、宏量与餐次建议</small></span>
        </div>
        <div class="preview-row">
          <span class="row-icon exercise"><el-icon><Timer /></el-icon></span>
          <span><b>运动安排</b><small>频率、项目与训练时长</small></span>
        </div>
      </div>
    </section>

    <section class="how-it-works">
      <article class="step panel">
        <span class="step-number">01</span>
        <h2>说明你的目标</h2>
        <p>例如减脂周期、训练频率、食物偏好或不适合的食材。</p>
      </article>
      <article class="step panel">
        <span class="step-number">02</span>
        <h2>确认计划草案</h2>
        <p>先看每日目标、餐次与训练安排，再决定是否启用。</p>
      </article>
      <article class="step panel">
        <span class="step-number">03</span>
        <h2>跟随记录调整</h2>
        <p>真实的饮食与运动记录会让后续建议更贴合你的节奏。</p>
      </article>
    </section>
  </div>
</template>

<style scoped>
.eyebrow {
  display: block;
  margin-bottom: 6px;
  color: var(--primary-deep);
  font-size: 10px;
  font-weight: 750;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}
.page-head h1 {
  font-size: 28px;
}
.plan-hero {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(260px, 0.9fr);
  gap: 24px;
  margin-top: 26px;
  padding: 28px;
  background: var(--primary-soft);
  border-color: var(--primary-line);
}
.hero-kicker {
  color: var(--primary-deep);
  font-size: 11px;
  font-weight: 650;
}
.hero-copy h2 {
  max-width: 560px;
  margin: 10px 0 0;
  font-size: 26px;
  line-height: 1.25;
  letter-spacing: 0;
}
.hero-copy p {
  max-width: 560px;
  margin: 10px 0 20px;
  color: var(--ink-2);
  font-size: 13px;
}
.plan-preview {
  align-self: center;
  padding: 16px;
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
  font-size: 11px;
}
.preview-head b {
  color: var(--primary-deep);
}
.preview-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 13px 0 0;
}
.row-icon {
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border-radius: 7px;
}
.row-icon.meal {
  color: var(--primary-deep);
  background: var(--primary-soft);
}
.row-icon.exercise {
  color: var(--info);
  background: #eef6ff;
}
.preview-row b,
.preview-row small {
  display: block;
}
.preview-row b {
  font-size: 12px;
}
.preview-row small {
  margin-top: 2px;
  color: var(--ink-3);
  font-size: 10px;
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
  font-size: 12px;
  font-weight: 700;
}
.step h2 {
  margin: 10px 0 0;
  font-size: 15px;
}
.step p {
  margin: 6px 0 0;
  color: var(--ink-3);
  font-size: 12px;
}
@media (max-width: 840px) {
  .plan-hero,
  .how-it-works {
    grid-template-columns: 1fr;
  }
}
</style>
