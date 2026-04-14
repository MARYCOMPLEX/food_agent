import { type ReactNode } from 'react'

interface MobilePageProps {
  subtitle?: string
  action?: ReactNode
  children: ReactNode
}

export function MobilePage({ subtitle, action, children }: MobilePageProps) {
  return (
    <div className="flex flex-col h-full">
      {(subtitle || action) && (
        <div className="shrink-0 flex items-center justify-between px-5 pt-3 pb-2">
          {subtitle && <p className="text-xs text-muted-foreground">{subtitle}</p>}
          {action && <div className="shrink-0">{action}</div>}
        </div>
      )}
      <div
        className="flex-1 min-h-0 overflow-y-auto overscroll-contain"
        style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
      >
        {children}
      </div>
    </div>
  )
}
