import React from 'react'
import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard,
  Server,
  Activity,
  Database,
  Cpu,
  ArrowLeft,
  CheckCircle2,
  Sparkles,
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
    <div className="min-h-screen bg-[#fafafa] text-zinc-900 flex flex-col font-sans">
      {/* Top Header - OpenAI Platform Style */}
      <header className="sticky top-0 z-40 bg-white border-b border-zinc-200/80 h-14 flex items-center justify-between px-4 sm:px-6 shadow-2xs">
        <div className="flex items-center gap-5">
          <button
            onClick={() => navigate('/')}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full border border-zinc-200 hover:bg-zinc-100 text-zinc-700 text-xs font-medium transition-colors"
            title="返回对话工作台"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            <span>返回对话端</span>
          </button>

          <div className="flex items-center gap-2.5">
            <div className="w-6 h-6 rounded-md bg-[#10a37f] text-white flex items-center justify-center font-bold">
              <Sparkles className="w-3.5 h-3.5" />
            </div>
            <span className="font-semibold text-sm text-zinc-900 tracking-tight">
              Food Agent <span className="text-zinc-500 font-normal">Platform</span>
            </span>
            <span className="px-2 py-0.5 rounded-full bg-zinc-100 border border-zinc-200 text-zinc-600 font-mono text-[10px]">
              ENV: PROD
            </span>
          </div>
        </div>

        {/* Global System Readiness Indicator */}
        <div className="flex items-center gap-4 text-xs">
          <div className="flex items-center gap-1.5 text-[#10a37f] font-mono text-[11px]">
            <CheckCircle2 className="w-3.5 h-3.5" />
            <span>ALL SYSTEMS OPERATIONAL</span>
          </div>

          <div className="h-3 w-px bg-zinc-200 hidden sm:block" />

          <div className="text-zinc-500 text-[11px] font-mono hidden sm:block">
            MCP TOOLS: 14 DISCOVERED / 12 ACTIVE
          </div>
        </div>
      </header>

      {/* Body with Sidebar & Content */}
      <div className="flex-1 flex flex-col md:flex-row">
        {/* Sidebar */}
        <aside className="w-full md:w-60 bg-[#fafafa] border-r border-zinc-200/80 p-4 space-y-2 flex-shrink-0">
          <div className="text-[10px] font-medium uppercase tracking-wider text-zinc-400 px-3 mb-2">
            管理与观测
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
                    `flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-medium transition-all ${
                      isActive
                        ? 'bg-white text-zinc-900 font-semibold shadow-2xs border border-zinc-200/80'
                        : 'text-zinc-600 hover:text-zinc-900 hover:bg-zinc-200/50'
                    }`
                  }
                >
                  <Icon className="w-4 h-4" />
                  <span>{item.label}</span>
                </NavLink>
              )
            })}
          </nav>

          <div className="pt-6 mt-6 border-t border-zinc-200/80 px-3 text-[11px] text-zinc-400 space-y-1">
            <div className="font-medium text-zinc-600">合规审计安全声明</div>
            <p className="leading-relaxed text-[10px]">
              敏感身份凭证与 Cookie 经由沙箱脱敏存储，所有调用日志遵循最小化审计原则。
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

