import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './index.css'

async function start(): Promise<void> {
  // Mock mode (`npm run dev:mock`) answers every API call in the browser. The
  // import is dynamic and behind a condition Vite resolves at build time, so a
  // normal build drops it and ships none of the mock code.
  if (import.meta.env.MODE === 'mock') {
    await import('./mock/install')
  }

  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
}

void start()
