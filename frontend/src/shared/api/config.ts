export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

const memoryStorage: Record<string, string> = {}

function safeGetItem(key: string): string | null {
  try {
    if (typeof window !== 'undefined' && window.localStorage) {
      return window.localStorage.getItem(key)
    }
  }
  catch {}
  return memoryStorage[key] || null
}

function safeSetItem(key: string, value: string): void {
  try {
    if (typeof window !== 'undefined' && window.localStorage) {
      window.localStorage.setItem(key, value)
      return
    }
  }
  catch {}
  memoryStorage[key] = value
}

export function getTenantId(): string {
  let tenantId = safeGetItem('anyfast_tenant_id')
  if (!tenantId) {
    tenantId = `user_${Math.random().toString(36).substring(2, 11)}`
    safeSetItem('anyfast_tenant_id', tenantId)
  }
  return tenantId
}

export function getDeviceId(): string {
  let deviceId = safeGetItem('anyfast_device_id')
  if (!deviceId) {
    deviceId = `dev_${Math.random().toString(36).substring(2, 11)}`
    safeSetItem('anyfast_device_id', deviceId)
  }
  return deviceId
}

export function getDefaultHeaders(): Record<string, string> {
  return {
    'Content-Type': 'application/json',
    'X-User-Id': getTenantId(),
    'X-Device-Id': getDeviceId(),
  }
}
