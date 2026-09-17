import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router-dom'

import { EditorPage } from './pages/Editor'
import { HomePage } from './pages/Home'
import './styles.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/d/:docId" element={<EditorPage />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
)
