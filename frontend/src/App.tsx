import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { useIsMobile } from '@/hooks/useMediaQuery'
import { DesktopShell } from '@/components/layout/DesktopShell'
import { MobileShell } from '@/components/layout/MobileShell'
import { SearchPage } from '@/pages/SearchPage'
import { FavoritesPage } from '@/pages/FavoritesPage'
import { HistoryPage } from '@/pages/HistoryPage'
import { ProfilePage } from '@/pages/ProfilePage'

export default function App() {
  const isMobile = useIsMobile()
  const Shell = isMobile ? MobileShell : DesktopShell

  return (
    <BrowserRouter>
      <Shell>
        <Routes>
          <Route path="/" element={<SearchPage />} />
          <Route path="/favorites" element={<FavoritesPage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/profile" element={<ProfilePage />} />
        </Routes>
      </Shell>
    </BrowserRouter>
  )
}
