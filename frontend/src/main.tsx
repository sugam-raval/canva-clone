import React, { useEffect, useState } from 'react'
import ReactDOM from 'react-dom/client'

import { api, type HealthResponse } from './lib/api'
import { LidoFlow } from './pages/LidoApp'
import './styles.css'

function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null))
  }, [])

  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">Lido.js Template Designer</span>
        <span className="spacer" />
        {health && (
          <span className={`badge ${health.openaiConfigured ? 'ok' : 'warn'}`}>
            {health.openaiConfigured ? 'OpenAI connected' : 'no API key — stub adapters'}
          </span>
        )}
      </header>
      <LidoFlow />
    </div>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
