import type { ApiResponse } from '../contracts'
import { API_BASE_URL, getDefaultHeaders } from './config'
import { ApiError, TimeoutError, handleApiError } from './errors'

export interface RequestOptions extends RequestInit {
  timeoutMs?: number
  params?: Record<string, any>
}

export async function request<T = any>(
  endpoint: string,
  options: RequestOptions = {},
): Promise<T> {
  const { timeoutMs = 30000, params, ...fetchOptions } = options

  let url = endpoint.startsWith('http') ? endpoint : `${API_BASE_URL}${endpoint}`

  if (params) {
    const searchParams = new URLSearchParams()
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') {
        searchParams.append(key, String(value))
      }
    })
    const queryString = searchParams.toString()
    if (queryString) {
      url += (url.includes('?') ? '&' : '?') + queryString
    }
  }

  const headers = {
    ...getDefaultHeaders(),
    ...(fetchOptions.headers as Record<string, string>),
  }

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)

  try {
    const response = await fetch(url, {
      ...fetchOptions,
      headers,
      signal: controller.signal,
    })

    clearTimeout(timer)

    if (response.status === 204) {
      return {} as T
    }

    let payload: any
    const contentType = response.headers.get('content-type') || ''
    if (contentType.includes('application/json')) {
      payload = await response.json()
    }
    else {
      payload = await response.text()
    }

    if (!response.ok) {
      const message = payload?.message || payload?.error || payload?.detail || response.statusText || '请求失败'
      const code = payload?.error || payload?.code || `HTTP_${response.status}`
      throw new ApiError(message, response.status, code, payload)
    }

    if (payload && typeof payload === 'object' && 'success' in payload) {
      const apiResp = payload as ApiResponse<T>
      if (!apiResp.success) {
        throw new ApiError(apiResp.message || apiResp.error || '操作失败', response.status, apiResp.error || 'FAILED', payload)
      }
      return (apiResp.data !== undefined ? apiResp.data : apiResp) as T
    }

    return payload as T
  }
  catch (error: any) {
    clearTimeout(timer)
    if (error.name === 'AbortError') {
      throw new TimeoutError()
    }
    throw handleApiError(error)
  }
}

export const httpClient = {
  get: <T = any>(url: string, params?: Record<string, any>, options?: RequestOptions) =>
    request<T>(url, { ...options, method: 'GET', params }),

  post: <T = any>(url: string, body?: any, options?: RequestOptions) =>
    request<T>(url, {
      ...options,
      method: 'POST',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }),

  put: <T = any>(url: string, body?: any, options?: RequestOptions) =>
    request<T>(url, {
      ...options,
      method: 'PUT',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }),

  delete: <T = any>(url: string, params?: Record<string, any>, options?: RequestOptions) =>
    request<T>(url, { ...options, method: 'DELETE', params }),
}
