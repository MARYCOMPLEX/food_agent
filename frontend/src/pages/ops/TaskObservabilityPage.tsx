import React, { useState } from 'react'
import {
  Activity,
  Search,
  CheckCircle2,
  AlertTriangle,
  RefreshCw,
  RotateCcw,
  StopCircle,
  ChevronRight,
  X,
} from 'lucide-react'
import { useToast } from '../../context/ToastContext'

interface ObservabilityTaskItem {
  taskId: string
  sessionId: string
  query: string
  type: string
  status: 'running' | 'succeeded' | 'partial' | 'failed'
  turnCount: number
  durationMs: number
  retryCount: number
  evidenceCount: number
  profileCount: number
  gapCount: number
  createdAt: string
  timeline: Array<{ time: string; action: string; status: string; detail?: string }>
}

export function TaskObservabilityPage() {
  const { showToast } = useToast()
  const [searchQuery, setSearchQuery] = useState<string>('')
  const [selectedTask, setSelectedTask] = useState<ObservabilityTaskItem | null>(null)

  const [tasks] = useState<ObservabilityTaskItem[]>([
    {
      taskId: 'task_cd_hotpot_001',
      sessionId: 'session_demo_cd_hotpot',
      query: '周六晚在成都玉林，三个人想吃串串，人均 100 以内...',
      type: 'research',
      status: 'succeeded',
      turnCount: 2,
      durationMs: 4200,
      retryCount: 0,
      evidenceCount: 18,
      profileCount: 4,
      gapCount: 0,
      createdAt: '2026-09-11 01:12:30',
      timeline: [
        { time: '01:12:30', action: 'intent_parsed', status: 'done', detail: '识别地点: 成都玉林, 预算: 100, 排除: 纯网红' },
        { time: '01:12:31', action: 'comment_collection.search_notes', status: 'done', detail: '抓取 12 篇笔记元数据' },
        { time: '01:12:32', action: 'comment_collection.fetch_comments', status: 'done', detail: '抓取 84 条评论并清洗' },
        { time: '01:12:33', action: 'shop_profile_enrichment.search_poi', status: 'done', detail: '大众点评完成 4 家门店 POI 绑定' },
        { time: '01:12:34', action: 'recommendation_synthesized', status: 'done', detail: '输出综合研判报告' },
      ],
    },
    {
      taskId: 'task_gz_morningtea_002',
      sessionId: 'session_demo_gz_morningtea',
      query: '广州越秀或荔湾区，两个人周末上午喝早茶，人均 80 左右...',
      type: 'research',
      status: 'partial',
      turnCount: 1,
      durationMs: 3800,
      retryCount: 1,
      evidenceCount: 12,
      profileCount: 3,
      gapCount: 1,
      createdAt: '2026-09-11 01:05:10',
      timeline: [
        { time: '01:05:10', action: 'intent_parsed', status: 'done', detail: '识别地点: 广州越秀/荔湾, 预算: 80' },
        { time: '01:05:11', action: 'comment_collection.fetch_comments', status: 'done', detail: '抓取 46 条小红书早茶真实口碑' },
        { time: '01:05:12', action: 'shop_profile_enrichment.fetch_detail', status: 'partial', detail: '大众点评要求滑块验证，保留评论候选' },
      ],
    },
    {
      taskId: 'task_sh_dating_003',
      sessionId: 'session_demo_sh_dating',
      query: '上海静安寺附近，两人约会，人均 180 左右...',
      type: 'research',
      status: 'running',
      turnCount: 1,
      durationMs: 1200,
      retryCount: 0,
      evidenceCount: 6,
      profileCount: 1,
      gapCount: 0,
      createdAt: '2026-09-11 01:28:40',
      timeline: [
        { time: '01:28:40', action: 'intent_parsed', status: 'done', detail: '识别地点: 上海静安寺' },
        { time: '01:28:41', action: 'comment_collection.search_notes', status: 'running', detail: '正在搜索小酒馆/意面笔记' },
      ],
    },
  ])

  const filteredTasks = tasks.filter(
    (t) =>
      t.taskId.toLowerCase().includes(searchQuery.toLowerCase()) ||
      t.query.toLowerCase().includes(searchQuery.toLowerCase()),
  )

  const handleRetryTask = (task: ObservabilityTaskItem) => {
    showToast(`已向调度器发送任务重试请求: ${task.taskId}`, 'info')
  }

  const handleCancelTask = (task: ObservabilityTaskItem) => {
    showToast(`已终止任务: ${task.taskId}`, 'warning')
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-zinc-200/80">
        <div>
          <h1 className="text-xl font-semibold text-zinc-900 tracking-tight flex items-center gap-2">
            <Activity className="w-5 h-5 text-[#10a37f]" />
            <span>任务执行观测台</span>
          </h1>
          <p className="text-xs text-zinc-500 mt-1">
            全量调查任务链路流转、Temporal 状态、耗时与错误排查
          </p>
        </div>

        {/* Search */}
        <div className="relative">
          <Search className="w-4 h-4 text-zinc-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            placeholder="搜索 Task ID 或 Query..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9 pr-3 py-1.5 bg-white border border-zinc-200 rounded-full text-xs text-zinc-900 placeholder:text-zinc-400 focus:outline-none focus:ring-1 focus:ring-zinc-400 shadow-2xs w-60"
          />
        </div>
      </div>

      {/* Task Table */}
      <div className="bg-white border border-zinc-200/80 rounded-2xl overflow-x-auto shadow-2xs">
        <table className="w-full text-left text-xs text-zinc-700">
          <thead className="bg-zinc-50/70 border-b border-zinc-200/80 text-zinc-500 uppercase text-[11px] font-mono">
            <tr>
              <th className="p-3.5">Task ID / 时间</th>
              <th className="p-3.5">需求摘要</th>
              <th className="p-3.5">状态</th>
              <th className="p-3.5">耗时</th>
              <th className="p-3.5">产出指标</th>
              <th className="p-3.5 text-right">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100 font-mono">
            {filteredTasks.map((task) => {
              let statusBadge = {
                text: 'SUCCEEDED',
                class: 'bg-emerald-50 text-[#10a37f] border-emerald-200/60',
                icon: CheckCircle2,
              }
              if (task.status === 'running') {
                statusBadge = {
                  text: 'RUNNING',
                  class: 'bg-amber-50 text-amber-700 border-amber-200/60',
                  icon: RefreshCw,
                }
              } else if (task.status === 'partial') {
                statusBadge = {
                  text: 'PARTIAL',
                  class: 'bg-zinc-100 text-zinc-700 border-zinc-200',
                  icon: AlertTriangle,
                }
              }

              const StatusIcon = statusBadge.icon

              return (
                <tr key={task.taskId} className="hover:bg-zinc-50/60 transition-colors">
                  <td className="p-3.5">
                    <div className="font-semibold text-zinc-900 text-xs">{task.taskId}</div>
                    <div className="text-[10px] text-zinc-400 mt-0.5">{task.createdAt}</div>
                  </td>

                  <td className="p-3.5 max-w-xs font-sans">
                    <div className="truncate text-zinc-800">{task.query}</div>
                    <div className="text-[10px] text-zinc-400 font-mono mt-0.5">{task.sessionId}</div>
                  </td>

                  <td className="p-3.5">
                    <span
                      className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-mono font-medium border ${statusBadge.class}`}
                    >
                      <StatusIcon className={`w-3 h-3 ${task.status === 'running' ? 'animate-spin' : ''}`} />
                      <span>{statusBadge.text}</span>
                    </span>
                  </td>

                  <td className="p-3.5 text-zinc-500">{task.durationMs}ms</td>

                  <td className="p-3.5 text-zinc-500">
                    <div>
                      {task.evidenceCount} 证据 / {task.profileCount} 档案
                    </div>
                    {task.gapCount > 0 && <div className="text-amber-600 text-[10px]">{task.gapCount} 个缺口</div>}
                  </td>

                  <td className="p-3.5 text-right font-sans">
                    <button
                      onClick={() => setSelectedTask(task)}
                      className="inline-flex items-center gap-1 px-3 py-1.5 rounded-full border border-zinc-200 bg-white hover:bg-zinc-50 text-zinc-700 text-xs font-medium transition-colors shadow-2xs"
                    >
                      <span>时间线</span>
                      <ChevronRight className="w-3 h-3 text-zinc-400" />
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Task Detail Modal */}
      {selectedTask && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-xs animate-in fade-in">
          <div className="bg-white border border-zinc-200 rounded-2xl max-w-xl w-full p-6 space-y-4 shadow-xl">
            <div className="flex items-center justify-between border-b border-zinc-100 pb-3">
              <div>
                <h3 className="font-semibold text-zinc-900 text-sm font-mono">{selectedTask.taskId}</h3>
                <p className="text-xs text-zinc-500 font-sans mt-0.5">{selectedTask.query}</p>
              </div>
              <button
                onClick={() => setSelectedTask(null)}
                className="text-zinc-400 hover:text-zinc-700 p-1 rounded-md transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Timeline */}
            <div className="space-y-3 max-h-72 overflow-y-auto pr-1">
              <div className="text-xs font-semibold text-zinc-500 uppercase tracking-wider font-mono">
                动作执行生命周期
              </div>
              <div className="space-y-3 border-l-2 border-zinc-200 ml-2 pl-3">
                {selectedTask.timeline.map((step, idx) => (
                  <div key={idx} className="space-y-0.5 text-xs font-mono">
                    <div className="flex items-center gap-2">
                      <span className="text-zinc-400 text-[11px]">{step.time}</span>
                      <span className="text-zinc-900 font-medium">{step.action}</span>
                      <span className="text-[10px] px-1.5 py-0.5 rounded-md bg-zinc-100 text-zinc-600 border border-zinc-200/60">
                        {step.status}
                      </span>
                    </div>
                    {step.detail && <div className="text-zinc-500 text-[11px] font-sans">{step.detail}</div>}
                  </div>
                ))}
              </div>
            </div>

            {/* Actions */}
            <div className="pt-3 border-t border-zinc-100 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <button
                  onClick={() => handleRetryTask(selectedTask)}
                  className="px-3 py-1.5 rounded-full border border-zinc-200 bg-white hover:bg-zinc-50 text-zinc-700 text-xs font-medium flex items-center gap-1.5 transition-colors shadow-2xs"
                >
                  <RotateCcw className="w-3.5 h-3.5" />
                  <span>重新触发</span>
                </button>
                {selectedTask.status === 'running' && (
                  <button
                    onClick={() => handleCancelTask(selectedTask)}
                    className="px-3 py-1.5 rounded-full border border-rose-200 bg-rose-50 hover:bg-rose-100 text-rose-700 text-xs font-medium flex items-center gap-1.5 transition-colors"
                  >
                    <StopCircle className="w-3.5 h-3.5" />
                    <span>终止任务</span>
                  </button>
                )}
              </div>

              <button
                onClick={() => setSelectedTask(null)}
                className="px-4 py-1.5 rounded-full bg-zinc-900 hover:bg-zinc-800 text-white text-xs font-medium transition-colors shadow-2xs"
              >
                关闭
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
