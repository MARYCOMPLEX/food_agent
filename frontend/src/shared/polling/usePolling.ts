import { onUnmounted, ref } from 'vue'

export interface PollingOptions<T> {
  intervalMs?: number
  maxIntervalMs?: number
  backoffFactor?: number
  timeoutMs?: number
  shouldStop?: (data: T) => boolean
  onSuccess?: (data: T) => void
  onError?: (err: any) => void
  onTimeout?: () => void
}

export function usePolling<T>(
  fn: () => Promise<T>,
  options: PollingOptions<T> = {},
) {
  const {
    intervalMs = 2000,
    maxIntervalMs = 10000,
    backoffFactor = 1.0,
    timeoutMs = 300000, // 5 min
    shouldStop,
    onSuccess,
    onError,
    onTimeout,
  } = options

  const isPolling = ref(false)
  const data = ref<T | null>(null) as any
  const error = ref<any>(null)
  let timer: any = null
  let timeoutTimer: any = null
  let currentInterval = intervalMs

  async function pollStep() {
    if (!isPolling.value)
      return

    try {
      const res = await fn()
      data.value = res
      error.value = null
      onSuccess?.(res)

      if (shouldStop && shouldStop(res)) {
        stop()
        return
      }
    }
    catch (err) {
      error.value = err
      onError?.(err)
    }

    if (isPolling.value) {
      currentInterval = Math.min(currentInterval * backoffFactor, maxIntervalMs)
      timer = setTimeout(pollStep, currentInterval)
    }
  }

  function start() {
    stop()
    isPolling.value = true
    currentInterval = intervalMs

    if (timeoutMs > 0) {
      timeoutTimer = setTimeout(() => {
        stop()
        onTimeout?.()
      }, timeoutMs)
    }

    pollStep()
  }

  function stop() {
    isPolling.value = false
    if (timer) {
      clearTimeout(timer)
      timer = null
    }
    if (timeoutTimer) {
      clearTimeout(timeoutTimer)
      timeoutTimer = null
    }
  }

  onUnmounted(() => {
    stop()
  })

  return {
    isPolling,
    data,
    error,
    start,
    stop,
  }
}
