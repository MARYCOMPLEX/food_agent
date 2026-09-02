<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import AdaptiveContainer from '../../shared/ui/AdaptiveContainer.vue'
import AdaptiveButton from '../../shared/ui/AdaptiveButton.vue'
import AdaptiveDrawer from '../../shared/ui/AdaptiveDrawer.vue'
import StatusBadge from '../../shared/ui/StatusBadge.vue'
import { formatRelativeTime } from '../../shared/utils/date'
import { formatDuration } from '../../shared/utils/formatters'
import { taskObservabilityApi } from './api/tasksApi'
import type { ObservabilityTask } from './types'

const router = useRouter()

const tasks = ref<ObservabilityTask[]>([])
const filterType = ref('all')
const filterStatus = ref('all')
const selectedTask = ref<ObservabilityTask | null>(null)
const drawerOpen = ref(false)

async function loadTasks() {
  try {
    tasks.value = await taskObservabilityApi.getTasks({
      type: filterType.value,
      status: filterStatus.value,
    })
  }
  catch (err) {
    console.error('Load tasks failed', err)
  }
}

function openDetail(task: ObservabilityTask) {
  selectedTask.value = task
  drawerOpen.value = true
}

function jumpToSession(sessionId?: string) {
  if (sessionId) {
    router.push(`/app/sessions/${sessionId}`)
  }
}

onMounted(() => {
  loadTasks()
})
</script>

