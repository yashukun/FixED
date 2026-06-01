import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App.jsx'
import { CostProvider } from './context/CostContext'
import { ThemeProvider } from './context/ThemeContext'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ThemeProvider>
      <CostProvider>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </CostProvider>
    </ThemeProvider>
  </StrictMode>,
)
