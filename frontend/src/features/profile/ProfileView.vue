<script setup lang="ts">
import { onMounted, ref } from 'vue'
import AdaptiveContainer from '../../shared/ui/AdaptiveContainer.vue'
import AdaptiveTabs from '../../shared/ui/AdaptiveTabs.vue'
import AdaptiveButton from '../../shared/ui/AdaptiveButton.vue'
import AdaptiveCard from '../../shared/ui/AdaptiveCard.vue'
import { profileApi } from './api/profileApi'
import type {
  FaqItem,
  FeedbackRequest,
  UserNotifications,
  UserProfile,
} from './types'

const activeTab = ref('profile')

const tabs = [
  { key: 'profile', label: '个人资料', icon: '👤' },
  { key: 'preferences', label: '口味偏好', icon: '🍲' },
  { key: 'memory', label: '推断记忆', icon: '🧠' },
  { key: 'notifications', label: '通知与主题', icon: '🔔' },
  { key: 'help', label: '帮助与反馈', icon: '❓' },
]

const profile = ref<UserProfile>({
  id: '',
  name: '美食探索家',
  email: 'foodie@anyfast.local',
  location: '成都',
  stats: { saved_count: 0, search_count: 0, visited_count: 0 },
})

const tastesList = ['地道老字号', '麻辣鲜香', '清淡少油', '夜市烧烤', '适合聚餐', '一人食']
const selectedTastes = ref<string[]>(['地道老字号', '麻辣鲜香'])
const defaultCity = ref('成都')
const dietaryRestrictions = ref('无特殊忌口')

// Inferred Memory
const inferredMemories = ref([
  { id: 'mem_1', category: '口味倾向', value: '偏好传统市井火锅，重视锅底牛油浓郁度', confidence: 0.92 },
  { id: 'mem_2', category: '价格敏感', value: '倾向于人均 60-120 元的高性价比街头老店', confidence: 0.85 },
  { id: 'mem_3', category: '避雷特征', value: '反感重度营销与排队超 1 小时的网红门店', confidence: 0.96 },
])

// Notifications
const notifs = ref<UserNotifications>({
  push: true,
  email: false,
  newRecommendations: true,
  weeklyDigest: false,
})
const theme = ref('system')

// FAQs & Feedback
const faqs = ref<FaqItem[]>([])
const feedback = ref<FeedbackRequest>({
  type: 'feature',
  content: '',
  contact: '',
})
const feedbackSuccess = ref(false)
const saving = ref(false)

async function loadProfile() {
  try {
    const data = await profileApi.getProfile()
    if (data) {
      profile.value = { ...profile.value, ...data }
    }
  }
  catch {}
  try {
    const faqList = await profileApi.getFaqs()
    if (faqList)
      faqs.value = faqList
  }
  catch {}
}

async function saveProfile() {
  saving.value = true
  try {
    await profileApi.updateProfile({
      name: profile.value.name,
      email: profile.value.email,
      location: profile.value.location,
    })
  }
  catch (err) {
    console.error('Save profile failed', err)
  }
  finally {
    saving.value = false
  }
}

async function savePreferences() {
  saving.value = true
  try {
    await profileApi.updatePreferences({
      tastes: selectedTastes.value,
      defaultCity: defaultCity.value,
      dietaryRestrictions: dietaryRestrictions.value,
    })
  }
  catch (err) {
    console.error('Save prefs failed', err)
  }
  finally {
    saving.value = false
  }
}

async function saveNotifications() {
  saving.value = true
  try {
    await profileApi.updateNotifications({
      ...notifs.value,
      theme: theme.value,
    })
  }
  catch (err) {
    console.error('Save notifications failed', err)
  }
  finally {
    saving.value = false
  }
}

function removeMemory(id: string) {
  inferredMemories.value = inferredMemories.value.filter(m => m.id !== id)
}

async function handleSendFeedback() {
  if (!feedback.value.content.trim())
    return
  saving.value = true
  try {
    await profileApi.submitFeedback(feedback.value)
    feedbackSuccess.value = true
    feedback.value.content = ''
  }
  catch (err) {
    console.error('Feedback failed', err)
  }
  finally {
    saving.value = false
  }
}

