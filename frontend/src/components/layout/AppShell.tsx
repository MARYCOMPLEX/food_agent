import { type ReactNode } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { cn } from '../../utils/cn'

const tabs = [
  { path: '/', label: '探味', icon: '🔍' },
  { path: '/favorites', label: '收藏', icon: '♡' },
  { path: '/history', label: '足迹', icon: '📜' },
  { path: '/profile', label: '我的', icon: '👤' },
]

export function AppShell({ children }: { children: ReactNode }) {
  const location = useLocation()
  const isSearch = location.pathname === '/'

  return (
    <div className="flex flex-col min-h-[100dvh] max-w-lg mx-auto relative">
      {/* Header - hidden on search page for immersion */}
      {!isSearch && (
        <header className="sticky top-0 z-40 bg-cream/80 backdrop-blur-md border-b border-border px-5 py-3">
          <h1 className="font-display text-lg font-semibold text-ink tracking-wide">
            <span className="text-ember">食</span>探
          </h1>
        </header>
      )}

      {/* Main content */}
      <main className="flex-1 pb-20">{children}</main>

      {/* Bottom tab bar */}
      <nav className="fixed bottom-0 left-1/2 -translate-x-1/2 w-full max-w-lg z-50 bg-cream/90 backdrop-blur-lg border-t border-border">
        <div className="flex items-center justify-around h-16 px-2">
          {tabs.map((tab) => (
            <NavLink
              key={tab.path}
              to={tab.path}
              className={({ isActive }) =>
                cn(
                  'flex flex-col items-center gap-0.5 px-4 py-1.5 rounded-xl transition-all duration-300',
                  isActive
                    ? 'text-ember scale-105'
                    : 'text-muted hover:text-ink'
                )
              }
            >
              {({ isActive }) => (
                <>
                  <span className={cn(
                    'text-xl transition-transform duration-300',
                    isActive && 'scale-110'
                  )}>
                    {tab.icon}
                  </span>
                  <span className={cn(
                    'text-[10px] font-medium tracking-wider',
                    isActive && 'font-bold'
                  )}>
                    {tab.label}
                  </span>
                  {isActive && (
                    <span className="absolute -bottom-0 w-6 h-0.5 bg-ember rounded-full" />
                  )}
                </>
              )}
            </NavLink>
          ))}
        </div>
      </nav>
    </div>
  )
}
