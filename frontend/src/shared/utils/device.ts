import { computed } from 'vue'
import { breakpointsTailwind, useBreakpoints } from '@vueuse/core'

export function useDevice() {
  const breakpoints = useBreakpoints(breakpointsTailwind)

  const isMobile = breakpoints.smaller('md') // < 768px
  const isTablet = breakpoints.between('md', 'lg') // 768px - 1024px
  const isDesktop = breakpoints.greaterOrEqual('lg') // >= 1024px

  const layoutMode = computed<'mobile' | 'desktop'>(() => {
    return isMobile.value ? 'mobile' : 'desktop'
  })

  return {
    isMobile,
    isTablet,
    isDesktop,
    layoutMode,
  }
}
