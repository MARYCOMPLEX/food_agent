<script setup lang="ts">
import { computed } from 'vue'
import type { AssistantUiBlock } from '../types'

const props = defineProps<{ block: AssistantUiBlock, data: unknown }>()

type RecordValue = Record<string, unknown>

function asRecord(value: unknown): RecordValue | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as RecordValue
    : null
}

function asArray(value: unknown): unknown[] {
  if (Array.isArray(value)) return value
  const record = asRecord(value)
  return record && Array.isArray(record.items) ? record.items : []
}

function text(value: unknown, fallback = ''): string {
  return typeof value === 'string' && value.trim() ? value : fallback
}

function numberText(value: unknown): string {
  return typeof value === 'number' ? String(value) : ''
}

function listText(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
}

const family = computed(() => {
  const renderer = props.block.renderer
  if (renderer.includes('evidence')) return 'evidence'
  if (renderer.includes('controversy')) return 'controversy'
  if (renderer.includes('profile')) return 'profile'
  if (renderer.includes('recommendation')) return 'recommendation'
  if (renderer.includes('gap')) return 'gap'
  if (renderer.includes('plan')) return 'plan'
  if (renderer.includes('coverage')) return 'coverage'
  return 'summary'
})

const payload = computed(() => asRecord(props.data) ?? {})
const items = computed(() => asArray(props.data))
const title = computed(() => text(payload.value.title, {
  evidence: '评论证据',
  controversy: '争议与分歧',
  profile: '店铺档案',
  recommendation: '值得去看',
  gap: '数据缺口',
  plan: '研究计划',
  coverage: '研究覆盖度',
  summary: '研究摘要',
}[family.value]))

function itemText(item: unknown, key: string, fallback = ''): string {
  return text(asRecord(item)?.[key], fallback)
}

function itemList(item: unknown, key: string): string[] {
  return listText(asRecord(item)?.[key])
}

function sideItems(item: unknown): unknown[] {
  const sides = asRecord(item)?.sides
  return Array.isArray(sides) ? sides : []
}

function coveragePercent(item: unknown): string {
  const ratio = asRecord(item)?.ratio
  return typeof ratio === 'number' ? `${Math.round(ratio * 100)}%` : ''
}

function statusClass(value: unknown): string {
  const status = text(value).toLowerCase()
  if (['resolved', 'succeeded', 'complete', 'sufficient'].includes(status)) return 'is-positive'
  if (['failed', 'error', 'exhausted', 'blocked'].includes(status)) return 'is-negative'
  if (['partial', 'partially_resolved', 'warning', 'running'].includes(status)) return 'is-warning'
  return 'is-neutral'
}

function statusLabel(value: unknown): string {
  const labels: Record<string, string> = {
    resolved: '已解决',
    partially_resolved: '部分解决',
    unresolved: '待核验',
    complete: '已补齐',
    partial: '部分完成',
    failed: '失败',
    exhausted: '已耗尽',
    running: '进行中',
    warning: '注意',
    sufficient: '充足',
  }
  const status = text(value)
  return labels[status] ?? (status || '记录')
}
</script>

