import { describe, it, expect } from 'vitest'
import { checkIsMobile } from '../hooks/useIsMobile'

describe('useIsMobile / checkIsMobile breakpoint detection', () => {
  it('returns true for typical mobile screen widths (375px iPhone, 390px, 414px)', () => {
    expect(checkIsMobile(375)).toBe(true)
    expect(checkIsMobile(390)).toBe(true)
    expect(checkIsMobile(414)).toBe(true)
  })

  it('returns true exactly at the 768px tablet/mobile boundary', () => {
    expect(checkIsMobile(768)).toBe(true)
  })

  it('returns false for desktop screen widths (> 768px)', () => {
    expect(checkIsMobile(769)).toBe(false)
    expect(checkIsMobile(1024)).toBe(false)
    expect(checkIsMobile(1440)).toBe(false)
    expect(checkIsMobile(1920)).toBe(false)
  })

  it('supports custom breakpoint thresholds', () => {
    expect(checkIsMobile(800, 600)).toBe(false)
    expect(checkIsMobile(500, 600)).toBe(true)
  })
})
