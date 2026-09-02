const memoryStorage: Record<string, string> = {}

export const storage = {
  get: <T>(key: string, defaultValue: T): T => {
    try {
      let item: string | null = null
      if (typeof window !== 'undefined' && window.localStorage) {
        item = window.localStorage.getItem(key)
      }
      else {
        item = memoryStorage[key] || null
      }
      return item ? JSON.parse(item) : defaultValue
    }
    catch {
      return defaultValue
    }
  },
  set: <T>(key: string, value: T): void => {
    try {
      const valStr = JSON.stringify(value)
      if (typeof window !== 'undefined' && window.localStorage) {
        window.localStorage.setItem(key, valStr)
      }
      else {
        memoryStorage[key] = valStr
      }
    }
    catch (e) {
      console.warn('LocalStorage error:', e)
    }
  },
  remove: (key: string): void => {
    try {
      if (typeof window !== 'undefined' && window.localStorage) {
        window.localStorage.removeItem(key)
      }
      else {
        delete memoryStorage[key]
      }
    }
    catch (e) {
      console.warn('LocalStorage error:', e)
    }
  },
}