<template>
  <section class="research-block" :data-family="family">
    <header class="research-block__header">
      <div>
        <span class="research-block__eyebrow">RESEARCH SIGNAL</span>
        <h3>{{ title }}</h3>
      </div>
      <span class="research-block__count" v-if="items.length">{{ items.length }} 条</span>
    </header>

    <p v-if="family === 'summary' && text(payload.text, text(payload.summary))" class="research-block__summary">
      {{ text(payload.text, text(payload.summary)) }}
    </p>

    <div v-else-if="family === 'evidence'" class="research-block__list">
      <article v-for="(item, index) in items" :key="itemText(item, 'evidenceId', `evidence-${index}`)" class="research-item">
        <div class="research-item__meta">
          <span class="research-item__source">{{ itemText(item, 'source', '未知来源') }}</span>
          <span v-if="itemText(item, 'stance')" class="research-status" :class="statusClass(itemText(item, 'stance'))">{{ itemText(item, 'stance') }}</span>
        </div>
        <p class="research-item__title">{{ itemText(item, 'title', itemText(item, 'excerpt', '未提供评论摘要')) }}</p>
        <p v-if="itemText(item, 'title') && itemText(item, 'excerpt')" class="research-item__excerpt">{{ itemText(item, 'excerpt') }}</p>
        <div class="research-item__refs">
          <span v-if="itemText(item, 'noteRef')">笔记 {{ itemText(item, 'noteRef') }}</span>
          <span v-if="itemText(item, 'commentRef')">评论 {{ itemText(item, 'commentRef') }}</span>
          <span v-if="numberText(asRecord(item)?.confidence)">置信度 {{ numberText(asRecord(item)?.confidence) }}</span>
        </div>
      </article>
    </div>

    <div v-else-if="family === 'controversy'" class="research-block__list">
      <article v-for="(item, index) in items" :key="itemText(item, 'controversyId', `controversy-${index}`)" class="research-item">
        <div class="research-item__meta">
          <strong>{{ itemText(item, 'topic', '未命名争议') }}</strong>
          <span class="research-status" :class="statusClass(asRecord(item)?.status)">{{ statusLabel(asRecord(item)?.status) }}</span>
        </div>
        <p v-if="itemText(item, 'summary')" class="research-item__excerpt">{{ itemText(item, 'summary') }}</p>
        <div v-if="sideItems(item).length" class="research-sides">
          <div v-for="(side, sideIndex) in sideItems(item)" :key="sideIndex" class="research-side">
            <span>{{ itemText(side, 'label', `立场 ${sideIndex + 1}`) }}</span>
            <small>{{ itemText(side, 'summary') }}</small>
          </div>
        </div>
        <p v-if="itemText(item, 'resolution')" class="research-item__resolution">结论：{{ itemText(item, 'resolution') }}</p>
      </article>
    </div>

    <div v-else-if="family === 'profile'" class="research-block__list research-block__list--profiles">
      <article v-for="(item, index) in items" :key="itemText(item, 'profileId', `profile-${index}`)" class="research-item research-profile">
        <div class="research-item__meta">
          <strong>{{ itemText(item, 'name', '未命名店铺') }}</strong>
          <span class="research-status" :class="statusClass(asRecord(item)?.status)">{{ statusLabel(asRecord(item)?.status) }}</span>
        </div>
        <p v-if="itemText(item, 'address')" class="research-item__excerpt">{{ itemText(item, 'address') }}</p>
        <div class="research-profile__facts">
          <span v-if="numberText(asRecord(item)?.rating)">评分 {{ numberText(asRecord(item)?.rating) }}</span>
          <span v-if="numberText(asRecord(item)?.averagePrice)">人均 ¥{{ numberText(asRecord(item)?.averagePrice) }}</span>
          <span v-if="numberText(asRecord(item)?.reviewCount)">{{ numberText(asRecord(item)?.reviewCount) }} 条评价</span>
        </div>
        <div v-if="itemList(item, 'recommendedDishes').length" class="research-tags">
          <span v-for="dish in itemList(item, 'recommendedDishes')" :key="dish">{{ dish }}</span>
        </div>
      </article>
    </div>

    <div v-else-if="family === 'recommendation'" class="research-block__list">
      <article v-for="(item, index) in items" :key="itemText(item, 'recommendationId', `recommendation-${index}`)" class="research-item">
        <div class="research-item__meta">
          <strong>{{ itemText(item, 'title', '未命名候选') }}</strong>
          <span class="research-status" :class="statusClass(asRecord(item)?.status)">{{ statusLabel(asRecord(item)?.status) }}</span>
        </div>
        <p v-if="itemText(item, 'summary')" class="research-item__excerpt">{{ itemText(item, 'summary') }}</p>
        <div class="research-item__refs">
          <span v-if="typeof asRecord(item)?.rank === 'number'">排名 {{ asRecord(item)?.rank }}</span>
          <span v-if="typeof asRecord(item)?.confidence === 'number'">置信度 {{ Math.round(Number(asRecord(item)?.confidence) * 100) }}%</span>
          <span v-if="itemList(item, 'evidenceRefs').length">{{ itemList(item, 'evidenceRefs').length }} 条评论证据</span>
        </div>
        <div v-if="itemList(item, 'highlights').length || itemList(item, 'warnings').length" class="research-tags">
          <span v-for="highlight in itemList(item, 'highlights').slice(0, 3)" :key="`h-${highlight}`">{{ highlight }}</span>
          <span v-for="warning in itemList(item, 'warnings').slice(0, 2)" :key="`w-${warning}`" class="is-warning">{{ warning }}</span>
        </div>
      </article>
    </div>

    <div v-else-if="family === 'gap'" class="research-block__list">
      <article v-for="(item, index) in items" :key="itemText(item, 'gapId', `gap-${index}`)" class="research-item research-gap">
        <div class="research-item__meta">
          <strong>{{ itemText(item, 'operation', '数据采集') }}</strong>
          <span class="research-status" :class="statusClass(asRecord(item)?.severity)">{{ statusLabel(asRecord(item)?.severity) }}</span>
        </div>
        <p class="research-item__excerpt">{{ itemText(item, 'message', '部分数据暂未获得') }}</p>
        <div class="research-item__refs">
          <span>{{ itemText(item, 'source', '未知来源') }}</span>
          <span v-if="asRecord(item)?.retryable === true">可重试</span>
          <span v-if="itemText(item, 'status')">{{ statusLabel(asRecord(item)?.status) }}</span>
        </div>
      </article>
    </div>

    <div v-else-if="family === 'plan'" class="research-plan">
      <div v-for="(item, index) in items" :key="itemText(item, 'stepId', `step-${index}`)" class="research-plan__step">
        <span class="research-plan__index">{{ index + 1 }}</span>
        <div>
          <strong>{{ itemText(item, 'label', '研究步骤') }}</strong>
          <small v-if="itemText(item, 'detail')">{{ itemText(item, 'detail') }}</small>
        </div>
        <span class="research-status" :class="statusClass(asRecord(item)?.status)">{{ statusLabel(asRecord(item)?.status) }}</span>
      </div>
    </div>

    <div v-else-if="family === 'coverage'" class="research-coverage">
      <div v-for="(item, index) in items" :key="itemText(item, 'dimension', `dimension-${index}`)" class="research-coverage__row">
        <span>{{ itemText(item, 'dimension', '覆盖维度') }}</span>
        <strong v-if="coveragePercent(item)">{{ coveragePercent(item) }}</strong>
        <span v-else class="research-status" :class="statusClass(asRecord(item)?.status)">{{ statusLabel(asRecord(item)?.status) }}</span>
      </div>
    </div>

    <p v-else class="research-block__summary">该研究区块暂无可显示内容。</p>
  </section>
