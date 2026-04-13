import { useIsMobile } from '@/hooks/useMediaQuery'
import { MobileHistoryView } from '@/components/mobile/history/MobileHistoryView'
import { DesktopHistoryView } from '@/components/desktop/history/DesktopHistoryView'

export function HistoryPage() {
  return useIsMobile() ? <MobileHistoryView /> : <DesktopHistoryView />
}
