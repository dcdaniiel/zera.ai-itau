import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Zera UI — dev: `npm run dev` (http://localhost:5173). A API (uvicorn :8080) é proxied em /api.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: { '/api': { target: process.env.VITE_API_URL ?? 'http://localhost:8080', changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, '') } },
  },
})
