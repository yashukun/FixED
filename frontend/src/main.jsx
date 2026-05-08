import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App.jsx'
import { CostProvider } from './context/CostContext'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <CostProvider>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </CostProvider>
  </StrictMode>,
)
