import React, { useState } from 'react'
import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard,
  Server,
  Activity,
  Database,
  Cpu,
  ArrowLeft,
  ShieldCheck,
  AlertTriangle,
  CheckCircle2,
  Sliders,
} from 'lucide-react'

export function OpsShell() {
  const navigate = useNavigate()

  const opsNavItems = [
    { path: '/ops', label: '系统总览', icon: LayoutDashboard, exact: true },
    { path: '/ops/services', label: '服务与工具目录', icon: Server },
    { path: '/ops/tasks', label: '任务执行观测', icon: Activity },
    { path: '/ops/evidence', label: '证据数据观测', icon: Database },
    { path: '/ops/governance', label: '模型与策略治理', icon: Cpu },
  ]

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      {/* Top Ops Global Header */}
      <header className="sticky top-0 z-40 bg-slate-900/90 backdrop-blur-md border-b border-slate-800 h-14 flex items-center justify-between px-4 sm:px-6">
        <div className="flex items-center gap-6">
          <button
            onClick={() => navigate('/app/explore')}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium transition-colors"
            title="返回用户探索端"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            <span>用户端</span>
          </button>

          <div className="flex items-center gap-2.5">
            <span className="font-bold text-sm text-white tracking-wide">
              FOOD AGENT <span className="text-orange-500 font-mono">OPS CONSOLE</span>
            </span>
            <span className="px-2 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 font-mono text-[10px]">
              ENV: PRODUCTION
            </span>
          </div>
        </div>

        {/* Global System Readiness Indicator */}
        <div className="flex items-center gap-4 text-xs">
          <div className="flex items-center gap-1.5 text-emerald-400 font-mono text-[11px]">
            <CheckCircle2 className="w-3.5 h-3.5" />
            <span>READINESS: 100% READY</span>
          </div>

          <div className="h-3 w-px bg-slate-800 hidden sm:block" />

          <div className="text-slate-400 text-[11px] font-mono hidden sm:block">
            MCP TOOLS: 14 DISCOVERED / 12 ACTIVE
          </div>
        </div>
      </header>

      {/* Body with Sidebar & Content */}
      <div className="flex-1 flex flex-col md:flex-row">
        {/* Sidebar */}
        <aside className="w-full md:w-60 bg-slate-900/50 border-r border-slate-800/80 p-4 space-y-2 flex-shrink-0">
          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500 px-3 mb-2">
            观测与运营中台
          </div>

          <nav className="space-y-1">
            {opsNavItems.map((item) => {
              const Icon = item.icon
              return (
                <NavLink
                  key={item.path}
                  to={item.path}
                  end={item.exact}
                  className={({ isActive }) =>
                    `flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-medium transition-colors ${
                      isActive
                        ? 'bg-orange-600 text-white font-semibold shadow-md shadow-orange-600/20'
                        : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
                    }`
                  }
                >
                  <Icon className="w-4 h-4" />
                  <span>{item.label}</span>
                </NavLink>
              )
            })}
          </nav>

          <div className="pt-6 mt-6 border-t border-slate-800/80 px-3 text-[11px] text-slate-500 space-y-1">
            <div className="font-semibold text-slate-400">合规审计安全提示</div>
            <p className="leading-relaxed text-[10px]">
              敏感认证头与 Cookie 自动过滤，所有诊断日志遵从数据最小化原则。
            </p>
          </div>
        </aside>

        {/* Content Area */}
        <main className="flex-1 p-6 overflow-y-auto max-w-7xl">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
