import React, { useState, useEffect } from 'react'
import { Outlet, NavLink, useLocation, useNavigate } from 'react-router-dom'
import {
  Compass,
  History,
  Bookmark,
  Shield,
  User,
  Activity,
  AlertTriangle,
  Wifi,
  WifiOff,
  Server,
  ArrowUpRight,
  UtensilsCrossed,
} from 'lucide-react'
import { platformAccountsApi } from '../features/platform-accounts/api/platformAccountsApi'
import { QrLoginModal } from '../components/auth/QrLoginModal'
import type { PlatformAccount } from '../shared/contracts'

export function UserShell() {
  const location = useLocation()
  const navigate = useNavigate()
  const [accounts, setAccounts] = useState<PlatformAccount[]>([])
  const [loginModalPlatform, setLoginModalPlatform] = useState<'xhs_pc' | 'dianping' | null>(null)
  const [isOnline, setIsOnline] = useState<boolean>(navigator.onLine)

  // Load account status
  useEffect(() => {
    const local = platformAccountsApi.getLocalAccounts()
    setAccounts(local)

    const handleOnline = () => setIsOnline(true)
    const handleOffline = () => setIsOnline(false)
    window.addEventListener('online', handleOnline)
    window.addEventListener('offline', handleOffline)

    return () => {
      window.removeEventListener('online', handleOnline)
      window.removeEventListener('offline', handleOffline)
    }
  }, [])

  // Check if any primary account is degraded/expired
  const degradedAccount = accounts.find(
    (a) => a.status === 'expired' || a.status === 'degraded' || a.health === 'critical',
  )

  const navItems = [
    { path: '/app/explore', label: '美食探索', icon: Compass },
    { path: '/app/history', label: '调查历史', icon: History },
    { path: '/app/favorites', label: '我的收藏', icon: Bookmark },
    { path: '/app/accounts', label: '平台账号', icon: Shield },
    { path: '/app/me', label: '偏好记忆', icon: User },
  ]

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 flex flex-col font-sans">
      {/* Top Warning Banner if an account is degraded */}
      {degradedAccount && (
        <div className="bg-amber-500/10 border-b border-amber-500/20 px-4 py-2 text-xs text-amber-900 flex items-center justify-between">
          <div className="flex items-center gap-2 max-w-4xl mx-auto w-full">
            <AlertTriangle className="w-4 h-4 text-amber-600 flex-shrink-0" />
            <span className="flex-1">
              {degradedAccount.platform === 'xhs_pc'
                ? '小红书账号授权已过期，可能影响评论深度采集。'
                : '大众点评账号需要验证，可能影响到店资料补充。'}
            </span>
            <button
              onClick={() => setLoginModalPlatform(degradedAccount.platform as any)}
              className="px-2.5 py-1 rounded bg-amber-600 hover:bg-amber-700 text-white font-medium transition-colors shadow-xs"
            >
              一键重新扫码登录
            </button>
          </div>
        </div>
      )}

      {/* Offline Alert */}
      {!isOnline && (
        <div className="bg-rose-500/10 border-b border-rose-500/20 px-4 py-2 text-xs text-rose-800 flex items-center justify-center gap-2">
          <WifiOff className="w-4 h-4 text-rose-600" />
          <span>网络连接已中断，当前已保留最新调查结果，正在尝试自动恢复...</span>
        </div>
      )}

      {/* Top Header */}
      <header className="sticky top-0 z-40 bg-white/90 backdrop-blur-md border-b border-slate-200/80">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 h-14 flex items-center justify-between">
          {/* Brand */}
          <div className="flex items-center gap-6">
            <NavLink to="/app/explore" className="flex items-center gap-2.5 group">
              <div className="w-8 h-8 rounded-xl bg-orange-600 text-white flex items-center justify-center shadow-md shadow-orange-600/20 group-hover:scale-105 transition-transform">
                <UtensilsCrossed className="w-4 h-4" />
              </div>
              <div className="flex flex-col">
                <span className="font-bold text-base tracking-tight text-slate-900 flex items-center gap-1.5">
                  Food Agent
                  <span className="text-[10px] font-normal px-1.5 py-0.5 rounded bg-orange-100 text-orange-700 font-mono">
                    PRO
                  </span>
                </span>
                <span className="text-[10px] text-slate-400 font-medium -mt-1 hidden sm:inline">真实评论证据驱动</span>
              </div>
            </NavLink>

            {/* Desktop Navigation */}
            <nav className="hidden md:flex items-center gap-1">
              {navItems.map((item) => {
                const Icon = item.icon
                return (
                  <NavLink
                    key={item.path}
                    to={item.path}
                    className={({ isActive }) =>
                      `flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-medium transition-colors ${
                        isActive
                          ? 'bg-slate-100 text-slate-900 font-semibold'
                          : 'text-slate-500 hover:text-slate-900 hover:bg-slate-50'
                      }`
                    }
                  >
                    <Icon className="w-3.5 h-3.5" />
                    <span>{item.label}</span>
                  </NavLink>
                )
              })}
            </nav>
          </div>

          {/* Right Header Actions */}
          <div className="flex items-center gap-3">
            {/* Live Connection Dot */}
            <div className="flex items-center gap-1.5 text-xs text-slate-500 hidden sm:flex">
              <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
              <span className="text-[11px] text-slate-400 font-mono">服务正常就绪</span>
            </div>

            {/* Switch to Ops Management Portal */}
            <NavLink
              to="/ops"
              className="inline-flex items-center gap-1 px-3 py-1.5 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-medium transition-colors"
              title="进入内部运维观测与配置端"
            >
              <Server className="w-3.5 h-3.5" />
              <span>运维管控台</span>
              <ArrowUpRight className="w-3 h-3 text-slate-400" />
            </NavLink>
          </div>
        </div>
      </header>

      {/* Main Page Area */}
      <main className="flex-1 max-w-7xl mx-auto w-full px-4 sm:px-6 py-6 pb-20 md:pb-6">
        <Outlet />
      </main>

      {/* Mobile Bottom Navigation Bar */}
      <div className="md:hidden fixed bottom-0 left-0 right-0 z-40 bg-white/95 backdrop-blur-md border-t border-slate-200 flex items-center justify-around py-2 px-1">
        {navItems.map((item) => {
          const Icon = item.icon
          const isActive = location.pathname.startsWith(item.path)
          return (
            <NavLink
              key={item.path}
              to={item.path}
              className={`flex flex-col items-center gap-1 px-3 py-1 rounded-xl text-[11px] transition-colors ${
                isActive ? 'text-orange-600 font-semibold' : 'text-slate-400 hover:text-slate-700'
              }`}
            >
              <Icon className="w-4 h-4" />
              <span>{item.label}</span>
            </NavLink>
          )
        })}
      </div>

      {/* Global QR Login Modal */}
      {loginModalPlatform && (
        <QrLoginModal
          isOpen={true}
          platform={loginModalPlatform}
          onClose={() => setLoginModalPlatform(null)}
          onSuccess={() => {
            setAccounts(platformAccountsApi.getLocalAccounts())
            setLoginModalPlatform(null)
          }}
        />
      )}
    </div>
  )
}
