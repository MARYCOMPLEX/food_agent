import { type ReactNode } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { PenSquare, Search, Heart, Clock, Settings } from 'lucide-react'
import { useSearchStore } from '@/stores/searchStore'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

interface NavItem {
  path: string
  label: string
  icon: typeof Search
}

const NAV_ITEMS: readonly NavItem[] = [
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

interface MobileShellProps {
  children: ReactNode
}

export function MobileShell({ children }: MobileShellProps) {
  const navigate = useNavigate()
  const location = useLocation()
  const reset = useSearchStore((s) => s.reset)

  const handleNewChat = () => {
    reset()
    navigate('/')
  }

  const isSearchPage = location.pathname === '/'
  const title = TITLES[location.pathname] ?? '食探'

  return (
    <div className="h-dvh flex flex-col max-w-lg mx-auto bg-background overflow-hidden relative">
      <header
        className="shrink-0 flex items-center justify-between px-2 h-14 border-b border-border/60 bg-background/90 backdrop-blur supports-[backdrop-filter]:bg-background/70"
        style={{ paddingTop: 'env(safe-area-inset-top)' }}
      >
        <div className="size-10" />
        <h1 className="font-semibold text-base text-foreground tracking-tight">{title}</h1>
        <Button variant="ghost" size="icon" aria-label="新对话" onClick={handleNewChat}>
          <PenSquare className="size-5" />
        </Button>
      </header>

      <main className="flex-1 min-h-0 overflow-hidden">{children}</main>

      {!isSearchPage && (
        <nav
          className="shrink-0 flex items-center justify-around border-t border-border/60 bg-background/90 backdrop-blur supports-[backdrop-filter]:bg-background/70"
          style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
        >
          {NAV_ITEMS.map(({ path, label, icon: Icon }) => {
            const isActive = location.pathname === path
            return (
              <button
                key={path}
                type="button"
                onClick={() => navigate(path)}
                className={cn(
                  'flex flex-col items-center gap-0.5 px-3 py-2 min-w-[4rem] transition-colors',
                  isActive
                    ? 'text-brand'
                    : 'text-muted-foreground active:text-foreground',
                )}
              >
                <Icon className="size-5" />
                <span className="text-[10px] leading-tight">{label}</span>
              </button>
            )
          })}
        </nav>
      )}
    </div>
  )
}
