import React from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { ToastProvider } from './context/ToastContext'
import { UserShell } from './layouts/UserShell'
import { OpsShell } from './layouts/OpsShell'
import { ExplorePage } from './pages/user/ExplorePage'
import { ResearchSessionWorkbench } from './pages/user/ResearchSessionWorkbench'
import { FavoritesPage } from './pages/user/FavoritesPage'
import { HistoryPage } from './pages/user/HistoryPage'
import { PlatformAccountsPage } from './pages/user/PlatformAccountsPage'
import { ProfilePage } from './pages/user/ProfilePage'
import { OpsOverviewPage } from './pages/ops/OpsOverviewPage'
import { ServiceCatalogPage } from './pages/ops/ServiceCatalogPage'
import { ServiceDetailPage } from './pages/ops/ServiceDetailPage'
import { TaskObservabilityPage } from './pages/ops/TaskObservabilityPage'
import { EvidenceObservabilityPage } from './pages/ops/EvidenceObservabilityPage'
import { ModelGovernancePage } from './pages/ops/ModelGovernancePage'

export function App() {
  return (
    <ToastProvider>
      <BrowserRouter>
        <Routes>
          {/* Default redirect to Explore */}
          <Route path="/" element={<Navigate to="/app/explore" replace />} />

          {/* User Experience Portal (/app) */}
          <Route path="/app" element={<UserShell />}>
            <Route index element={<Navigate to="/app/explore" replace />} />
            <Route path="explore" element={<ExplorePage />} />
            <Route path="sessions/:sessionId" element={<ResearchSessionWorkbench />} />
            <Route path="favorites" element={<FavoritesPage />} />
            <Route path="history" element={<HistoryPage />} />
            <Route path="accounts" element={<PlatformAccountsPage />} />
            <Route path="me" element={<ProfilePage />} />
          </Route>

          {/* Internal Ops Management Console (/ops) */}
          <Route path="/ops" element={<OpsShell />}>
            <Route index element={<OpsOverviewPage />} />
            <Route path="services" element={<ServiceCatalogPage />} />
            <Route path="services/:serviceId" element={<ServiceDetailPage />} />
            <Route path="tasks" element={<TaskObservabilityPage />} />
            <Route path="evidence" element={<EvidenceObservabilityPage />} />
            <Route path="governance" element={<ModelGovernancePage />} />
          </Route>

          {/* Catch-all fallback */}
          <Route path="*" element={<Navigate to="/app/explore" replace />} />
        </Routes>
      </BrowserRouter>
    </ToastProvider>
  )
}

export default App
