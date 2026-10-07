import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig(({ mode }) => ({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // Mock mode answers the API in the browser (src/mock/). It gets no proxy at
    // all, so a call the mock fails to intercept 404s on the dev server instead
    // of reaching the real backend on :8000.
    ...(mode === 'mock'
      ? {}
      : {
          proxy: {
            '/programs': 'http://localhost:8000',
            '/health': 'http://localhost:8000',
          },
        }),
  },
}))
