import { useIsMobile } from '@/hooks/useMediaQuery'
import { MobileSearchView } from '@/components/mobile/search/MobileSearchView'
import { DesktopSearchView } from '@/components/desktop/search/DesktopSearchView'

export function SearchPage() {
  return useIsMobile() ? <MobileSearchView /> : <DesktopSearchView />
}