function toggleTaste(t: string) {
  if (selectedTastes.value.includes(t)) {
    selectedTastes.value = selectedTastes.value.filter(x => x !== t)
  }
  else {
    selectedTastes.value.push(t)
  }
}

onMounted(() => {
  loadProfile()
})
</script>

<template>
  <AdaptiveContainer max-width="lg" class="space-y-6">
    <!-- Header with Stats -->
    <div class="bg-gradient-to-r from-[var(--color-brand-500)] to-[var(--color-brand-700)] text-white p-6 rounded-2xl shadow-md">
      <div class="flex items-center gap-4">
        <div class="w-16 h-16 rounded-full bg-white/20 flex items-center justify-center text-3xl font-bold border-2 border-white/40">
          🍜
        </div>
        <div>
          <h1 class="text-xl md:text-2xl font-bold">
            {{ profile.name || '美食探索家' }}
          </h1>
          <div class="text-xs text-white/80 mt-0.5">
            常驻城市: {{ profile.location || '成都' }} · AnyFast Pro 会员
          </div>
        </div>
      </div>

      <!-- Quick Stats -->
      <div class="grid grid-cols-3 gap-2 mt-6 pt-4 border-t border-white/20 text-center">
        <div>
          <div class="text-xs text-white/75">
            收藏餐厅
          </div>
          <div class="text-lg md:text-xl font-bold font-mono mt-0.5">
            {{ profile.stats?.saved_count || 12 }}
          </div>
        </div>
        <div>
          <div class="text-xs text-white/75">
            研判探索会话
          </div>
          <div class="text-lg md:text-xl font-bold font-mono mt-0.5">
            {{ profile.stats?.search_count || 48 }}
          </div>
        </div>
        <div>
          <div class="text-xs text-white/75">
            推断记忆项
          </div>
          <div class="text-lg md:text-xl font-bold font-mono mt-0.5">
            {{ inferredMemories.length }}
          </div>
        </div>
      </div>
    </div>

    <!-- Tabs Navigation -->
    <AdaptiveTabs v-model="activeTab" :tabs="tabs" />

    <!-- Tab 1: Profile Info -->
    <AdaptiveCard v-if="activeTab === 'profile'" padding="md" class="space-y-4">
      <h3 class="text-base font-bold text-[var(--color-text-primary)]">
        基本资料
      </h3>

      <div class="space-y-3 text-sm">
        <div>
          <label class="block text-xs font-semibold text-[var(--color-text-secondary)] mb-1">昵称</label>
          <input
            v-model="profile.name"
            type="text"
            class="w-full px-3 py-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-surface)] text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-brand-500)]"
          >
        </div>

        <div>
          <label class="block text-xs font-semibold text-[var(--color-text-secondary)] mb-1">电子邮箱</label>
          <input
            v-model="profile.email"
            type="email"
            class="w-full px-3 py-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-surface)] text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-brand-500)]"
          >
        </div>

        <div>
          <label class="block text-xs font-semibold text-[var(--color-text-secondary)] mb-1">常住/常用地点</label>
          <input
            v-model="profile.location"
            type="text"
            placeholder="例如: 成都市锦江区"
            class="w-full px-3 py-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-surface)] text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-brand-500)]"
          >
        </div>
      </div>

      <div class="pt-2 flex justify-end">
        <AdaptiveButton variant="primary" size="sm" :loading="saving" @click="saveProfile">
          <span>保存资料修改</span>
        </AdaptiveButton>
      </div>
    </AdaptiveCard>

    <!-- Tab 2: Preferences -->
    <AdaptiveCard v-else-if="activeTab === 'preferences'" padding="md" class="space-y-4">
      <h3 class="text-base font-bold text-[var(--color-text-primary)]">
        个性化美食偏好
      </h3>

      <div class="space-y-4 text-sm">
        <div>
          <label class="block text-xs font-semibold text-[var(--color-text-secondary)] mb-2">常选口味标签</label>
          <div class="flex flex-wrap gap-2">
            <button
              v-for="t in tastesList"
              :key="t"
              class="px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors cursor-pointer"
              :class="selectedTastes.includes(t) ? 'bg-[var(--color-brand-500)] text-white border-[var(--color-brand-500)] font-semibold' : 'bg-[var(--color-bg-subtle)] text-[var(--color-text-secondary)] border-[var(--color-border)]'"
              @click="toggleTaste(t)"
            >
              {{ t }}
            </button>
          </div>
        </div>

        <div>
          <label class="block text-xs font-semibold text-[var(--color-text-secondary)] mb-1">默认优先探索城市</label>
          <input
            v-model="defaultCity"
            type="text"
            class="w-full px-3 py-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-surface)] text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-brand-500)]"
          >
        </div>

        <div>
          <label class="block text-xs font-semibold text-[var(--color-text-secondary)] mb-1">忌口与特殊要求</label>
          <input
            v-model="dietaryRestrictions"
            type="text"
            placeholder="例如: 不吃香菜、少放味精、不要折耳根"
            class="w-full px-3 py-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-surface)] text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-brand-500)]"
          >
        </div>
      </div>

      <div class="pt-2 flex justify-end">
        <AdaptiveButton variant="primary" size="sm" :loading="saving" @click="savePreferences">
          <span>更新偏好设置</span>
        </AdaptiveButton>
      </div>
    </AdaptiveCard>

    <!-- Tab 3: Inferred Memory -->
    <AdaptiveCard v-else-if="activeTab === 'memory'" padding="md" class="space-y-4">
      <div class="flex items-center justify-between">
        <div>
          <h3 class="text-base font-bold text-[var(--color-text-primary)]">
            Agent 智能推断记忆
          </h3>
          <p class="text-xs text-[var(--color-text-secondary)] mt-0.5">
            系统从您的历史追问和收藏行为中归纳出的隐含偏好，可在研判时自动生效
          </p>
        </div>
      </div>

      <div class="space-y-2.5">
        <div
          v-for="mem in inferredMemories"
          :key="mem.id"
          class="p-3 bg-[var(--color-bg-subtle)] rounded-xl border border-[var(--color-border)] flex items-start justify-between gap-3"
        >
          <div class="space-y-1">
            <div class="flex items-center gap-2">
              <span class="text-xs font-bold px-2 py-0.5 rounded bg-[var(--color-brand-100)] text-[var(--color-brand-700)]">
                {{ mem.category }}
              </span>
              <span class="text-[11px] text-[var(--color-text-tertiary)]">
                置信度: {{ Math.round(mem.confidence * 100) }}%
              </span>
            </div>
            <p class="text-xs md:text-sm text-[var(--color-text-primary)] font-medium">
              {{ mem.value }}
            </p>
          </div>

          <button
            class="text-xs text-red-500 hover:text-red-700 p-1 cursor-pointer shrink-0"
            title="删除该条记忆"
            @click="removeMemory(mem.id)"
          >
            删除
          </button>
        </div>
      </div>
    </AdaptiveCard>

    <!-- Tab 4: Notifications & Theme -->
    <AdaptiveCard v-else-if="activeTab === 'notifications'" padding="md" class="space-y-4">
      <h3 class="text-base font-bold text-[var(--color-text-primary)]">
        通知与显示偏好
      </h3>

      <div class="space-y-3 text-sm">
        <label class="flex items-center justify-between p-2 rounded-lg hover:bg-[var(--color-neutral-100)] cursor-pointer">
          <div>
            <div class="font-medium text-[var(--color-text-primary)]">系统推送通知</div>
            <div class="text-xs text-[var(--color-text-tertiary)]">研判完成或后台增量刷新就绪时提醒</div>
          </div>
          <input v-model="notifs.push" type="checkbox" class="w-4 h-4 rounded text-[var(--color-brand-500)]">
        </label>

        <label class="flex items-center justify-between p-2 rounded-lg hover:bg-[var(--color-neutral-100)] cursor-pointer">
          <div>
            <div class="font-medium text-[var(--color-text-primary)]">每周本地美食精选速递</div>
            <div class="text-xs text-[var(--color-text-tertiary)]">每周五推送常驻城市最新高分小众老店</div>
          </div>
          <input v-model="notifs.weeklyDigest" type="checkbox" class="w-4 h-4 rounded text-[var(--color-brand-500)]">
        </label>

        <div class="pt-3 border-t border-[var(--color-border)]">
          <label class="block text-xs font-semibold text-[var(--color-text-secondary)] mb-1">界面主题风格</label>
          <select
            v-model="theme"
            class="w-full px-3 py-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-surface)] text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-brand-500)]"
          >
            <option value="system">
              跟随系统 (System Default)
            </option>
            <option value="light">
              明亮模式 (Cobalt Clean Light)
            </option>
            <option value="dark">
              深色夜间模式 (Dark)
            </option>
          </select>
        </div>
      </div>

      <div class="pt-2 flex justify-end">
        <AdaptiveButton variant="primary" size="sm" :loading="saving" @click="saveNotifications">
          <span>保存设置</span>
        </AdaptiveButton>
      </div>
    </AdaptiveCard>

    <!-- Tab 5: Help & Feedback -->
    <div v-else-if="activeTab === 'help'" class="space-y-4">
      <!-- FAQs -->
      <AdaptiveCard padding="md" class="space-y-3">
        <h3 class="text-base font-bold text-[var(--color-text-primary)]">
          常见问题 FAQ
        </h3>
        <div class="space-y-3">
          <div
            v-for="faq in faqs"
            :key="faq.id"
            class="p-3 bg-[var(--color-bg-subtle)] rounded-xl border border-[var(--color-border)] space-y-1"
          >
            <div class="font-bold text-xs md:text-sm text-[var(--color-text-primary)] flex items-center gap-1.5">
              <span>❓</span>
              <span>{{ faq.question }}</span>
            </div>
            <p class="text-xs text-[var(--color-text-secondary)] leading-relaxed pl-5">
              {{ faq.answer }}
            </p>
          </div>
        </div>
      </AdaptiveCard>

      <!-- Feedback Form -->
      <AdaptiveCard padding="md" class="space-y-3">
        <h3 class="text-base font-bold text-[var(--color-text-primary)]">
          提交反馈与建议
        </h3>

        <div v-if="feedbackSuccess" class="p-3 bg-emerald-50 text-emerald-800 rounded-xl text-xs font-medium">
          ✓ 感谢您的反馈！我们的工程师与研判专家团队会尽快核实处理。
        </div>

        <div class="space-y-3 text-sm">
          <div>
            <label class="block text-xs font-semibold text-[var(--color-text-secondary)] mb-1">反馈类型</label>
            <select
              v-model="feedback.type"
              class="w-full px-3 py-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-surface)] text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-brand-500)]"
            >
              <option value="feature">
                ✨ 功能建议 / 需求提出
              </option>
              <option value="bug">
                🐛 问题排查 / 研判结果不准
              </option>
              <option value="other">
                💬 其他反馈
              </option>
            </select>
          </div>

          <div>
            <label class="block text-xs font-semibold text-[var(--color-text-secondary)] mb-1">详细描述</label>
            <textarea
              v-model="feedback.content"
              rows="3"
              placeholder="请详细描述您的建议或遇到的问题..."
              class="w-full px-3 py-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-surface)] text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-brand-500)] resize-none"
            />
          </div>

          <div>
            <label class="block text-xs font-semibold text-[var(--color-text-secondary)] mb-1">联系方式 (可选)</label>
            <input
              v-model="feedback.contact"
              type="text"
              placeholder="邮箱或手机号"
              class="w-full px-3 py-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-surface)] text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-brand-500)]"
            >
          </div>
        </div>

        <div class="pt-2 flex justify-end">
          <AdaptiveButton
            variant="primary"
            size="sm"
            :disabled="!feedback.content.trim()"
            :loading="saving"
            @click="handleSendFeedback"
          >
            <span>提交反馈</span>
          </AdaptiveButton>
        </div>
      </AdaptiveCard>
    </div>
  </AdaptiveContainer>
</template>
