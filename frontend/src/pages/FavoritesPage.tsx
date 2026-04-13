import { useIsMobile } from '@/hooks/useMediaQuery'
import { MobileFavoritesView } from '@/components/mobile/favorites/MobileFavoritesView'
import { DesktopFavoritesView } from '@/components/desktop/favorites/DesktopFavoritesView'

export function FavoritesPage() {
  return useIsMobile() ? <MobileFavoritesView /> : <DesktopFavoritesView />
}
