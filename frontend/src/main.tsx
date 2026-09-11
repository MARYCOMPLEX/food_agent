import React from 'react'
import { createRoot } from 'react-dom/client'
import 'virtual:uno.css'
import './styles/design-tokens.css'
import App from './App'


const container = document.getElementById('app') || document.getElementById('root')
if (container) {
  const root = createRoot(container)
  root.render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  )
}
