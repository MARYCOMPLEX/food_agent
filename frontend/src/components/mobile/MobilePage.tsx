import { type ReactNode } from 'react'

interface Props {
  subtitle?: string
  action?: ReactNode
  children: ReactNode
}

/**
 * Mobile content page. Used inside MobileShell's main area.
 * The top bar in MobileShell already shows the page title; this component
 * provides an optional subtitle row and scrollable content area.
 */
export function MobilePage({ subtitle, action, children }: Props) {
  return (
    <div className="flex flex-col h-full">
      {(subtitle || action) && (
        <div className="shrink-0 flex items-center justify-between px-5 pt-4 pb-2">
          {subtitle && <p className="text-xs text-muted-foreground">{subtitle}</p>}
          {action && <div className="shrink-0">{action}</div>}
        </div>
      )}
      <div className="flex-1 min-h-0 overflow-y-auto">{children}</div>
    </div>
  )
}
