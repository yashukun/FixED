import { Navigate, Route, Routes } from 'react-router-dom'
import LmsLayout from './layouts/LmsLayout'
import DashboardPage from './pages/DashboardPage'
import UpcomingPage from './pages/UpcomingPage'
import LearnAssistantPage from './pages/LearnAssistantPage'
import VivaPage from './pages/VivaPage'

function App() {
  return (
    <Routes>
      <Route path="/" element={<LmsLayout />}>
        <Route index element={<DashboardPage />} />
        <Route path="learn/assistant" element={<LearnAssistantPage />} />
        <Route path="upcoming" element={<UpcomingPage />} />
        <Route path="viva" element={<VivaPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default App
