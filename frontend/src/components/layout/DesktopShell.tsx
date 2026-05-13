import { type ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import { Search, Heart, Clock, Info } from 'lucide-react'
import { cn } from '@/utils/cn'

interface NavItem {
  to: string
  label: string
  icon: typeof Search
}

const NAV_ITEMS: readonly NavItem[] = [
  { to: '/', label: '探索', icon: Search },
  { to: '/favorites', label: '收藏', icon: Heart },
  { to: '/history', label: '历史', icon: Clock },
  { to: '/profile', label: '关于', icon: Info },
] as const

interface DesktopShellProps {
  children: ReactNode
}

export function DesktopShell({ children }: DesktopShellProps) {
  return (
    <div className="flex min-h-dvh bg-[#faf9f7]">
      <aside className="w-[200px] shrink-0 border-r border-[#e7e5e4] bg-[#faf9f7]">
        <div className="px-4 pt-5 pb-6 font-serif text-lg font-bold text-[#c2410c]">食探</div>
        <nav className="flex flex-col gap-1 px-2">
          {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors',
                  isActive
                    ? 'bg-[#f5f3f0] font-semibold text-[#c2410c]'
                    : 'text-[#57534e] hover:bg-[#f5f3f0]/60'
                )
              }
            >
              <Icon size={16} strokeWidth={1.8} />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="flex-1 overflow-auto p-6">
        <div className="mx-auto max-w-[960px]">{children}</div>
      </main>
    </div>
  )
}
