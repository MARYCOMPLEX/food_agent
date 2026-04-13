import { useIsMobile } from '@/hooks/useMediaQuery'
import { MobileProfileView } from '@/components/mobile/profile/MobileProfileView'
import { DesktopProfileView } from '@/components/desktop/profile/DesktopProfileView'

export function ProfilePage() {
  return useIsMobile() ? <MobileProfileView /> : <DesktopProfileView />
}
