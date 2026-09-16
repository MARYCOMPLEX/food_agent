import { useState, useEffect } from 'react'

/**
 * 判断指定宽度是否符合移动端断点
 */
export function checkIsMobile(width: number, breakpoint: number = 768): boolean {
  return width <= breakpoint
}

/**
 * 设备检测 Hook：判断当前视口是否属于移动端（默认 <= 768px）
 * 监听 matchMedia 变化，响应式更新
 */
export function useIsMobile(breakpoint: number = 768): boolean {
  const [isMobile, setIsMobile] = useState<boolean>(() => {
    if (typeof window === 'undefined') return false
    return checkIsMobile(window.innerWidth, breakpoint)
  })

  useEffect(() => {
    if (typeof window === 'undefined') return

    const mql = window.matchMedia(`(max-width: ${breakpoint}px)`)
    const update = (e: MediaQueryListEvent | MediaQueryList) => {
      setIsMobile(e.matches)
    }

    setIsMobile(mql.matches)

    if (mql.addEventListener) {
      mql.addEventListener('change', update)
      return () => mql.removeEventListener('change', update)
    } else {
      mql.addListener(update)
      return () => mql.removeListener(update)
    }
  }, [breakpoint])

  return isMobile
}
