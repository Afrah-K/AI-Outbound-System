import { Routes, Route, Navigate, useLocation } from 'react-router-dom'
import MainLayout from './components/layout/MainLayout'
import { RequireAuth } from './context/Auth'
import { BackgroundTasksProvider } from './context/BackgroundTasks'
import AuthPage from './pages/AuthPage'
import InboxesPage from './pages/InboxesPage'
import UniboxPage from './pages/UniboxPage'
import BookingPage from './pages/BookingPage'
import CalendarPage from './pages/CalendarPage'
import WarmupPage from './pages/WarmupPage'
import ProspectsPage from './pages/ProspectsPage'
import EnricherPage from './pages/EnricherPage'
import VerifierPage from './pages/VerifierPage'
import PersonalizerPage from './pages/PersonalizerPage'
import ScrapersPage from './pages/ScrapersPage'
import CampaignsPage from './pages/CampaignsPage'
import CampaignDetailPage from './pages/CampaignDetailPage'
import CampaignFormPage from './pages/CampaignFormPage'
import SequencesPage from './pages/SequencesPage'
import SequenceDetailPage from './pages/SequenceDetailPage'
import SequenceFormPage from './pages/SequenceFormPage'
import AnalyticsPage from './pages/AnalyticsPage'
import GettingStartedPage from './pages/GettingStartedPage'

// Keeps ?inbox=&thread= from older alert links that point at /unibox.
function RedirectToLeadBox() {
  const location = useLocation()
  return <Navigate to={{ pathname: '/leadbox', search: location.search }} replace />
}

function App() {
  return (
    <Routes>
      <Route path="/login" element={<AuthPage mode="login" />} />
      <Route path="/signup" element={<AuthPage mode="signup" />} />
      {/* Everything else: signed in only. Background jobs are tracked across page changes. */}
      <Route
        path="/"
        element={
          <RequireAuth>
            <BackgroundTasksProvider>
              <MainLayout />
            </BackgroundTasksProvider>
          </RequireAuth>
        }
      >
        <Route index element={<Navigate to="/leadbox" replace />} />
        <Route path="start" element={<GettingStartedPage />} />
        <Route path="leadbox" element={<UniboxPage />} />
        {/* Old addresses - Lead Box replaced the dashboard and was called Unibox */}
        <Route path="dashboard" element={<Navigate to="/leadbox" replace />} />
        <Route path="inboxes" element={<InboxesPage />} />
        <Route path="unibox" element={<RedirectToLeadBox />} />
        <Route path="warmup" element={<WarmupPage />} />
        <Route path="prospects" element={<ProspectsPage />} />
        <Route path="scrapers" element={<ScrapersPage />} />
        <Route path="enricher" element={<EnricherPage />} />
        <Route path="verifier" element={<VerifierPage />} />
        <Route path="personalizer" element={<PersonalizerPage />} />
        <Route path="campaigns" element={<CampaignsPage />} />
        <Route path="campaigns/new" element={<CampaignFormPage />} />
        <Route path="campaigns/:id" element={<CampaignDetailPage />} />
        <Route path="sequences" element={<SequencesPage />} />
        <Route path="sequences/new" element={<SequenceFormPage />} />
        <Route path="sequences/:id" element={<SequenceDetailPage />} />
        <Route path="sequences/:id/edit" element={<SequenceFormPage />} />
        <Route path="analytics" element={<AnalyticsPage />} />
        <Route path="booking" element={<BookingPage />} />
        <Route path="calendar" element={<CalendarPage />} />
      </Route>
    </Routes>
  )
}

export default App
