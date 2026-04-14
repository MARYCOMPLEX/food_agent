import { type ReactNode, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { Menu, PenSquare, Search, Heart, Clock, Settings } from 'lucide-react'
import { useSearchStore } from '@/stores/searchStore'
import { Button } from '@/components/ui/button'
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Separator } from '@/components/ui/separator'
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

  const title = TITLES[location.pathname] ?? '食探'

  return (
    <div className="h-dvh flex flex-col max-w-lg mx-auto bg-background overflow-hidden relative">
      <header
        className="shrink-0 flex items-center justify-between px-2 h-14 border-b border-border/60 bg-background/90 backdrop-blur supports-[backdrop-filter]:bg-background/70"
        style={{ paddingTop: 'env(safe-area-inset-top)' }}
      >
        <Button variant="ghost" size="icon" aria-label="菜单" onClick={() => setDrawerOpen(true)}>
          <Menu className="size-5" />
        </Button>
        <h1 className="font-semibold text-base text-foreground tracking-tight">{title}</h1>
        <Button variant="ghost" size="icon" aria-label="新对话" onClick={handleNewChat}>
          <PenSquare className="size-5" />
        </Button>
      </header>

      <main className="flex-1 min-h-0 overflow-hidden">{children}</main>

      <Sheet open={drawerOpen} onOpenChange={setDrawerOpen}>
        <SheetContent
          side="left"
          hideClose
          className="w-[84%] max-w-[320px] flex flex-col p-0 bg-bg-elev"
        >
          <SheetHeader className="px-4 pt-5 pb-3" style={{ paddingTop: 'calc(env(safe-area-inset-top) + 1.25rem)' }}>
            <SheetTitle className="text-left">食探</SheetTitle>
          </SheetHeader>

          <div className="px-3 pb-2">
            <Button
              variant="outline"
              className="w-full justify-start gap-2 rounded-xl"
              onClick={handleNewChat}
            >
              <PenSquare className="size-4" />
              新对话
            </Button>
          </div>

          <Separator className="bg-border/60" />

          <nav className="flex-1 overflow-y-auto px-2 py-2">
            <p className="px-3 pb-1.5 text-[11px] uppercase tracking-wider text-muted-foreground">导航</p>
            {NAV_ITEMS.map(({ path, label, icon: Icon }) => {
              const active = location.pathname === path
              return (
                <button
                  key={path}
                  onClick={() => handleNavigate(path)}
                  className={cn(
                    'w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm transition-colors',
                    active
                      ? 'bg-background text-foreground font-medium shadow-sm'
                      : 'text-foreground hover:bg-background/60 active:bg-background'
                  )}
                >
                  <Icon className="size-4 text-muted-foreground" />
                  <span className="flex-1 text-left">{label}</span>
                </button>
              )
            })}
          </nav>

          <Separator className="bg-border/60" />

          <div
            className="shrink-0 px-3 py-3 flex items-center gap-2.5"
            style={{ paddingBottom: 'calc(env(safe-area-inset-bottom) + 0.75rem)' }}
          >
            <Avatar className="size-8">
              <AvatarFallback>食</AvatarFallback>
            </Avatar>
            <div className="flex-1 text-sm text-foreground truncate">食探用户</div>
            <Button variant="ghost" size="icon" aria-label="设置" onClick={() => handleNavigate('/profile')}>
              <Settings className="size-4" />
            </Button>
          </div>
        </SheetContent>
      </Sheet>
    </div>
  )
}
