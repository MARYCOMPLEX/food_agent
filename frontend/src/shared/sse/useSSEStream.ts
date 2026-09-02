import { onUnmounted, ref, shallowRef } from 'vue'
import type { LoadingStep, Restaurant } from '../contracts'
import { SSEStreamClient } from './sseClient'
import type { SSEConnectionState, SSEOptions } from './types'

export function useSSEStream(sessionId: string, options: SSEOptions = {}) {
  const connectionState = ref<SSEConnectionState>('idle')
  const steps = ref<LoadingStep[]>([])
  const restaurants = ref<Restaurant[]>([])
  const summary = ref<string>('')
  const lastError = ref<any>(null)
  const isComplete = ref<boolean>(false)
  const clientRef = shallowRef<SSEStreamClient | null>(null)

  function start() {
    if (clientRef.value) {
      clientRef.value.disconnect()
    }

    const client = new SSEStreamClient(sessionId, {
      ...options,
      onStateChange: (state) => {
        connectionState.value = state
        options.onStateChange?.(state)
      },
      onProgress: (step) => {
        const index = steps.value.findIndex(s => s.id === step.id)
        if (index >= 0) {
          steps.value[index] = step
        }
        else {
          steps.value.push(step)
        }
        options.onProgress?.(step)
      },
      onResult: (results, resSummary) => {
        restaurants.value = results
        if (resSummary)
          summary.value = resSummary
        options.onResult?.(results, resSummary)
      },
      onError: (err) => {
        lastError.value = err
        options.onError?.(err)
      },
      onDone: (data) => {
        isComplete.value = true
        options.onDone?.(data)
      },
    })

    clientRef.value = client
    client.connect()
  }

  function stop() {
    if (clientRef.value) {
      clientRef.value.disconnect()
      clientRef.value = null
    }
  }

  onUnmounted(() => {
    stop()
  })

  return {
    connectionState,
    steps,
    restaurants,
    summary,
    lastError,
    isComplete,
    start,
    stop,
  }
}
