export class ApiError extends Error {
  code: string
  status: number
  detail?: any

  constructor(message: string, status = 500, code = 'API_ERROR', detail?: any) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.detail = detail
  }
}

export class NetworkError extends ApiError {
  constructor(message = '网络连接失败，请检查您的网络设置') {
    super(message, 0, 'NETWORK_ERROR')
    this.name = 'NetworkError'
  }
}

export class TimeoutError extends ApiError {
  constructor(message = '请求超时，请稍后重试') {
    super(message, 408, 'TIMEOUT_ERROR')
    this.name = 'TimeoutError'
  }
}

export function handleApiError(error: unknown): ApiError {
  if (error instanceof ApiError) {
    return error
  }
  if (error instanceof TypeError && error.message.includes('fetch')) {
    return new NetworkError()
  }
  const message = error instanceof Error ? error.message : '未知错误发生'
  return new ApiError(message)
}
