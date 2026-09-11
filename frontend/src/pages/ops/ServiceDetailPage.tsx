import React, { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Server,
  ArrowLeft,
  CheckCircle2,
  AlertTriangle,
  Play,
  Layers,
  Shield,
  HelpCircle,
  Eye,
  Sliders,
} from 'lucide-react'
import { useToast } from '../../context/ToastContext'

interface ToolItem {
  toolName: string
  standardCapability: string
  description: string
  isReadOnly: boolean
  isAllowed: boolean
  callSuccessRate: string
  schemaFields: string[]
}

export function ServiceDetailPage() {
  const { serviceId } = useParams<{ serviceId: string }>()
  const navigate = useNavigate()
  const { showToast } = useToast()

  const [tools, setTools] = useState<ToolItem[]>([
    {
      toolName: 'xhs_search_notes',
      standardCapability: 'comment_collection.search_notes',
      description: '根据关键词与商圈检索小红书公开美食笔记，提取评论入口元数据',
      isReadOnly: true,
      isAllowed: true,
      callSuccessRate: '99.2%',
      schemaFields: ['keywords: string[]', 'city: string', 'limit: number'],
    },
    {
      toolName: 'xhs_fetch_comments',
      standardCapability: 'comment_collection.fetch_comments',
      description: '拉取指定笔记下的热门真实评论，按点赞与讨论深度过滤',
      isReadOnly: true,
      isAllowed: true,
      callSuccessRate: '98.7%',
      schemaFields: ['note_id: string', 'sort: "hot" | "latest"', 'max_depth: number'],
    },
    {
      toolName: 'dp_search_poi',
      standardCapability: 'shop_profile_enrichment.search_poi',
      description: '根据候选餐厅名称检索大众点评 POI 匹配项',
      isReadOnly: true,
      isAllowed: true,
      callSuccessRate: '94.5%',
      schemaFields: ['shop_name: string', 'city: string', 'district?: string'],
    },
    {
      toolName: 'dp_fetch_poi_detail',
      standardCapability: 'shop_profile_enrichment.fetch_detail',
      description: '拉取营业时间、人均价格带、精确地址、推荐菜列表',
      isReadOnly: true,
      isAllowed: true,
      callSuccessRate: '91.8%',
      schemaFields: ['poi_id: string'],
    },
    {
      toolName: 'dp_post_user_review',
      standardCapability: 'forbidden.write_action',
      description: '向大众点评写入用户评价（写操作）',
      isReadOnly: false,
      isAllowed: false,
      callSuccessRate: 'N/A',
      schemaFields: ['poi_id: string', 'content: string', 'rating: number'],
    },
  ])

  const toggleToolAllowed = (toolName: string) => {
    setTools(
      tools.map((t) => {
        if (t.toolName === toolName) {
          const next = !t.isAllowed
          showToast(`已${next ? '放行' : '禁用'}工具: ${toolName}`, 'info')
          return { ...t, isAllowed: next }
        }
        return t
      }),
    )
  }

  const handleTestInvoke = (toolName: string) => {
    showToast(`正在对 ${toolName} 进行沙箱测试调用...`, 'info')
    setTimeout(() => {
      showToast(`工具 ${toolName} 测试调用成功，输出符合 Schema 规范`, 'success')
    }, 1000)
  }

  return (
    <div className="space-y-6">
      {/* Top Header */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => navigate('/ops/services')}
          className="p-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
        </button>
        <div>
          <h1 className="text-xl font-bold text-white tracking-tight flex items-center gap-2">
            <span>服务详情：{serviceId}</span>
          </h1>
          <p className="text-xs text-slate-400 mt-0.5">
            标准能力映射、工具 Schema 检查及放行策略管理
          </p>
        </div>
      </div>

      {/* Tools List */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-2xl overflow-hidden shadow-xs">
        <div className="p-4 border-b border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Layers className="w-4 h-4 text-orange-500" />
            <h3 className="font-semibold text-white text-sm">暴露的 MCP 工具列表 ({tools.length})</h3>
          </div>
          <span className="text-xs text-slate-500">仅放行工具允许被 Agent 内部编排</span>
        </div>

        <div className="divide-y divide-slate-800/80">
          {tools.map((t) => (
            <div key={t.toolName} className="p-5 flex flex-col md:flex-row md:items-center justify-between gap-4">
              <div className="space-y-2 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-bold text-white text-sm font-mono">{t.toolName}</span>
                  <span className="px-2 py-0.5 rounded bg-slate-800 text-slate-300 text-[11px] font-mono">
                    标准映射: {t.standardCapability}
                  </span>
                  <span
                    className={`px-2 py-0.5 rounded text-[10px] font-semibold uppercase ${
                      t.isReadOnly
                        ? 'bg-blue-500/10 text-blue-400 border border-blue-500/20'
                        : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
                    }`}
                  >
                    {t.isReadOnly ? 'READ ONLY' : 'SIDE EFFECT'}
                  </span>
                </div>

                <p className="text-xs text-slate-400 leading-relaxed">{t.description}</p>

                {/* Schema Fields */}
                <div className="flex items-center gap-2 flex-wrap text-[11px] font-mono text-slate-500">
                  <span>入参 Schema:</span>
                  {t.schemaFields.map((f, idx) => (
                    <span key={idx} className="bg-slate-950 px-2 py-0.5 rounded border border-slate-800 text-slate-300">
                      {f}
                    </span>
                  ))}
                  <span className="text-slate-400 ml-2">调用成功率: {t.callSuccessRate}</span>
                </div>
              </div>

              {/* Toggle & Test Action */}
              <div className="flex items-center gap-3 flex-shrink-0 self-end md:self-center">
                <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={t.isAllowed}
                    onChange={() => toggleToolAllowed(t.toolName)}
                    className="rounded bg-slate-950 border-slate-700 text-orange-600 focus:ring-orange-500"
                  />
                  <span>放行调用</span>
                </label>

                <button
                  disabled={!t.isAllowed}
                  onClick={() => handleTestInvoke(t.toolName)}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium transition-colors disabled:opacity-30"
                >
                  <Play className="w-3 h-3 text-orange-400" />
                  <span>沙箱测试</span>
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
