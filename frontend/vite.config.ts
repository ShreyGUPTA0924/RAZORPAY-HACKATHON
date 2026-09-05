import path from 'node:path'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    // Fail loudly if 5173 is taken instead of silently drifting to 5174/5175 --
    // the backend's CORS allowlist (api/main.py) only permits port 5173, so a
    // silent port drift here means every live API call fails the CORS
    // preflight and falls back to cached data with no visible error.
    strictPort: true,
  },
})
