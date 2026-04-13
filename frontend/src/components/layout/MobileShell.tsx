import { type ReactNode, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { Menu, PenSquare, Search, Heart, Clock, Settings, X } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { useSearchStore } from '@/stores/searchStore'
import { cn } from '@/utils/cn'

const SIDEBAR_ITEMS = [
  { path: '/', label: '搜索', icon: Search },
  { path: '/favorites', label: '收藏', icon: Heart },
  { path: '/history', label: '历史', icon: Clock },
  { path: '/profile', label: '关于', icon: Settings },
] as const

const TITLES: Record<string, string> = {
  '/': '食探',
  '/favorites': '收藏',
  '/history': '历史',
  '/profile': '关于',
}

function IconButton({ onClick, ariaLabel, children }: { onClick?: () => void; ariaLabel: string; children: ReactNode }) {
  return (
    <button
      onClick={onClick}
      aria-label={ariaLabel}
      className="w-10 h-10 grid place-items-center rounded-xl text-foreground active:bg-bg-elev transition-colors"
    >
      {children}
    </button>
  )
}

export function MobileShell({ children }: { children: ReactNode }) {
  const [drawerOpen, setDrawerOpen] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()
  const reset = useSearchStore((s) => s.reset)

  const handleNewChat = () => {
    reset()
    navigate('/')
  }

  const handleNavigate = (path: string) => {
    navigate(path)
    setDrawerOpen(false)
  }

  return (
    <div className="h-dvh flex flex-col max-w-lg mx-auto bg-background overflow-hidden relative">
      <header className="shrink-0 h-14 flex items-center justify-between px-2 relative z-10">
        <IconButton ariaLabel="菜单" onClick={() => setDrawerOpen(true)}>
          <Menu size={22} strokeWidth={2} />
        </IconButton>
        <h1 className="font-semibold text-[17px] text-foreground tracking-tight">
          {TITLES[location.pathname] ?? '食探'}
        </h1>
        <IconButton ariaLabel="新对话" onClick={handleNewChat}>
          <PenSquare size={20} strokeWidth={1.8} />
        </IconButton>
      </header>

      <main className="flex-1 min-h-0 overflow-hidden">{children}</main>

      {/* Sidebar drawer */}
      <AnimatePresence>
        {drawerOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setDrawerOpen(false)}
              className="absolute inset-0 z-40 bg-black/40"
            />
            <motion.aside
              initial={{ x: '-100%' }}
              animate={{ x: 0 }}
              exit={{ x: '-100%' }}
              transition={{ duration: 0.22, ease: [0.32, 0.72, 0, 1] }}
              className="absolute top-0 bottom-0 left-0 z-50 w-[84%] max-w-[320px] bg-bg-elev border-r border-border flex flex-col"
            >
              <div className="flex items-center gap-2 px-3 pt-3 pb-2">
                <IconButton ariaLabel="关闭" onClick={() => setDrawerOpen(false)}>
                  <X size={20} strokeWidth={2} />
                </IconButton>
                <div className="flex-1 h-9 flex items-center px-3 rounded-xl bg-background border border-border text-[13px] text-muted-foreground">
                  搜索对话
                </div>
              </div>

              <div className="px-2 py-1.5">
                <button
                  onClick={() => { handleNewChat(); setDrawerOpen(false) }}
                  className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-[14px] text-foreground active:bg-background transition-colors"
                >
                  <PenSquare size={16} strokeWidth={1.8} />
                  新对话
                </button>
              </div>

              <nav className="flex-1 overflow-y-auto px-2 pt-2">
                <div className="px-3 pb-1.5 text-[11px] uppercase tracking-wider text-muted-foreground">
                  导航
                </div>
                {SIDEBAR_ITEMS.map(({ path, label, icon: Icon }) => {
                  const active = location.pathname === path
                  return (
                    <button
                      key={path}
                      onClick={() => handleNavigate(path)}
                      className={cn(
                        'w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-[14px] transition-colors',
                        active
                          ? 'bg-background text-foreground font-medium'
                          : 'text-foreground active:bg-background'
                      )}
                    >
                      <Icon size={16} strokeWidth={1.8} className="text-muted-foreground" />
                      <span className="flex-1 text-left">{label}</span>
                    </button>
                  )
                })}
              </nav>

              <div className="shrink-0 border-t border-border px-3 py-3 flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-full bg-foreground text-background grid place-items-center text-xs font-bold">
                  食
                </div>
                <div className="flex-1 text-[13px] text-foreground">食探用户</div>
                <IconButton ariaLabel="设置">
                  <Settings size={16} strokeWidth={1.8} />
                </IconButton>
              </div>
            </motion.aside>
          </>
        )}
      </AnimatePresence>
    </div>
  )
}
