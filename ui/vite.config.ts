import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev: `npm run dev` proxies /api to the FastAPI backend.
// Build: output goes to ../frontend, which `netcoop serve` mounts at "/".
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
  build: { outDir: '../frontend', emptyOutDir: true },
})
