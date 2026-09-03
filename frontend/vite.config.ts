import path from "node:path"
import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"

// Бэкенд (api.main:app) слушает :8000. В dev проксируем туда API-пути,
// чтобы cookie-сессия и CORS работали как на одном origin (frontend_origin=5173).
const API_TARGET = "http://localhost:8000"

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
  server: {
    host: "localhost",
    port: 5173,
    proxy: {
      "/api": { target: API_TARGET, changeOrigin: true, ws: true },
      "/score": { target: API_TARGET, changeOrigin: true },
      "/auth": { target: API_TARGET, changeOrigin: true },
      "/health": { target: API_TARGET, changeOrigin: true },
    },
  },
})
