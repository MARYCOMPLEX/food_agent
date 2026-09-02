<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import AdaptiveContainer from '../../shared/ui/AdaptiveContainer.vue'
import ExploreForm from './components/ExploreForm.vue'
import PromptChips from './components/PromptChips.vue'
import { researchApi } from './api/researchApi'
import type { PromptTemplate, UnifiedSearchRequest } from './types'

const router = useRouter()
const formRef = ref<any>(null)
const loading = ref(false)
const errorMsg = ref('')

const promptTemplates: PromptTemplate[] = [
  {
    title: '成都本地人常去的市井老火锅',
    query: '成都本地人常去、排队合理、锅底醇厚不燥辣的市井老火锅',
    city: '成都',
    category: '火锅',
  },
  {
    title: '上海静安区高性价比Bistro',
    query: '上海静安寺附近适合约会、氛围好、人均200左右的西餐Bistro',
    city: '上海',
    category: '西餐',
  },
  {
    title: '广州地道早茶老字号',
    query: '广州老城区本地街坊去得最多的早茶酒楼，虾饺和红米肠必吃',
    city: '广州',
    category: '早茶',
  },
  {
    title: '重庆防空洞深处地道烤鱼',
    query: '重庆本地特色防空洞烤鱼/江湖菜，重麻重辣、烟火气十足',
    city: '重庆',
    category: '江湖菜',
  },
  {
    title: '杭州西湖边适合家庭聚餐杭帮菜',
    query: '杭州西湖景区附近不宰客、环境清幽、适合老人小孩的传统杭帮菜',
    city: '杭州',
    category: '杭帮菜',
  },
]

function handleSelectPrompt(t: PromptTemplate) {
  if (formRef.value) {
    formRef.value.setQueryAndCity(t.query, t.city)
  }
}

async function handleStartResearch(req: UnifiedSearchRequest) {
  loading.value = true
  errorMsg.value = ''
  try {
    const admission = await researchApi.startSearch(req)
    if (admission?.sessionId) {
      router.push(`/app/sessions/${admission.sessionId}`)
    }
  }
  catch (err: any) {
    errorMsg.value = err?.message || '发起研究失败，请检查服务连接'
  }
  finally {
    loading.value = false
  }
}
</script>

<template>
  <AdaptiveContainer max-width="lg" class="space-y-6">
    <!-- Hero Header -->
    <div class="text-center space-y-2 py-4 md:py-8">
      <div class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-[var(--color-brand-50)] text-[var(--color-brand-700)] text-xs font-semibold">
        <span>🍲</span>
        <span>基于小红书真实笔记 & 评论多维研判</span>
      </div>
      <h1 class="text-2xl md:text-4xl font-extrabold text-[var(--color-text-primary)] tracking-tight">
        探索真正地道、好吃的特色餐厅
      </h1>
      <p class="text-xs md:text-sm text-[var(--color-text-secondary)] max-w-lg mx-auto">
        过滤广告软文与虚假网红店，多轮智能 Agent 为您交叉核验本地人口碑、招牌必点与避雷建议。
      </p>
    </div>

    <!-- Error Banner -->
    <div
      v-if="errorMsg"
      class="p-3.5 rounded-xl bg-red-50 border border-red-200 text-red-700 text-xs md:text-sm flex items-center justify-between"
    >
      <div class="flex items-center gap-2">
        <span>⚠️</span>
        <span>{{ errorMsg }}</span>
      </div>
      <button class="text-xs underline font-medium cursor-pointer" @click="errorMsg = ''">
        关闭
      </button>
    </div>

    <!-- Research Main Form -->
    <div class="bg-[var(--color-bg-surface)] p-4 md:p-6 rounded-2xl border border-[var(--color-border)] shadow-md">
      <ExploreForm ref="formRef" :loading="loading" @submit="handleStartResearch" />
    </div>

    <!-- Prompt Chips -->
    <div class="p-4 rounded-xl bg-[var(--color-bg-subtle)] border border-[var(--color-border)]">
      <PromptChips :templates="promptTemplates" @select="handleSelectPrompt" />
    </div>
  </AdaptiveContainer>
</template>
