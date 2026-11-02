import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// API_PROXY_TARGET: http://api:8000 inside docker-compose, localhost otherwise.
const apiTarget = process.env.API_PROXY_TARGET ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: { '/api': apiTarget },
  },
})
