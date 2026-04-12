const getDeviceId = (): string => {
  let id = localStorage.getItem('deviceId')
  if (!id) {
    id = crypto.randomUUID()
    localStorage.setItem('deviceId', id)
  }
  return id
}

const getHeaders = (): HeadersInit => ({
  'Content-Type': 'application/json',
  'X-Device-Id': getDeviceId(),
})

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: getHeaders() })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: 'POST',
    headers: getHeaders(),
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

export async function apiDelete<T>(path: string): Promise<T> {
  const res = await fetch(path, { method: 'DELETE', headers: getHeaders() })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: 'PUT',
    headers: getHeaders(),
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

export { getDeviceId }
