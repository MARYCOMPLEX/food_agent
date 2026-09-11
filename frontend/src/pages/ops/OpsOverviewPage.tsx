import React, { useState } from 'react'
import {
  LayoutDashboard,
  AlertTriangle,
  CheckCircle2,
  Activity,
  Server,
  Database,
  ArrowUpRight,
  TrendingUp,
  Clock,
  RefreshCw,
} from 'lucide-react'

export function OpsOverviewPage() {
  const [refreshing, setRefreshing] = useState<boolean>(false)

  const handleRefresh = () => {
    setRefreshing(true)
    setTimeout(() => setRefreshing(false), 800)
  }

  return (
    <div className="space-y-6">
      {/* Title & Refresh */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white tracking-tight flex items-center gap-2">
            <LayoutDashboard className="w-5 h-5 text-orange-500" />
            <span>系统总览与健康状态</span>
          </h1>
          <p className="text-xs text-slate-400 mt-0.5">
            聚合监控平台通道、任务生命周期、证据吞吐量与高影响异常
          </p>
        </div>

        <button
          onClick={handleRefresh}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium transition-colors"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? 'animate-spin text-orange-500' : ''}`} />
          <span>刷新指标</span>
        </button>
      </div>

      {/* 1. High Impact Anomalies Banner (Section 24.2 item 1) */}
      <div className="p-4 rounded-2xl bg-amber-500/10 border border-amber-500/30 text-xs text-amber-300 flex items-start gap-3">
        <AlertTriangle className="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5" />
        <div className="flex-1 space-y-1">
          <div className="font-semibold text-amber-200 text-sm">关注事项：大众点评二次验证拦截频次略微上升</div>
          <div className="text-amber-300/80 leading-relaxed">
            最近 1 小时内有 2 起店铺档案查询触发大众点评安全滑块验证，系统已自动进入“部分完成”状态并降级保留小红书评论证据，未对用户造成白屏影响。
          </div>
        </div>
      </div>

      {/* 2. Platform Service Readiness (Section 24.2 item 2) */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Xiaohongshu Channel */}
        <div className="bg-slate-900/80 border border-slate-800 p-5 rounded-2xl space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-lg bg-red-500/10 text-red-400 border border-red-500/20 flex items-center justify-center font-bold text-xs">
                RED
              </div>
              <div>
                <h3 className="font-semibold text-sm text-white">小红书评论采集服务 (xhs_pc)</h3>
                <div className="text-[11px] text-slate-400 font-mono">通道: MCP SSE / HTTP</div>
              </div>
            </div>
            <span className="px-2.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-[11px] font-mono">
              HEALTHY
            </span>
          </div>

          <div className="grid grid-cols-3 gap-2 pt-2 border-t border-slate-800/80 text-xs text-center">
            <div className="bg-slate-950/60 p-2.5 rounded-xl">
              <div className="text-slate-400 text-[10px]">连通成功率</div>
              <div className="font-bold text-emerald-400 font-mono mt-0.5">99.4%</div>
            </div>
            <div className="bg-slate-950/60 p-2.5 rounded-xl">
              <div className="text-slate-400 text-[10px]">P95 延迟</div>
              <div className="font-bold text-slate-200 font-mono mt-0.5">380ms</div>
            </div>
            <div className="bg-slate-950/60 p-2.5 rounded-xl">
              <div className="text-slate-400 text-[10px]">可用账号数</div>
              <div className="font-bold text-slate-200 font-mono mt-0.5">2 / 2</div>
            </div>
          </div>
        </div>

        {/* Dazhong Dianping Channel */}
        <div className="bg-slate-900/80 border border-slate-800 p-5 rounded-2xl space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-lg bg-orange-500/10 text-orange-400 border border-orange-500/20 flex items-center justify-center font-bold text-xs">
                DP
              </div>
              <div>
                <h3 className="font-semibold text-sm text-white">大众点评事实档案服务 (dianping)</h3>
                <div className="text-[11px] text-slate-400 font-mono">通道: MCP Tool API</div>
              </div>
            </div>
            <span className="px-2.5 py-0.5 rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20 text-[11px] font-mono">
              DEGRADED (部分限流)
            </span>
          </div>

          <div className="grid grid-cols-3 gap-2 pt-2 border-t border-slate-800/80 text-xs text-center">
            <div className="bg-slate-950/60 p-2.5 rounded-xl">
              <div className="text-slate-400 text-[10px]">连通成功率</div>
              <div className="font-bold text-blue-400 font-mono mt-0.5">92.1%</div>
            </div>
            <div className="bg-slate-950/60 p-2.5 rounded-xl">
              <div className="text-slate-400 text-[10px]">P95 延迟</div>
              <div className="font-bold text-slate-200 font-mono mt-0.5">640ms</div>
            </div>
            <div className="bg-slate-950/60 p-2.5 rounded-xl">
              <div className="text-slate-400 text-[10px]">可用账号数</div>
              <div className="font-bold text-slate-200 font-mono mt-0.5">1 / 2</div>
            </div>
          </div>
        </div>
      </div>

      {/* 3. Task Status Breakdown (Section 24.2 item 3) */}
      <div className="bg-slate-900/80 border border-slate-800 p-5 rounded-2xl space-y-4">
        <h3 className="font-semibold text-sm text-white flex items-center gap-2">
          <Activity className="w-4 h-4 text-orange-500" />
          <span>全系统调查任务状态分布 (实时)</span>
        </h3>

        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 text-xs">
          <div className="bg-slate-950/80 p-3 rounded-xl border border-slate-800/80">
            <div className="text-slate-400 text-[11px]">运行中 (Running)</div>
            <div className="text-xl font-bold font-mono text-orange-400 mt-1">3</div>
          </div>

          <div className="bg-slate-950/80 p-3 rounded-xl border border-slate-800/80">
            <div className="text-slate-400 text-[11px]">排队中 (Queued)</div>
            <div className="text-xl font-bold font-mono text-slate-300 mt-1">0</div>
          </div>

          <div className="bg-slate-950/80 p-3 rounded-xl border border-slate-800/80">
            <div className="text-slate-400 text-[11px]">已完成 (Succeeded)</div>
            <div className="text-xl font-bold font-mono text-emerald-400 mt-1">128</div>
          </div>

          <div className="bg-slate-950/80 p-3 rounded-xl border border-slate-800/80">
            <div className="text-slate-400 text-[11px]">部分完成 (Partial)</div>
            <div className="text-xl font-bold font-mono text-blue-400 mt-1">9</div>
          </div>

          <div className="bg-slate-950/80 p-3 rounded-xl border border-slate-800/80">
            <div className="text-slate-400 text-[11px]">失败 / 阻塞 (Failed)</div>
            <div className="text-xl font-bold font-mono text-rose-400 mt-1">1</div>
          </div>
        </div>
      </div>

      {/* 4. Evidence Output & Gap Trends */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-slate-900/80 border border-slate-800 p-5 rounded-2xl space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="font-semibold text-sm text-white flex items-center gap-2">
              <Database className="w-4 h-4 text-orange-500" />
              <span>证据吞吐与评论提炼趋势</span>
            </h3>
            <span className="text-[11px] text-slate-400 font-mono">今日累计 1,420 条</span>
          </div>

          <div className="space-y-2 text-xs">
            <div className="flex items-center justify-between text-slate-400">
              <span>小红书高赞评论正向观点</span>
              <span className="font-mono text-emerald-400">842 条 (59.3%)</span>
            </div>
            <div className="w-full bg-slate-950 h-1.5 rounded-full overflow-hidden">
              <div className="bg-emerald-500 h-full w-[59%]" />
            </div>

            <div className="flex items-center justify-between text-slate-400 pt-1">
              <span>反例 / 踩雷点 / 负向评价</span>
              <span className="font-mono text-rose-400">388 条 (27.3%)</span>
            </div>
            <div className="w-full bg-slate-950 h-1.5 rounded-full overflow-hidden">
              <div className="bg-rose-500 h-full w-[27%]" />
            </div>

            <div className="flex items-center justify-between text-slate-400 pt-1">
              <span>中立事实 / 分店争议描述</span>
              <span className="font-mono text-amber-400">190 条 (13.4%)</span>
            </div>
            <div className="w-full bg-slate-950 h-1.5 rounded-full overflow-hidden">
              <div className="bg-amber-500 h-full w-[13%]" />
            </div>
          </div>
        </div>

        {/* Failure Categories */}
        <div className="bg-slate-900/80 border border-slate-800 p-5 rounded-2xl space-y-3">
          <h3 className="font-semibold text-sm text-white flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-orange-500" />
            <span>异常与数据缺口归类</span>
          </h3>

          <div className="space-y-2 text-xs">
            <div className="p-2.5 rounded-xl bg-slate-950/60 border border-slate-800/80 flex items-center justify-between">
              <div>
                <span className="font-medium text-slate-200">DP_SLIDER_CAPTCHA</span>
                <div className="text-[11px] text-slate-500">大众点评反爬滑块拦截</div>
              </div>
              <span className="font-mono text-amber-400 font-bold">5 次</span>
            </div>

            <div className="p-2.5 rounded-xl bg-slate-950/60 border border-slate-800/80 flex items-center justify-between">
              <div>
                <span className="font-medium text-slate-200">XHS_RATE_LIMIT</span>
                <div className="text-[11px] text-slate-500">小红书单 IP 访问限速</div>
              </div>
              <span className="font-mono text-slate-400 font-bold">1 次</span>
            </div>

            <div className="p-2.5 rounded-xl bg-slate-950/60 border border-slate-800/80 flex items-center justify-between">
              <div>
                <span className="font-medium text-slate-200">PROFILE_NOT_FOUND</span>
                <div className="text-[11px] text-slate-500">新开小店尚未在大众点评建档</div>
              </div>
              <span className="font-mono text-slate-400 font-bold">4 次</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
