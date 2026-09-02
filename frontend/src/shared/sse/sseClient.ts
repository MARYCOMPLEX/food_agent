import { API_BASE_URL, getDefaultHeaders } from '../api/config'
import type { StreamEvent } from '../contracts'
import type { SSEConnectionState, SSEOptions } from './types'

export class SSEStreamClient {
  private sessionId: string
  private options: SSEOptions
  private eventSource: EventSource | null = null
  private abortController: AbortController | null = null
  private lastEventId: string | null = null
  private reconnectAttempts = 0
  private reconnectTimer: any = null
  private state: SSEConnectionState = 'idle'

  constructor(sessionId: string, options: SSEOptions = {}) {
    this.sessionId = sessionId
    this.options = {
      sseVersion: 'v1',
      autoReconnect: true,
      maxReconnectAttempts: 5,
      reconnectDelayMs: 1500,
      ...options,
    }
  }

  private setState(state: SSEConnectionState) {
    this.state = state
    this.options.onStateChange?.(state)
  }

  public getState(): SSEConnectionState {
    return this.state
  }

  public connect() {
    if (this.state === 'connected' || this.state === 'connecting') {
      return
    }

    this.setState('connecting')
    const versionQuery = this.options.sseVersion ? `?sseVersion=${this.options.sseVersion}` : ''
    const streamUrl = `${API_BASE_URL}/v1/search/stream/${this.sessionId}${versionQuery}`

    // Prefer fetch-based stream for custom headers, fallback to EventSource
    this.connectViaFetch(streamUrl)
  }

  private async connectViaFetch(url: string) {
    this.abortController = new AbortController()
    const headers: Record<string, string> = {
      ...getDefaultHeaders(),
      Accept: 'text/event-stream',
    }
    if (this.lastEventId) {
      headers['Last-Event-ID'] = this.lastEventId
    }

    try {
      const response = await fetch(url, {
        headers,
        signal: this.abortController.signal,
      })

      if (!response.ok) {
        throw new Error(`SSE stream failed with status ${response.status}`)
      }

      if (!response.body) {
        throw new Error('ReadableStream not supported on this response')
      }

      this.setState('connected')
      this.reconnectAttempts = 0

      const reader = response.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) {
          if (this.state !== 'completed') {
            this.handleDisconnect()
          }
          break
        }

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split(/\r\n|\r|\n/)
        buffer = lines.pop() || ''

        let currentEvent = 'message'
        let currentData = ''
        let currentId = ''

        for (const line of lines) {
          if (line.startsWith('id:')) {
            currentId = line.substring(3).trim()
            this.lastEventId = currentId
          }
          else if (line.startsWith('event:')) {
            currentEvent = line.substring(6).trim()
          }
          else if (line.startsWith('data:')) {
            currentData = line.substring(5).trim()
          }
          else if (line === '') {
            if (currentData) {
              this.dispatchSSEEvent(currentEvent, currentData, currentId)
            }
            currentEvent = 'message'
            currentData = ''
            currentId = ''
          }
        }
      }
    }
    catch (error: any) {
      if (error.name === 'AbortError') {
        this.setState('disconnected')
        return
      }
      this.options.onError?.(error)
      this.handleDisconnect()
    }
  }

  private dispatchSSEEvent(eventType: string, dataStr: string, eventId: string) {
    let parsedData: any = dataStr
    try {
      parsedData = JSON.parse(dataStr)
    }
    catch {
      // keep raw string
    }

    const streamEvent: StreamEvent = {
      event: (eventType as any) || 'message',
      data: parsedData,
      id: eventId,
    }

    this.options.onEvent?.(streamEvent)

    switch (streamEvent.event) {
      case 'status':
        this.options.onStatus?.(parsedData)
        break
      case 'progress':
        this.options.onProgress?.(parsedData)
        break
      case 'result':
        if (parsedData?.recommendations) {
          this.options.onResult?.(parsedData.recommendations, parsedData.summary)
        }
        break
      case 'error':
        this.options.onError?.(parsedData)
        this.setState('error')
        break
      case 'done':
        this.options.onDone?.(parsedData)
        this.setState('completed')
        this.disconnect()
        break
    }
  }

  private handleDisconnect() {
    if (this.state === 'completed' || this.state === 'disconnected') {
      return
    }

    if (this.options.autoReconnect && this.reconnectAttempts < (this.options.maxReconnectAttempts || 5)) {
      this.reconnectAttempts++
      this.setState('reconnecting')
      const delay = (this.options.reconnectDelayMs || 1500) * 1.5 ** (this.reconnectAttempts - 1)
      this.reconnectTimer = setTimeout(() => {
        this.connect()
      }, delay)
    }
    else {
      this.setState('disconnected')
    }
  }

  public disconnect() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    if (this.abortController) {
      this.abortController.abort()
      this.abortController = null
    }
    if (this.eventSource) {
      this.eventSource.close()
      this.eventSource = null
    }
    if (this.state !== 'completed') {
      this.setState('disconnected')
    }
  }
}
