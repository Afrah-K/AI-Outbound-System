import { Routes, Route, Navigate } from 'react-router-dom'
import MainLayout from './components/layout/MainLayout'
import DashboardPage from './pages/DashboardPage'
import InboxesPage from './pages/InboxesPage'
import WarmupPage from './pages/WarmupPage'
import LeadsPage from './pages/LeadsPage'
import CampaignsPage from './pages/CampaignsPage'
import CampaignDetailPage from './pages/CampaignDetailPage'
import CampaignFormPage from './pages/CampaignFormPage'
import SequencesPage from './pages/SequencesPage'
import SequenceDetailPage from './pages/SequenceDetailPage'
import SequenceFormPage from './pages/SequenceFormPage'
import AnalyticsPage from './pages/AnalyticsPage'

function App() {
  return (
    <Routes>
      <Route path="/" element={<MainLayout />}>
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard" element={<DashboardPage />} />
        <Route path="inboxes" element={<InboxesPage />} />
        <Route path="warmup" element={<WarmupPage />} />
        <Route path="leads" element={<LeadsPage />} />
        <Route path="campaigns" element={<CampaignsPage />} />
        <Route path="campaigns/new" element={<CampaignFormPage />} />
        <Route path="campaigns/:id" element={<CampaignDetailPage />} />
        <Route path="campaigns/:id/edit" element={<CampaignFormPage />} />
        <Route path="sequences" element={<SequencesPage />} />
        <Route path="sequences/new" element={<SequenceFormPage />} />
        <Route path="sequences/:id" element={<SequenceDetailPage />} />
        <Route path="sequences/:id/edit" element={<SequenceFormPage />} />
        <Route path="analytics" element={<AnalyticsPage />} />
      </Route>
    </Routes>
  )
}

export default App
