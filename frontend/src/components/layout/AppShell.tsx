import { type ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import { Search, Heart, Clock, User } from 'lucide-react'
import { cn } from '@/utils/cn'

const tabs = [
  { path: '/', label: '探索', icon: Search },
  { path: '/favorites', label: '收藏', icon: Heart },
  { path: '/history', label: '历史', icon: Clock },
  { path: '/profile', label: '我的', icon: User },
] as const

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-col min-h-dvh max-w-lg mx-auto bg-background">
      <main className="flex-1 pb-[72px]">{children}</main>

      <nav className="fixed bottom-0 left-1/2 -translate-x-1/2 w-full max-w-lg z-50 border-t bg-card/95 backdrop-blur-lg">
        <div className="grid grid-cols-4 h-[72px]">
          {tabs.map(({ path, label, icon: Icon }) => (
            <NavLink
              key={path}
              to={path}
              className={({ isActive }) =>
                cn(
                  'flex flex-col items-center justify-center gap-1 transition-colors',
                  isActive ? 'text-primary' : 'text-muted-foreground hover:text-foreground'
                )
              }
            >
              {({ isActive }) => (
                <>
                  <Icon
                    size={20}
                    strokeWidth={isActive ? 2.5 : 1.5}
                    className="transition-all"
                  />
                  <span className={cn('text-[10px]', isActive && 'font-semibold')}>
                    {label}
                  </span>
                </>
              )}
            </NavLink>
          ))}
        </div>
      </nav>
    </div>
  )
}
