import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Voorkomt CORS-gedoe in dev: de browser praat alleen met de Vite-server,
    // die stuurt /api door naar FastAPI. Zie backend/app.py.
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
