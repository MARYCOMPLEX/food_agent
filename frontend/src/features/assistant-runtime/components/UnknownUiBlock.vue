<script setup lang="ts">
import { computed } from 'vue'
import type { AssistantUiBlock } from '../types'

const props = defineProps<{ block: AssistantUiBlock, reason?: 'unknown' | 'invalid' | 'missing' }>()

const label = computed(() => {
  if (props.reason === 'missing') return '内容暂时不可用'
  if (props.reason === 'invalid') return '内容格式暂时无法渲染'
  return '暂不支持的内容类型'
})

const preview = computed(() => {
  try {
    const text = JSON.stringify(props.block.data)
    return text.length > 180 ? `${text.slice(0, 177)}...` : text
  }
  catch {
    return '无法读取内容预览'
  }
})
</script>

<template>
  <div class="assistant-unknown-block" role="status">
    <div class="assistant-unknown-block__icon" aria-hidden="true">?</div>
    <div class="assistant-unknown-block__body">
      <div class="assistant-unknown-block__title">
        {{ label }}
      </div>
      <div class="assistant-unknown-block__renderer">
        {{ block.renderer }} · v{{ block.schemaVersion }}
      </div>
      <code class="assistant-unknown-block__preview">{{ preview }}</code>
    </div>
  </div>
</template>

<style scoped>
.assistant-unknown-block {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  padding: 14px;
  border: 1px dashed var(--color-border-default, #cbd2dd);
  border-radius: 12px;
  background: var(--color-bg-muted, #f5f7fa);
  color: var(--color-text-secondary-exact, #4b5565);
}

.assistant-unknown-block__icon {
  display: grid;
  width: 26px;
  height: 26px;
  flex: 0 0 26px;
  place-items: center;
  border: 1px solid var(--color-border-default, #cbd2dd);
  border-radius: 50%;
  color: var(--color-text-muted, #667085);
  font-weight: 700;
}

.assistant-unknown-block__body {
  min-width: 0;
}

.assistant-unknown-block__title {
  font-size: 13px;
  font-weight: 700;
  color: var(--color-text-primary, #101828);
}

.assistant-unknown-block__renderer {
  margin-top: 2px;
  font-size: 11px;
  color: var(--color-text-muted, #667085);
}

.assistant-unknown-block__preview {
  display: block;
  margin-top: 8px;
  overflow: hidden;
  font-size: 11px;
  line-height: 1.45;
  white-space: nowrap;
  text-overflow: ellipsis;
}
</style>
