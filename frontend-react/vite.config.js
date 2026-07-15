import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev server proxies API + avatar assets to the existing FastAPI backend,
// so the React app runs against real data without any backend changes.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
      '/avatars': 'http://localhost:8000',
      '/uploads': 'http://localhost:8000',
    },
  },
})
