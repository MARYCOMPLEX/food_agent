import React, { createContext, useContext, type ReactNode } from 'react'
import { message } from 'antd'

export type ToastType = 'success' | 'warning' | 'error' | 'info'

interface ToastContextValue {
  showToast: (msg: string, type?: ToastType, duration?: number) => void
  removeToast: (id: string) => void
}

const ToastContext = createContext<ToastContextValue | null>(null)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [messageApi, contextHolder] = message.useMessage()

  const showToast = (msg: string, type: ToastType = 'info', duration = 3) => {
    messageApi.open({
      type,
      content: msg,
      duration,
    })
  }

  const removeToast = (_id: string) => {
    messageApi.destroy()
  }

  return (
    <ToastContext.Provider value={{ showToast, removeToast }}>
      {contextHolder}
      {children}
    </ToastContext.Provider>
  )
}

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext)
  if (!context) {
    // Fallback if rendered outside provider
    return {
      showToast: (msg: string, type: ToastType = 'info') => {
        message[type]?.(msg)
      },
      removeToast: () => {},
    }
  }
  return context
}
