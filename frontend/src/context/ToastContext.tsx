import React, { createContext, useContext, useState, useCallback, type ReactNode } from 'react'
import { CheckCircle2, AlertTriangle, AlertCircle, Info, X } from 'lucide-react'

export type ToastType = 'success' | 'warning' | 'error' | 'info'

export interface ToastItem {
  id: string
  type: ToastType
  message: string
  duration?: number
}

interface ToastContextValue {
  showToast: (message: string, type?: ToastType, duration?: number) => void
  removeToast: (id: string) => void
}

const ToastContext = createContext<ToastContextValue | null>(null)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([])

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])

  const showToast = useCallback((message: string, type: ToastType = 'info', duration = 3500) => {
    const id = Math.random().toString(36).substring(2, 9)
    setToasts((prev) => [...prev, { id, type, message, duration }])

    if (duration > 0) {
      setTimeout(() => {
        removeToast(id)
      }, duration)
    }
  }, [removeToast])

  return (
    <ToastContext.Provider value={{ showToast, removeToast }}>
      {children}
      <div className="fixed top-5 right-5 z-[9999] flex flex-col gap-2 pointer-events-none max-w-sm w-full">
        {toasts.map((toast) => {
          let bgClass = 'bg-white text-slate-800 border-slate-200 shadow-lg'
          let IconComponent = Info
          let iconColor = 'text-blue-500'

          if (toast.type === 'success') {
            bgClass = 'bg-emerald-50 text-emerald-900 border-emerald-200 shadow-emerald-100/50 shadow-lg'
            IconComponent = CheckCircle2
            iconColor = 'text-emerald-500'
          } else if (toast.type === 'warning') {
            bgClass = 'bg-amber-50 text-amber-900 border-amber-200 shadow-amber-100/50 shadow-lg'
            IconComponent = AlertTriangle
            iconColor = 'text-amber-500'
          } else if (toast.type === 'error') {
            bgClass = 'bg-rose-50 text-rose-900 border-rose-200 shadow-rose-100/50 shadow-lg'
            IconComponent = AlertCircle
            iconColor = 'text-rose-500'
          }

          return (
            <div
              key={toast.id}
              role="alert"
              className={`pointer-events-auto flex items-start gap-3 p-3.5 rounded-xl border text-sm transition-all duration-200 animate-in fade-in slide-in-from-top-2 ${bgClass}`}
            >
              <IconComponent className={`w-5 h-5 flex-shrink-0 mt-0.5 ${iconColor}`} />
              <div className="flex-1 leading-snug break-words">{toast.message}</div>
              <button
                onClick={() => removeToast(toast.id)}
                className="text-slate-400 hover:text-slate-600 p-0.5 rounded focus:outline-none"
                aria-label="关闭提示"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          )
        })}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  const context = useContext(ToastContext)
  if (!context) {
    throw new Error('useToast must be used within a ToastProvider')
  }
  return context
}
