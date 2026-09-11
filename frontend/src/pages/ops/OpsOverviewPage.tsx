import React, { useState } from 'react'
import {
  LayoutDashboard,
  AlertTriangle,
  Activity,
  Database,
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
      <div className="flex items-center justify-between pb-4 border-b border-zinc-200/80">
        <div>
          <h1 className="text-xl font-semibold text-zinc-900 tracking-tight flex items-center gap-2">
            <LayoutDashboard className="w-5 h-5 text-[#10a37f]" />
            <span>系统总览与通道健康</span>
          </h1>
          <p className="text-xs text-zinc-500 mt-1">
            监控采集通道健康度、任务执行统计与数据缺口治理
          </p>
        </div>

        <button
          onClick={handleRefresh}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full border border-zinc-200 bg-white hover:bg-zinc-50 text-zinc-700 text-xs font-medium transition-colors shadow-2xs"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? 'animate-spin text-zinc-800' : 'text-zinc-500'}`} />
          <span>刷新数据</span>
        </button>
      </div>

      {/* 1. High Impact Anomalies Banner */}
      <div className="p-4 rounded-2xl bg-amber-50/70 border border-amber-200/80 text-xs text-amber-900 flex items-start gap-3">
        <AlertTriangle className="w-5 h-5 text-amber-600 flex-shrink-0 mt-0.5" />
        <div className="flex-1 space-y-1">
          <div className="font-semibold text-amber-950 text-sm">关注事项：大众点评安全滑块拦截频次增加</div>
          <div className="text-amber-800/90 leading-relaxed">
            最近 1 小时内有 2 起店铺档案抓取触发滑块验证，系统已自动降级为“部分就绪”状态并保留小红书评论证据，未对用户交互造成白屏阻塞。
          </div>
        </div>
      </div>

      {/* 2. Platform Service Readiness */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Xiaohongshu Channel */}
        <div className="bg-white border border-zinc-200 p-5 rounded-2xl space-y-3 shadow-2xs">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="w-7 h-7 rounded-lg bg-zinc-100 text-zinc-800 font-mono font-semibold flex items-center justify-center text-xs">
                XHS
              </div>
              <div>
                <h3 className="font-medium text-sm text-zinc-900">小红书公开评论采集服务 (xhs_pc)</h3>
                <div className="text-[11px] text-zinc-400 font-mono">通道: MCP SSE / HTTP Client</div>
              </div>
            </div>
            <span className="px-2.5 py-0.5 rounded-full bg-emerald-50 text-[#10a37f] border border-emerald-200/60 text-[11px] font-mono font-medium">
              OPERATIONAL
            </span>
          </div>

          <div className="grid grid-cols-3 gap-2 pt-2 border-t border-zinc-100 text-xs text-center">
            <div className="bg-zinc-50/70 p-2.5 rounded-xl border border-zinc-100">
              <div className="text-zinc-500 text-[10px]">连通成功率</div>
              <div className="font-semibold text-zinc-900 font-mono mt-0.5">99.4%</div>
            </div>
            <div className="bg-zinc-50/70 p-2.5 rounded-xl border border-zinc-100">
              <div className="text-zinc-500 text-[10px]">P95 延迟</div>
              <div className="font-semibold text-zinc-900 font-mono mt-0.5">380ms</div>
            </div>
            <div className="bg-zinc-50/70 p-2.5 rounded-xl border border-zinc-100">
              <div className="text-zinc-500 text-[10px]">可用会话号</div>
              <div className="font-semibold text-zinc-900 font-mono mt-0.5">2 / 2</div>
            </div>
          </div>
        </div>

        {/* Dazhong Dianping Channel */}
        <div className="bg-white border border-zinc-200 p-5 rounded-2xl space-y-3 shadow-2xs">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="w-7 h-7 rounded-lg bg-zinc-100 text-zinc-800 font-mono font-semibold flex items-center justify-center text-xs">
                DP
              </div>
              <div>
                <h3 className="font-medium text-sm text-zinc-900">大众点评商户事实服务 (dianping)</h3>
                <div className="text-[11px] text-zinc-400 font-mono">通道: MCP Tool API</div>
              </div>
            </div>
            <span className="px-2.5 py-0.5 rounded-full bg-amber-50 text-amber-700 border border-amber-200/60 text-[11px] font-mono font-medium">
              DEGRADED
            </span>
          </div>

          <div className="grid grid-cols-3 gap-2 pt-2 border-t border-zinc-100 text-xs text-center">
            <div className="bg-zinc-50/70 p-2.5 rounded-xl border border-zinc-100">
              <div className="text-zinc-500 text-[10px]">连通成功率</div>
              <div className="font-semibold text-zinc-900 font-mono mt-0.5">92.1%</div>
            </div>
            <div className="bg-zinc-50/70 p-2.5 rounded-xl border border-zinc-100">
              <div className="text-zinc-500 text-[10px]">P95 延迟</div>
              <div className="font-semibold text-zinc-900 font-mono mt-0.5">640ms</div>
            </div>
            <div className="bg-zinc-50/70 p-2.5 rounded-xl border border-zinc-100">
              <div className="text-zinc-500 text-[10px]">可用会话号</div>
              <div className="font-semibold text-zinc-900 font-mono mt-0.5">1 / 2</div>
            </div>
          </div>
        </div>
      </div>

      {/* 3. Task Status Breakdown */}
      <div className="bg-white border border-zinc-200 p-5 rounded-2xl space-y-4 shadow-2xs">
        <h3 className="font-medium text-sm text-zinc-900 flex items-center gap-2">
          <Activity className="w-4 h-4 text-[#10a37f]" />
          <span>全系统调查任务状态分布 (实时)</span>
        </h3>

        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 text-xs">
          <div className="bg-zinc-50/70 p-3 rounded-xl border border-zinc-200/80">
            <div className="text-zinc-500 text-[11px]">执行中 (Running)</div>
            <div className="text-2xl font-bold font-mono text-zinc-900 mt-1">3</div>
          </div>

          <div className="bg-zinc-50/70 p-3 rounded-xl border border-zinc-200/80">
            <div className="text-zinc-500 text-[11px]">排队中 (Queued)</div>
            <div className="text-2xl font-bold font-mono text-zinc-400 mt-1">0</div>
          </div>

          <div className="bg-zinc-50/70 p-3 rounded-xl border border-zinc-200/80">
            <div className="text-zinc-500 text-[11px]">已完成 (Succeeded)</div>
            <div className="text-2xl font-bold font-mono text-[#10a37f] mt-1">128</div>
          </div>

          <div className="bg-zinc-50/70 p-3 rounded-xl border border-zinc-200/80">
            <div className="text-zinc-500 text-[11px]">部分完成 (Partial)</div>
            <div className="text-2xl font-bold font-mono text-amber-600 mt-1">9</div>
          </div>

          <div className="bg-zinc-50/70 p-3 rounded-xl border border-zinc-200/80">
            <div className="text-zinc-500 text-[11px]">失败 (Failed)</div>
            <div className="text-2xl font-bold font-mono text-red-600 mt-1">1</div>
          </div>
        </div>
      </div>

      {/* 4. Evidence Output & Gap Trends */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-white border border-zinc-200 p-5 rounded-2xl space-y-3 shadow-2xs">
          <div className="flex items-center justify-between">
            <h3 className="font-medium text-sm text-zinc-900 flex items-center gap-2">
              <Database className="w-4 h-4 text-[#10a37f]" />
              <span>证据吞吐与评论提炼分类</span>
            </h3>
            <span className="text-[11px] text-zinc-400 font-mono">今日累计 1,420 条</span>
          </div>

          <div className="space-y-2 text-xs">
            <div className="flex items-center justify-between text-zinc-600">
              <span>小红书正向探店观点</span>
              <span className="font-mono text-[#10a37f] font-medium">842 条 (59.3%)</span>
            </div>
            <div className="w-full bg-zinc-100 h-1.5 rounded-full overflow-hidden">
              <div className="bg-[#10a37f] h-full w-[59%]" />
            </div>

            <div className="flex items-center justify-between text-zinc-600 pt-1">
              <span>反例 / 踩雷评价</span>
              <span className="font-mono text-red-600 font-medium">388 条 (27.3%)</span>
            </div>
            <div className="w-full bg-zinc-100 h-1.5 rounded-full overflow-hidden">
              <div className="bg-red-500 h-full w-[27%]" />
            </div>

            <div className="flex items-center justify-between text-zinc-600 pt-1">
              <span>中立描述 / 争议事实</span>
              <span className="font-mono text-amber-600 font-medium">190 条 (13.4%)</span>
            </div>
            <div className="w-full bg-zinc-100 h-1.5 rounded-full overflow-hidden">
              <div className="bg-amber-500 h-full w-[13%]" />
            </div>
          </div>
        </div>

        {/* Failure Categories */}
        <div className="bg-white border border-zinc-200 p-5 rounded-2xl space-y-3 shadow-2xs">
          <h3 className="font-medium text-sm text-zinc-900 flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-amber-500" />
            <span>异常与数据缺口归类</span>
          </h3>

          <div className="space-y-2 text-xs">
            <div className="p-3 rounded-xl bg-zinc-50/70 border border-zinc-200/80 flex items-center justify-between">
              <div>
                <span className="font-medium text-zinc-900 font-mono">DP_SLIDER_CAPTCHA</span>
                <div className="text-[11px] text-zinc-500">大众点评反爬滑块拦截</div>
              </div>
              <span className="font-mono text-amber-600 font-semibold">5 次</span>
            </div>

            <div className="p-3 rounded-xl bg-zinc-50/70 border border-zinc-200/80 flex items-center justify-between">
              <div>
                <span className="font-medium text-zinc-900 font-mono">XHS_RATE_LIMIT</span>
                <div className="text-[11px] text-zinc-500">小红书单 IP 访问频次限制</div>
              </div>
              <span className="font-mono text-zinc-500 font-semibold">1 次</span>
            </div>

            <div className="p-3 rounded-xl bg-zinc-50/70 border border-zinc-200/80 flex items-center justify-between">
              <div>
                <span className="font-medium text-zinc-900 font-mono">PROFILE_NOT_FOUND</span>
                <div className="text-[11px] text-zinc-500">小众新店大众点评未收录</div>
              </div>
              <span className="font-mono text-zinc-500 font-semibold">4 次</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

