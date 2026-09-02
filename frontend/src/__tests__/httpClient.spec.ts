import { afterEach, describe, expect, it, vi } from 'vitest'
import { httpClient } from '../shared/api/httpClient'

describe('hTTP Client & Envelope Unpacking', () => {
  const originalFetch = globalThis.fetch

  afterEach(() => {
    globalThis.fetch = originalFetch
  })

  it('unpacks standard success envelope correctly', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: { get: () => 'application/json' },
      json: async () => ({
        success: true,
        data: { sessionId: 'sess_123', status: 'ready' },
      }),
    } as any)

    const result = await httpClient.get<{ sessionId: string, status: string }>('/v1/test')
    expect(result.sessionId).toBe('sess_123')
    expect(result.status).toBe('ready')
  })

  it('throws ApiError when backend returns success=false envelope', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: { get: () => 'application/json' },
      json: async () => ({
        success: false,
        error: 'PLATFORM_DISABLED',
        message: 'Platform accounts disabled',
      }),
    } as any)

    await expect(httpClient.get('/v1/platform/accounts')).rejects.toThrow('Platform accounts disabled')
  })

  it('throws ApiError on HTTP 4xx/5xx status', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      statusText: 'Not Found',
      headers: { get: () => 'application/json' },
      json: async () => ({
        detail: 'Session not found',
      }),
    } as any)

    await expect(httpClient.get('/v1/search/status/non_existing')).rejects.toThrow('Session not found')
  })
})
