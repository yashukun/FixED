import { Navigate, Route, Routes } from 'react-router-dom'
import LmsLayout from './layouts/LmsLayout'
import DashboardPage from './pages/DashboardPage'
import LearnBooksPage from './pages/LearnBooksPage'
import LearnSubjectsPage from './pages/LearnSubjectsPage'
import UpcomingPage from './pages/UpcomingPage'
import LearnAssistantPage from './pages/LearnAssistantPage'

function App() {
  return (
    <Routes>
      <Route path="/" element={<LmsLayout />}>
        <Route index element={<DashboardPage />} />
        <Route path="learn/books" element={<LearnBooksPage />} />
        <Route path="learn/subjects" element={<LearnSubjectsPage />} />
        <Route path="learn/assistant" element={<LearnAssistantPage />} />
        <Route path="upcoming" element={<UpcomingPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default App
