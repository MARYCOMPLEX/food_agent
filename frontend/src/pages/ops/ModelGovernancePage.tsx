import React, { useState } from 'react'
import {
  Cpu,
  Shield,
  Sliders,
  CheckCircle2,
  AlertTriangle,
  Lock,
  Key,
  Save,
  RotateCcw,
  Sparkles,
  Layers,
} from 'lucide-react'
import { useToast } from '../../context/ToastContext'

interface ModelProviderConfig {
  id: string
  providerName: string
  modelName: string
  role: 'intent_parser' | 'evidence_critic' | 'poi_enricher' | 'recommender'
  reasoningEffort: 'low' | 'medium' | 'high'
  maxTokens: number
  temperature: number
  isUserSelectable: boolean
  maskedApiKey: string
  status: 'active' | 'testing' | 'disabled'
}

export function ModelGovernancePage() {
  const { showToast } = useToast()

  const [configs, setConfigs] = useState<ModelProviderConfig[]>([
    {
      id: 'cfg_intent',
      providerName: 'DeepSeek / Anthropic',
      modelName: 'claude-3-5-sonnet-20241022',
      role: 'intent_parser',
      reasoningEffort: 'medium',
      maxTokens: 2048,
      temperature: 0.2,
      isUserSelectable: false,
      maskedApiKey: 'sk-ant-api03-••••••••••••••••••••••••9A7B',
      status: 'active',
    },
    {
      id: 'cfg_critic',
      providerName: 'OpenAI',
      modelName: 'o3-mini',
      role: 'evidence_critic',
      reasoningEffort: 'high',
      maxTokens: 4096,
      temperature: 1.0,
      isUserSelectable: false,
      maskedApiKey: 'sk-proj-••••••••••••••••••••••••F14C',
      status: 'active',
    },
    {
      id: 'cfg_recommender',
      providerName: 'Google Gemini',
      modelName: 'gemini-1.5-pro',
      role: 'recommender',
      reasoningEffort: 'high',
      maxTokens: 8192,
      temperature: 0.4,
      isUserSelectable: true,
      maskedApiKey: 'AIzaSy••••••••••••••••••••••••Z4X8',
      status: 'active',
    },
  ])

  const [auditLog, setAuditLog] = useState<string[]>([
    '2026-09-11 00:30:00 - 管理员发布新版本策略配置 v1.4.0（调高 Evidence Critic 的 reasoning effort 至 high）',
    '2026-09-10 16:15:00 - 接入 Gemini 1.5 Pro 模型并在灰度集群通过并发负载测试',
  ])

  const handleSave = () => {
    showToast('模型治理策略已成功部署生效 (配置版本: v1.4.1)', 'success')
    setAuditLog([
      `${new Date().toISOString().replace('T', ' ').slice(0, 19)} - 管理员更新并发布模型策略配置 (v1.4.1)`,
      ...auditLog,
    ])
  }

  const roleLabelMap = {
    intent_parser: '意图拆解与地点约束解析',
    evidence_critic: '真实评论证据质检与争议提炼',
    poi_enricher: '大众点评 POI 实体消歧与档案对齐',
    recommender: '最终综合推荐与论据合成',
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white tracking-tight flex items-center gap-2">
            <Cpu className="w-5 h-5 text-orange-500" />
            <span>模型与调查策略治理 (Target Capability)</span>
          </h1>
          <p className="text-xs text-slate-400 mt-0.5">
            配置模型目录、角色推理强度 (Reasoning Effort)、参数放行规则与 API Key 掩码安全保护
          </p>
        </div>

        <button
          onClick={handleSave}
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-orange-600 hover:bg-orange-500 text-white text-xs font-semibold shadow-md transition-colors"
        >
          <Save className="w-3.5 h-3.5" />
          <span>保存并发布策略</span>
        </button>
      </div>

      {/* Security Protection Callout */}
      <div className="p-4 rounded-2xl bg-slate-900/90 border border-slate-800 text-xs text-slate-300 flex items-start gap-3">
        <Lock className="w-5 h-5 text-emerald-400 flex-shrink-0 mt-0.5" />
        <div className="space-y-1">
          <div className="font-semibold text-white">模型 Key 加密与参数防漂移规范</div>
          <div className="text-slate-400 leading-relaxed text-[11px]">
            API Key 保存后单向掩码化存储，永远不可再次逆向查阅明文。模型 temperature 与 reasoning effort 受后端 Hard Limit 约束，客户端不得绕过安全策略。
          </div>
        </div>
      </div>

      {/* Model Configurations Grid */}
      <div className="space-y-4">
        {configs.map((cfg) => (
          <div
            key={cfg.id}
            className="bg-slate-900/80 border border-slate-800 p-5 rounded-2xl space-y-4 shadow-xs"
          >
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-slate-800">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <span className="font-bold text-white text-sm">{cfg.providerName}</span>
                  <span className="font-mono text-orange-400 text-xs px-2 py-0.5 rounded bg-slate-950 border border-slate-800">
                    {cfg.modelName}
                  </span>
                  <span className="px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-[10px] font-mono">
                    {cfg.status.toUpperCase()}
                  </span>
                </div>
                <div className="text-xs text-slate-400">承担角色：{roleLabelMap[cfg.role]}</div>
              </div>

              <div className="flex items-center gap-2">
                <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={cfg.isUserSelectable}
                    onChange={(e) => {
                      setConfigs(
                        configs.map((c) => (c.id === cfg.id ? { ...c, isUserSelectable: e.target.checked } : c)),
                      )
                    }}
                    className="rounded bg-slate-950 border-slate-700 text-orange-600 focus:ring-orange-500"
                  />
                  <span>用户端高级设置可选</span>
                </label>
              </div>
            </div>

            {/* Parameter Fields */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-xs font-mono">
              {/* Reasoning Effort */}
              <div className="space-y-1.5 font-sans">
                <label className="text-slate-400 text-[11px]">Reasoning Effort (推理深度)</label>
                <select
                  value={cfg.reasoningEffort}
                  onChange={(e) => {
                    setConfigs(
                      configs.map((c) => (c.id === cfg.id ? { ...c, reasoningEffort: e.target.value as any } : c)),
                    )
                  }}
                  className="w-full p-2 rounded-xl bg-slate-950 border border-slate-800 text-slate-200 text-xs font-mono focus:outline-none focus:border-orange-500"
                >
                  <option value="low">low (快速筛选)</option>
                  <option value="medium">medium (常规均衡)</option>
                  <option value="high">high (深度交叉核验)</option>
                </select>
              </div>

              {/* Max Tokens */}
              <div className="space-y-1.5 font-sans">
                <label className="text-slate-400 text-[11px]">Max Tokens 限制</label>
                <input
                  type="number"
                  value={cfg.maxTokens}
                  onChange={(e) => {
                    setConfigs(
                      configs.map((c) => (c.id === cfg.id ? { ...c, maxTokens: Number(e.target.value) } : c)),
                    )
                  }}
                  className="w-full p-2 rounded-xl bg-slate-950 border border-slate-800 text-slate-200 text-xs font-mono focus:outline-none focus:border-orange-500"
                />
              </div>

              {/* Masked API Key */}
              <div className="space-y-1.5 font-sans">
                <label className="text-slate-400 text-[11px] flex items-center gap-1">
                  <Key className="w-3 h-3 text-orange-400" />
                  <span>凭据状态 (只读掩码)</span>
                </label>
                <input
                  type="text"
                  disabled
                  value={cfg.maskedApiKey}
                  className="w-full p-2 rounded-xl bg-slate-950/80 border border-slate-800 text-slate-500 text-xs font-mono cursor-not-allowed"
                />
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Audit Log (Section 24.6) */}
      <div className="bg-slate-900/80 border border-slate-800 p-5 rounded-2xl space-y-3">
        <h3 className="font-semibold text-sm text-white flex items-center gap-2">
          <Shield className="w-4 h-4 text-orange-500" />
          <span>策略版本审计与回滚日志</span>
        </h3>

        <div className="space-y-2">
          {auditLog.map((log, idx) => (
            <div key={idx} className="p-2.5 rounded-xl bg-slate-950/60 border border-slate-800/80 text-xs font-mono text-slate-400">
              {log}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
