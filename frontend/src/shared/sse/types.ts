import type { LoadingStep, Restaurant, StreamEvent } from '../contracts'

export type SSEConnectionState = 'idle' | 'connecting' | 'connected' | 'reconnecting' | 'disconnected' | 'error' | 'completed'

export interface SSEOptions {
  sseVersion?: string
  autoReconnect?: boolean
  maxReconnectAttempts?: number
  reconnectDelayMs?: number
  onEvent?: (event: StreamEvent) => void
  onStatus?: (data: any) => void
  onProgress?: (step: LoadingStep) => void
  onResult?: (restaurants: Restaurant[], summary?: string) => void
  onError?: (error: Error | any) => void
  onDone?: (data: any) => void
  onStateChange?: (state: SSEConnectionState) => void
}
