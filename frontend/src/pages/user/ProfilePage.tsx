import React, { useState } from 'react'
import {
  User,
  Brain,
  Sliders,
  CheckCircle2,
  Trash2,
  Save,
  MapPin,
  Sparkles,
  Shield,
  HelpCircle,
} from 'lucide-react'
import { storage } from '../../shared/utils/storage'
import { useToast } from '../../context/ToastContext'

interface InferredMemory {
  id: string
  category: string
  label: string
  value: string
  confidence: number
  sourceSession: string
  updatedAt: string
}

export function ProfilePage() {
  const { showToast } = useToast()

  // Explicit Settings
  const [name, setName] = useState<string>('美食探索家')
  const [defaultCity, setDefaultCity] = useState<string>('成都')
  const [budgetBand, setBudgetBand] = useState<string>('人均 80 - 150 元')
  const [spiceLevel, setSpiceLevel] = useState<string>('中辣 / 重口味')
  const [dietary, setDietary] = useState<string>('不吃香菜，轻度乳糖不耐')
  const [scenePreference, setScenePreference] = useState<string>('三两好友聚餐 / 避开纯网红拍照店')
  const [enablePersonalization, setEnablePersonalization] = useState<boolean>(true)

  // Inferred Memories (transparent to the user)
  const [memories, setMemories] = useState<InferredMemory[]>([
    {
      id: 'mem_1',
      category: '口味偏好',
      label: '底料咸度容忍低',
      value: '多次强调“不要太咸”，倾向于纯牛油天然香味而非味精酱油调味',
      confidence: 0.92,
      sourceSession: '成都玉林串串调查',
      updatedAt: '2026-09-09',
    },
    {
      id: 'mem_2',
      category: '排队决策',
      label: '排队阈值 45 分钟',
      value: '周末晚餐可接受排队半小时左右，超过1小时会要求降级替代方案',
      confidence: 0.85,
      sourceSession: '广州早茶调查',
      updatedAt: '2026-09-08',
    },
    {
      id: 'mem_3',
      category: '分店辨识',
      label: '高度重视老店总店',
      value: '倾向于本地老饕常去老店，怀疑商场加盟分店品控一致性',
      confidence: 0.88,
      sourceSession: '火锅专题研判',
      updatedAt: '2026-09-07',
    },
  ])

  const handleSaveProfile = () => {
    storage.set('anyfast_user_profile', {
      name,
      defaultCity,
      budgetBand,
      spiceLevel,
      dietary,
      scenePreference,
      enablePersonalization,
    })
    showToast('个人基础偏好设置已更新', 'success')
  }

  const handleDeleteMemory = (id: string, label: string) => {
    const next = memories.filter((m) => m.id !== id)
    setMemories(next)
    showToast(`已删除推断记忆：“${label}”`, 'info')
  }

  const handleClearAllMemories = () => {
    if (window.confirm('确认清空 Agent 提炼的所有个性化记忆？')) {
      setMemories([])
      showToast('所有提炼偏好记忆已清除', 'info')
    }
  }

  return (
    <div className="max-w-4xl mx-auto space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-900 tracking-tight flex items-center gap-2">
          <User className="w-6 h-6 text-orange-600" />
          <span>个人偏好与 Agent 记忆透明中心</span>
        </h1>
        <p className="text-xs text-slate-500 mt-1">
          设置显式默认条件，查看并管理 Agent 从历史调查中自主学习的偏好记忆
        </p>
      </div>

      {/* Memory Transparency Card (Section 23.2) */}
      <div className="bg-white rounded-3xl border border-slate-200/90 p-6 shadow-xs space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-3 border-b border-slate-100">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-xl bg-indigo-50 text-indigo-600 flex items-center justify-center">
              <Brain className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-bold text-slate-900 text-base">Agent 记忆透明度</h3>
              <p className="text-xs text-slate-500">
                Agent 从你的历史调查与追问中提炼的稳定倾向（区别于原始聊天记录）
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 text-xs text-slate-700 font-medium cursor-pointer">
              <input
                type="checkbox"
                checked={enablePersonalization}
                onChange={(e) => setEnablePersonalization(e.target.checked)}
                className="rounded text-orange-600 focus:ring-orange-500"
              />
              <span>启用记忆驱动的个性化研判</span>
            </label>

            {memories.length > 0 && (
              <button
                onClick={handleClearAllMemories}
                className="text-xs text-rose-600 hover:text-rose-700 font-medium underline"
              >
                清空记忆
              </button>
            )}
          </div>
        </div>

        {memories.length === 0 ? (
          <div className="p-8 text-center text-xs text-slate-400">
            暂无提炼的偏好记忆。多进行几次调查后，Agent 将自动在此沉淀真实可信的用餐习惯。
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {memories.map((mem) => (
              <div
                key={mem.id}
                className="p-4 rounded-2xl bg-slate-50 border border-slate-200/70 space-y-2 flex flex-col justify-between text-xs"
              >
                <div className="space-y-1">
                  <div className="flex items-center justify-between">
                    <span className="px-2 py-0.5 rounded-md bg-indigo-100 text-indigo-800 text-[10px] font-semibold">
                      {mem.category}
                    </span>
                    <span className="font-mono text-slate-400 text-[10px]">
                      置信度 {Math.round(mem.confidence * 100)}%
                    </span>
                  </div>
                  <h4 className="font-bold text-slate-900 text-sm mt-1">{mem.label}</h4>
                  <p className="text-slate-600 leading-relaxed text-[11px]">{mem.value}</p>
                </div>

                <div className="pt-2 border-t border-slate-200/50 flex items-center justify-between text-[10px] text-slate-400">
                  <span>来自：{mem.sourceSession}</span>
                  <button
                    onClick={() => handleDeleteMemory(mem.id, mem.label)}
                    className="text-slate-300 hover:text-rose-600 p-1"
                    title="删除该记忆"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Explicit Preference Form (Section 23.1) */}
      <div className="bg-white rounded-3xl border border-slate-200/90 p-6 shadow-xs space-y-5">
        <div className="flex items-center gap-2.5 pb-3 border-b border-slate-100">
          <div className="w-9 h-9 rounded-xl bg-orange-50 text-orange-600 flex items-center justify-center">
            <Sliders className="w-5 h-5" />
          </div>
          <div>
            <h3 className="font-bold text-slate-900 text-base">显式基础偏好</h3>
            <p className="text-xs text-slate-500">用于作为发起新调查时的默认填充值</p>
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
          {/* Default City */}
          <div className="space-y-1.5">
            <label className="font-semibold text-slate-700">常住城市 / 主要商圈</label>
            <input
              type="text"
              value={defaultCity}
              onChange={(e) => setDefaultCity(e.target.value)}
              className="w-full p-2.5 rounded-xl bg-slate-50 border border-slate-200 text-slate-900 focus:bg-white focus:outline-none focus:ring-2 focus:ring-orange-500"
            />
          </div>

          {/* Budget */}
          <div className="space-y-1.5">
            <label className="font-semibold text-slate-700">常规人均预算区间</label>
            <input
              type="text"
              value={budgetBand}
              onChange={(e) => setBudgetBand(e.target.value)}
              className="w-full p-2.5 rounded-xl bg-slate-50 border border-slate-200 text-slate-900 focus:bg-white focus:outline-none focus:ring-2 focus:ring-orange-500"
            />
          </div>

          {/* Spice Level */}
          <div className="space-y-1.5">
            <label className="font-semibold text-slate-700">常规辣度 / 口味倾向</label>
            <input
              type="text"
              value={spiceLevel}
              onChange={(e) => setSpiceLevel(e.target.value)}
              className="w-full p-2.5 rounded-xl bg-slate-50 border border-slate-200 text-slate-900 focus:bg-white focus:outline-none focus:ring-2 focus:ring-orange-500"
            />
          </div>

          {/* Dietary Restrictions */}
          <div className="space-y-1.5">
            <label className="font-semibold text-slate-700">忌口、过敏与硬排除项</label>
            <input
              type="text"
              value={dietary}
              onChange={(e) => setDietary(e.target.value)}
              className="w-full p-2.5 rounded-xl bg-slate-50 border border-slate-200 text-slate-900 focus:bg-white focus:outline-none focus:ring-2 focus:ring-orange-500"
            />
          </div>

          {/* Typical Scene */}
          <div className="space-y-1.5 sm:col-span-2">
            <label className="font-semibold text-slate-700">高频用餐场景与踩雷顾虑</label>
            <input
              type="text"
              value={scenePreference}
              onChange={(e) => setScenePreference(e.target.value)}
              className="w-full p-2.5 rounded-xl bg-slate-50 border border-slate-200 text-slate-900 focus:bg-white focus:outline-none focus:ring-2 focus:ring-orange-500"
            />
          </div>
        </div>

        <div className="pt-2 flex justify-end">
          <button
            onClick={handleSaveProfile}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-orange-600 hover:bg-orange-700 text-white text-xs font-semibold shadow-sm transition-colors"
          >
            <Save className="w-4 h-4" />
            <span>保存偏好设置</span>
          </button>
        </div>
      </div>
    </div>
  )
}
