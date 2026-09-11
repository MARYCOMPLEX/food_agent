import React, { useState } from 'react'
import {
  Database,
  Search,
  CheckCircle2,
  AlertTriangle,
  Clock,
  ShieldCheck,
  Tag,
  Layers,
  Sparkles,
} from 'lucide-react'
import { useToast } from '../../context/ToastContext'

interface EvidenceBundleRecord {
  bundleId: string
  familyId: string
  version: string
  itemCount: number
  freshnessHours: number
  sourcesBreakdown: Record<string, number>
  dedupRate: string
  maskingCheck: 'passed' | 'warning'
  createdAt: string
}

export function EvidenceObservabilityPage() {
  const { showToast } = useToast()
  const [searchQuery, setSearchQuery] = useState<string>('')

  const [bundles, setBundles] = useState<EvidenceBundleRecord[]>([
    {
      bundleId: 'bundle_cd_hotpot_v1',
      familyId: 'family_cd_spicy_dining',
      version: '1.2.0',
      itemCount: 48,
      freshnessHours: 3.5,
      sourcesBreakdown: { xhs_pc: 36, dianping: 12 },
      dedupRate: '98.4%',
      maskingCheck: 'passed',
      createdAt: '2026-09-11 00:45:00',
    },
    {
      bundleId: 'bundle_gz_tea_v2',
      familyId: 'family_gz_morning_tea',
      version: '2.0.1',
      itemCount: 62,
      freshnessHours: 12.0,
      sourcesBreakdown: { xhs_pc: 48, dianping: 14 },
      dedupRate: '96.8%',
      maskingCheck: 'passed',
      createdAt: '2026-09-10 18:20:00',
    },
    {
      bundleId: 'bundle_sh_bistro_v1',
      familyId: 'family_sh_dating_scenes',
      version: '1.0.0',
      itemCount: 28,
      freshnessHours: 1.2,
      sourcesBreakdown: { xhs_pc: 22, dianping: 6 },
      dedupRate: '99.1%',
      maskingCheck: 'passed',
      createdAt: '2026-09-11 01:00:00',
    },
  ])

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-white tracking-tight flex items-center gap-2">
            <Database className="w-5 h-5 text-orange-500" />
            <span>证据数据质量与 Bundle 观测</span>
          </h1>
          <p className="text-xs text-slate-400 mt-0.5">
            监控 Evidence Bundle 版本游标、去重比率、隐私脱敏合规性与时效窗口
          </p>
        </div>

        <div className="relative">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            placeholder="搜索 Bundle ID 或 Family..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9 pr-3 py-1.5 bg-slate-900 border border-slate-800 rounded-xl text-xs text-slate-200 focus:outline-none focus:ring-2 focus:ring-orange-500 w-56"
          />
        </div>
      </div>

      {/* Overview Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-xs font-mono">
        <div className="bg-slate-900/80 border border-slate-800 p-4 rounded-2xl">
          <div className="text-slate-400 text-[11px] font-sans">活动 Evidence Bundles</div>
          <div className="text-2xl font-bold text-white mt-1">3 组</div>
          <div className="text-[11px] text-emerald-400 font-sans mt-0.5">全量版本指针同步正常</div>
        </div>

        <div className="bg-slate-900/80 border border-slate-800 p-4 rounded-2xl">
          <div className="text-slate-400 text-[11px] font-sans">评论自动去重准确度</div>
          <div className="text-2xl font-bold text-orange-400 mt-1">98.1%</div>
          <div className="text-[11px] text-slate-500 font-sans mt-0.5">多笔记重复评论实体合并</div>
        </div>

        <div className="bg-slate-900/80 border border-slate-800 p-4 rounded-2xl">
          <div className="text-slate-400 text-[11px] font-sans">隐私脱敏与敏感词过滤</div>
          <div className="text-2xl font-bold text-emerald-400 mt-1">100% 合规</div>
          <div className="text-[11px] text-slate-500 font-sans mt-0.5">电话/敏感字段严格掩码</div>
        </div>
      </div>

      {/* Bundle Table */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-2xl overflow-x-auto shadow-xs">
        <table className="w-full text-left text-xs text-slate-300">
          <thead className="bg-slate-950/70 border-b border-slate-800 text-slate-400 uppercase text-[11px] font-mono">
            <tr>
              <th className="p-3.5">Bundle ID / 版本</th>
              <th className="p-3.5">查询家族 (Family ID)</th>
              <th className="p-3.5">条目容量</th>
              <th className="p-3.5">时效窗口</th>
              <th className="p-3.5">去重率</th>
              <th className="p-3.5">脱敏质检</th>
              <th className="p-3.5 text-right">生成时间</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60 font-mono">
            {bundles.map((b) => (
              <tr key={b.bundleId} className="hover:bg-slate-800/30 transition-colors">
                <td className="p-3.5">
                  <div className="font-bold text-white text-xs">{b.bundleId}</div>
                  <div className="text-[10px] text-orange-400">v{b.version}</div>
                </td>

                <td className="p-3.5 text-slate-300 font-sans">{b.familyId}</td>

                <td className="p-3.5">
                  <div>{b.itemCount} 条评论</div>
                  <div className="text-[10px] text-slate-500">
                    小红书: {b.sourcesBreakdown.xhs_pc} / 点评: {b.sourcesBreakdown.dianping}
                  </div>
                </td>

                <td className="p-3.5 text-slate-400">
                  <span className="text-slate-200">{b.freshnessHours}h 前</span>
                </td>

                <td className="p-3.5 text-emerald-400 font-bold">{b.dedupRate}</td>

                <td className="p-3.5">
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-[10px]">
                    <ShieldCheck className="w-3 h-3" />
                    <span>PASSED</span>
                  </span>
                </td>

                <td className="p-3.5 text-right text-slate-500 text-[11px]">{b.createdAt}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