</template>

<style scoped>
.research-block {
  overflow: hidden;
  border: 1px solid var(--color-border-muted, #e4e8ee);
  border-radius: 14px;
  background: var(--color-bg-surface, #fff);
}

.research-block__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 16px 12px;
  border-bottom: 1px solid var(--color-border-muted, #e4e8ee);
}

.research-block__eyebrow {
  display: block;
  margin-bottom: 4px;
  color: var(--color-text-muted, #667085);
  font-size: 9px;
  font-weight: 800;
  letter-spacing: .12em;
}

.research-block h3 {
  margin: 0;
  color: var(--color-text-primary, #101828);
  font-size: 14px;
}

.research-block__count {
  flex: 0 0 auto;
  color: var(--color-text-muted, #667085);
  font-size: 11px;
}

.research-block__summary {
  margin: 0;
  padding: 16px;
  color: var(--color-text-secondary-exact, #475467);
  font-size: 13px;
  line-height: 1.65;
}

.research-block__list {
  display: grid;
  gap: 1px;
  background: var(--color-border-muted, #e4e8ee);
}

.research-item {
  padding: 13px 16px;
  background: var(--color-bg-surface, #fff);
}

.research-item__meta,
.research-profile__facts,
.research-item__refs,
.research-coverage__row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.research-item__meta {
  justify-content: space-between;
  gap: 10px;
  color: var(--color-text-primary, #101828);
  font-size: 12px;
}

.research-item__source,
.research-item__refs,
.research-profile__facts,
.research-side small,
.research-plan small {
  color: var(--color-text-muted, #667085);
  font-size: 11px;
}

.research-item__title {
  margin: 8px 0 0;
  color: var(--color-text-primary, #101828);
  font-size: 13px;
  font-weight: 650;
  line-height: 1.5;
}

.research-item__excerpt,
.research-item__resolution {
  margin: 5px 0 0;
  color: var(--color-text-secondary-exact, #475467);
  font-size: 12px;
  line-height: 1.55;
}

.research-item__refs {
  margin-top: 9px;
}

.research-item__refs span {
  padding: 3px 7px;
  border-radius: 5px;
  background: var(--color-bg-muted, #f5f7fa);
}

.research-status {
  display: inline-flex;
  align-items: center;
  min-height: 20px;
  padding: 2px 7px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 700;
}

.research-status.is-positive { color: #057a55; background: #ecfdf5; }
.research-status.is-negative { color: #b42318; background: #fef3f2; }
.research-status.is-warning { color: #b54708; background: #fffaeb; }
.research-status.is-neutral { color: #475467; background: #f2f4f7; }

.research-sides {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 10px;
}

.research-side {
  display: grid;
  gap: 3px;
  padding: 9px;
  border-left: 2px solid var(--color-brand-400, #6a60e8);
  background: var(--color-bg-muted, #f5f7fa);
}

.research-side span { color: var(--color-text-primary, #101828); font-size: 11px; font-weight: 700; }

.research-profile__facts {
  margin-top: 9px;
}

.research-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.research-tags span {
  padding: 4px 7px;
  border-radius: 5px;
  color: var(--color-brand-700, #2a1faf);
  background: var(--color-brand-50, #edf0ff);
  font-size: 11px;
}

.research-plan,
.research-coverage {
  display: grid;
  gap: 1px;
  background: var(--color-border-muted, #e4e8ee);
}

.research-plan__step,
.research-coverage__row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 16px;
  background: var(--color-bg-surface, #fff);
}

.research-plan__step > div {
  display: grid;
  flex: 1;
  gap: 2px;
}

.research-plan__index {
  display: grid;
  width: 22px;
  height: 22px;
  flex: 0 0 22px;
  place-items: center;
  border-radius: 50%;
  color: var(--color-brand-700, #2a1faf);
  background: var(--color-brand-50, #edf0ff);
  font-size: 10px;
  font-weight: 800;
}

.research-coverage__row span:first-child { flex: 1; color: var(--color-text-secondary-exact, #475467); font-size: 12px; }
.research-coverage__row strong { color: var(--color-text-primary, #101828); font-size: 13px; }

@media (max-width: 520px) {
  .research-sides { grid-template-columns: 1fr; }
}
</style>