<template>
  <AdaptiveContainer max-width="2xl" class="space-y-6">
    <!-- Header -->
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
      <div>
        <h1 class="text-xl md:text-2xl font-bold text-[var(--color-text-primary)]">
          任务生命周期观测 (Task Observability)
        </h1>
        <p class="text-xs md:text-sm text-[var(--color-text-secondary)] mt-0.5">
          只读观测 Research 研判任务、Refresh 增量刷新与 Media 媒体抽取生命周期
        </p>
      </div>

      <AdaptiveButton variant="subtle" size="sm" @click="loadTasks">
        <span>🔄 刷新任务流</span>
      </AdaptiveButton>
    </div>

    <!-- Filter Bar -->
    <div class="p-3 bg-[var(--color-bg-surface)] rounded-xl border border-[var(--color-border)] flex flex-wrap items-center gap-3 text-xs">
      <div class="flex items-center gap-1.5">
        <span class="text-[var(--color-text-tertiary)]">任务类型:</span>
        <select
          v-model="filterType"
          class="px-2.5 py-1.5 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-subtle)] text-[var(--color-text-primary)] outline-none"
          @change="loadTasks"
        >
          <option value="all">
            全部类型 (All)
          </option>
          <option value="research">
            Research 研判任务
          </option>
          <option value="refresh">
            Refresh 增量刷新
          </option>
          <option value="media">
            Media 媒体解析
          </option>
        </select>
      </div>

      <div class="flex items-center gap-1.5">
        <span class="text-[var(--color-text-tertiary)]">执行状态:</span>
        <select
          v-model="filterStatus"
          class="px-2.5 py-1.5 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-subtle)] text-[var(--color-text-primary)] outline-none"
          @change="loadTasks"
        >
          <option value="all">
            全部状态 (All)
          </option>
          <option value="completed">
            Completed 完成
          </option>
          <option value="running">
            Running 执行中
          </option>
          <option value="failed">
            Failed 异常
          </option>
        </select>
      </div>
    </div>

    <!-- Task List Table -->
    <div class="bg-[var(--color-bg-surface)] border border-[var(--color-border)] rounded-xl overflow-hidden shadow-xs">
      <div class="overflow-x-auto">
        <table class="w-full text-left text-xs">
          <thead class="bg-[var(--color-bg-subtle)] border-b border-[var(--color-border)] text-[var(--color-text-tertiary)] uppercase">
            <tr>
              <th class="px-4 py-3">
                Task ID
              </th>
              <th class="px-4 py-3">
                类型
              </th>
              <th class="px-4 py-3">
                查询 Query
              </th>
              <th class="px-4 py-3">
                耗时
              </th>
              <th class="px-4 py-3">
                轮次 / 重试
              </th>
              <th class="px-4 py-3">
                状态
              </th>
              <th class="px-4 py-3">
                创建时间
              </th>
              <th class="px-4 py-3 text-right">
                操作
              </th>
            </tr>
          </thead>
          <tbody class="divide-y divide-[var(--color-border)]">
            <tr
              v-for="task in tasks"
              :key="task.task_id"
              class="hover:bg-[var(--color-neutral-100)] transition-colors cursor-pointer"
              @click="openDetail(task)"
            >
              <td class="px-4 py-3 font-mono font-bold text-[var(--color-brand-600)]">
                {{ task.task_id }}
              </td>
              <td class="px-4 py-3">
                <span class="px-2 py-0.5 rounded bg-[var(--color-neutral-200)] font-medium">
                  {{ task.type }}
                </span>
              </td>
              <td class="px-4 py-3 max-w-xs truncate font-medium text-[var(--color-text-primary)]">
                {{ task.query || '-' }}
              </td>
              <td class="px-4 py-3 font-mono">
                {{ formatDuration(task.duration_ms) }}
              </td>
              <td class="px-4 py-3 font-mono">
                Turn: {{ task.turn_count }} · Retry: {{ task.retry_count }}
              </td>
              <td class="px-4 py-3">
                <StatusBadge :status="task.status" size="sm" />
              </td>
              <td class="px-4 py-3 text-[var(--color-text-tertiary)] whitespace-nowrap">
                {{ formatRelativeTime(task.created_at) }}
              </td>
              <td class="px-4 py-3 text-right">
                <button
                  class="text-[var(--color-brand-600)] hover:underline font-semibold cursor-pointer"
                  @click.stop="openDetail(task)"
                >
                  详情 →
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Task Detail Drawer -->
    <AdaptiveDrawer
      v-model="drawerOpen"
      :title="`任务观测详情 - ${selectedTask?.task_id || ''}`"
      width="480px"
    >
      <div v-if="selectedTask" class="space-y-4 text-xs">
        <div class="p-3 bg-[var(--color-bg-subtle)] rounded-xl border border-[var(--color-border)] space-y-2">
          <div class="flex items-center justify-between">
            <span class="font-bold text-sm text-[var(--color-text-primary)]">任务状态信息</span>
            <StatusBadge :status="selectedTask.status" size="sm" />
          </div>
          <div class="grid grid-cols-2 gap-2 text-[var(--color-text-secondary)]">
            <div><span class="text-[var(--color-text-tertiary)]">Task ID: </span><code class="font-mono">{{ selectedTask.task_id }}</code></div>
            <div><span class="text-[var(--color-text-tertiary)]">Session Ref: </span><code class="font-mono">{{ selectedTask.session_id }}</code></div>
            <div><span class="text-[var(--color-text-tertiary)]">执行耗时: </span><span>{{ formatDuration(selectedTask.duration_ms) }}</span></div>
            <div><span class="text-[var(--color-text-tertiary)]">恢复状态: </span><span>{{ selectedTask.recovery_state }}</span></div>
          </div>
        </div>

        <div class="p-3 bg-[var(--color-bg-surface)] rounded-xl border border-[var(--color-border)] space-y-1.5">
          <div class="font-bold text-[var(--color-text-primary)]">
            研判查询 Prompt
          </div>
          <p class="text-sm text-[var(--color-text-secondary)] leading-relaxed">
            {{ selectedTask.query }}
          </p>
        </div>

        <div class="pt-2 flex justify-end">
          <AdaptiveButton
            v-if="selectedTask.session_id"
            variant="primary"
            size="sm"
            @click="jumpToSession(selectedTask.session_id)"
          >
            <span>🔗 跳转到对应用户端研判会话</span>
          </AdaptiveButton>
        </div>
      </div>
    </AdaptiveDrawer>
  </AdaptiveContainer>
</template>
