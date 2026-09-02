import { describe, expect, it } from 'vitest'
import { formatDuration, formatPrice, formatTrustScore, truncateText } from '../shared/utils/formatters'
import { formatRelativeTime } from '../shared/utils/date'
import { getDefaultHeaders, getDeviceId, getTenantId } from '../shared/api/config'

describe('shared Utilities and Formatters', () => {
  it('formats trust score correctly', () => {
    expect(formatTrustScore(8.56)).toBe('8.6')
    expect(formatTrustScore(undefined)).toBe('N/A')
    expect(formatTrustScore(7)).toBe('7.0')
  })

  it('formats price correctly', () => {
    expect(formatPrice('$$$')).toBe('$$$')
    expect(formatPrice(undefined)).toBe('¥¥')
  })

  it('formats relative date strings', () => {
    expect(formatRelativeTime(null)).toBe('刚刚')
    expect(formatRelativeTime(new Date().toISOString())).toBeTruthy()
  })

  it('truncates long text properly', () => {
    const text = '这是一个非常长非常长非常长的餐厅推荐评语和美食探店笔记'
    expect(truncateText(text, 10)).toBe('这是一个非常长非常长...')
    expect(truncateText('短文本', 10)).toBe('短文本')
  })

  it('formats duration in ms and seconds', () => {
    expect(formatDuration(450)).toBe('450ms')
    expect(formatDuration(1850)).toBe('1.9s')
  })

  it('generates consistent tenant and device headers', () => {
    const tenantId = getTenantId()
    const deviceId = getDeviceId()
    expect(tenantId).toBeTruthy()
    expect(deviceId).toBeTruthy()

    const headers = getDefaultHeaders()
    expect(headers['X-User-Id']).toBe(tenantId)
    expect(headers['X-Device-Id']).toBe(deviceId)
    expect(headers['Content-Type']).toBe('application/json')
  })
})
