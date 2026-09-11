import React from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { ToastProvider } from './context/ToastContext'
import { UnifiedChatWorkbench } from './pages/user/UnifiedChatWorkbench'
import { OpsShell } from './layouts/OpsShell'
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
          {/* C-End: Unified Chat Workspace (ChatGPT / Codex style) */}
          <Route path="/" element={<UnifiedChatWorkbench />} />
          <Route path="/chat" element={<UnifiedChatWorkbench />} />
          <Route path="/chat/:sessionId" element={<UnifiedChatWorkbench />} />

          {/* Compatibility redirects for /app paths */}
          <Route path="/app/*" element={<Navigate to="/" replace />} />

          {/* B-End: Internal Ops Console (/ops) */}
          <Route path="/ops" element={<OpsShell />}>
            <Route index element={<OpsOverviewPage />} />
            <Route path="services" element={<ServiceCatalogPage />} />
            <Route path="services/:serviceId" element={<ServiceDetailPage />} />
            <Route path="tasks" element={<TaskObservabilityPage />} />
            <Route path="evidence" element={<EvidenceObservabilityPage />} />
            <Route path="governance" element={<ModelGovernancePage />} />
          </Route>

          {/* Fallback */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </ToastProvider>
  )
}

export default App
