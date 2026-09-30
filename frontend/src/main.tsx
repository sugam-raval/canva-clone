import React, { useEffect, useState } from 'react'
import ReactDOM from 'react-dom/client'

import { api, type HealthResponse } from './lib/api'
import { DraftStudio } from './pages/DraftStudio'
import { LidoFlow } from './pages/LidoApp'
import './styles.css'

function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  // "fill": fill an existing template from a prompt; "design": design a brand-new one
  const [page, setPage] = useState<'fill' | 'design'>(
    () => (window.location.hash === '#design' ? 'design' : 'fill'))
  const go = (next: 'fill' | 'design') => {
    setPage(next)
    window.location.hash = next === 'design' ? 'design' : ''
  }
  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null))
  }, [])

  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">Lido.js Template Designer</span>
        <div className="flow-toggle">
          <button className={page === 'fill' ? 'active' : ''} onClick={() => go('fill')}>
            Fill a template
          </button>
          <button className={page === 'design' ? 'active' : ''} onClick={() => go('design')}>
            Design new template
          </button>
        </div>
        <span className="spacer" />
        {health && (
          <span className={`badge ${health.openaiConfigured ? 'ok' : 'warn'}`}>
            {health.openaiConfigured ? 'OpenAI connected' : 'no API key — stub adapters'}
          </span>
        )}
      </header>
      {page === 'fill' ? <LidoFlow /> : <DraftStudio />}
    </div>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
