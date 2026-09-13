<script setup lang="ts">
// HITL 确认卡片：饮食记录写库前的人工确认（可编辑克数）。
// 编辑克数时按比例线性重算营养值（营养值 = 每克 × 克数，原条目已含绝对营养值）。
import { reactive, computed, ref } from 'vue'
import { confidenceLabel, mealLabel } from '@/utils/labels'
import type { DietConfirmPayload, DietDraftItem } from '@/types'

const props = defineProps<{ payload: DietConfirmPayload }>()
const emit = defineEmits<{
  (e: 'confirm', items: DietDraftItem[], allergyAcknowledged: boolean): void
  (e: 'cancel'): void
}>()

// 本地可编辑副本：记录原始克数（用于比例重算）
interface EditableItem extends DietDraftItem {
  _origGrams: number
}
const items = reactive<EditableItem[]>(
  props.payload.items.map((it) => ({ ...it, _origGrams: it.grams })),
)

const totalCalories = computed(() =>
  items.reduce((s, it) => s + it.calories * (it.grams / it._origGrams), 0),
)
const allergyRisks = computed(() => props.payload.allergy_risks ?? [])
const allergyAcknowledged = ref(false)

function confidenceType(c: string) {
  return c === 'llm_estimate' ? 'warning' : c === 'db_exact' ? 'success' : 'info'
}

function confirm() {
  if (allergyRisks.value.length > 0 && !allergyAcknowledged.value) return
  emit(
    'confirm',
    items.map((it) => {
      const k = it.grams / it._origGrams
      const scale = (v: number) => Math.round(v * k * 10) / 10
      return {
        food_name: it.food_name,
        grams: it.grams,
        calories: scale(it.calories),
        protein: scale(it.protein),
        fat: scale(it.fat),
        carbs: scale(it.carbs),
        confidence: it.confidence,
      }
    }),
    allergyAcknowledged.value,
  )
}
</script>

<template>
  <div class="hitl">
    <div class="hitl-head">
      <span class="title">确认饮食记录</span>
      <span class="meta">{{ mealLabel(payload.meal_type) }} · {{ payload.record_date }}</span>
    </div>

    <table class="items">
      <thead>
        <tr>
          <th>食物</th>
          <th>克数</th>
          <th class="r">热量</th>
          <th>来源</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(it, i) in items" :key="i">
          <td class="name">{{ it.food_name }}</td>
          <td class="grams">
            <el-input-number
              v-model="it.grams"
              :min="1"
              :max="3000"
              :precision="0"
              size="small"
              controls-position="right"
              style="width: 110px"
            />
            <span class="unit">克</span>
          </td>
          <td class="r num">{{ Math.round(it.calories * (it.grams / it._origGrams)) }}</td>
          <td style="display: flex;">
            <el-tag :type="confidenceType(it.confidence)" size="small" effect="plain">
              {{ confidenceLabel(it.confidence) }}
            </el-tag>
          </td>
        </tr>
      </tbody>
    </table>

    <div v-if="allergyRisks.length" class="allergy-warning">
      <div class="warning-title">⚠️ 检测到档案中的过敏风险</div>
      <div v-for="risk in allergyRisks" :key="risk.allergen" class="warning-item">
        {{ risk.message }}
      </div>
      <el-checkbox v-model="allergyAcknowledged" class="warning-check">
        我已知悉上述风险，仍要记录已发生的饮食
      </el-checkbox>
      <div v-if="payload.confirmation_error" class="warning-error">
        {{ payload.confirmation_error }}
      </div>
    </div>

    <div class="foot">
      <div class="sum">
        合计 <span class="num strong">{{ Math.round(totalCalories) }}</span> 千卡
      </div>
      <div class="actions">
        <el-button size="small" @click="emit('cancel')">取消</el-button>
        <el-button
          size="small"
          type="primary"
          :disabled="allergyRisks.length > 0 && !allergyAcknowledged"
          @click="confirm"
        >确认写入</el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.hitl {
  margin-top: 10px;
  border: 1px solid var(--line-strong);
  border-left: 3px solid var(--primary);
  border-radius: var(--radius-sm);
  background: var(--bg-elevated);
  overflow: hidden;
}
.hitl-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--line);
}
.title {
  font-size: 14px;
  font-weight: 600;
}
.meta {
  font-size: 12px;
  color: var(--ink-3);
}
.items {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.items th {
  text-align: left;
  font-weight: 500;
  color: var(--ink-3);
  padding: 8px 14px;
  border-bottom: 1px solid var(--line);
}
.items th.r,
.items td.r {
  text-align: right;
}
.items td {
  padding: 8px 14px;
  border-bottom: 1px solid var(--line);
}
.items tr:last-child td {
  border-bottom: none;
}
.name {
  font-weight: 500;
}
.grams {
  white-space: nowrap;
}
.unit {
  margin-left: 4px;
  color: var(--ink-3);
}
.foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  background: var(--bg);
}
.sum {
  font-size: 13px;
  color: var(--ink-2);
}
.strong {
  font-weight: 700;
  color: var(--primary-deep);
}
.actions {
  display: flex;
  gap: 8px;
}
.allergy-warning {
  margin: 10px 14px 0;
  padding: 10px 12px;
  border: 1px solid #f3c46b;
  border-radius: var(--radius-sm);
  background: #fff8e6;
  color: #7a4d00;
  font-size: 12px;
  line-height: 1.6;
}
.warning-title {
  font-weight: 600;
  margin-bottom: 2px;
}
.warning-item {
  margin-top: 2px;
}
.warning-check {
  margin-top: 6px;
  color: #7a4d00;
}
.warning-error {
  margin-top: 4px;
  color: #c45656;
}
</style>
