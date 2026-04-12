import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { AppShell } from './components/layout/AppShell'
import { SearchPage } from './pages/SearchPage'
import { FavoritesPage } from './pages/FavoritesPage'
import { HistoryPage } from './pages/HistoryPage'
import { ProfilePage } from './pages/ProfilePage'

export default function App() {
  return (
    <BrowserRouter>
      <AppShell>
        <Routes>
          <Route path="/" element={<SearchPage />} />
          <Route path="/favorites" element={<FavoritesPage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/profile" element={<ProfilePage />} />
        </Routes>
      </AppShell>
    </BrowserRouter>
  )
}
