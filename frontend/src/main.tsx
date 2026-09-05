import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App.tsx'
import { MerchantProvider } from './services/merchantContext'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <MerchantProvider>
        <App />
      </MerchantProvider>
    </BrowserRouter>
  </StrictMode>,
)
