import { Routes, Route } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import OverviewPage from './pages/OverviewPage'
import MoneyAtRiskPage from './pages/MoneyAtRiskPage'
import ExceptionsPage from './pages/ExceptionsPage'
import ExceptionDetailPage from './pages/ExceptionDetailPage'
import FinancialEventsPage from './pages/FinancialEventsPage'
import AgentInvestigationPage from './pages/AgentInvestigationPage'
import RecoveryActionsPage from './pages/RecoveryActionsPage'
import AuditTrailPage from './pages/AuditTrailPage'
import ModelPerformancePage from './pages/ModelPerformancePage'

export default function App() {
  return (
    <div className="app-shell">
      <Sidebar />
      <main className="main">
        <Routes>
          <Route path="/" element={<OverviewPage />} />
          <Route path="/money-at-risk" element={<MoneyAtRiskPage />} />
          <Route path="/exceptions" element={<ExceptionsPage />} />
          <Route path="/exceptions/:id" element={<ExceptionDetailPage />} />
          <Route path="/events" element={<FinancialEventsPage />} />
          <Route path="/investigate" element={<AgentInvestigationPage />} />
          <Route path="/recovery" element={<RecoveryActionsPage />} />
          <Route path="/audit" element={<AuditTrailPage />} />
          <Route path="/performance" element={<ModelPerformancePage />} />
        </Routes>
      </main>
    </div>
  )
}
