import { fileURLToPath, URL } from "node:url"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

const backendPort = process.env.VITE_ATLAS_BACKEND_PORT ?? "8000"
const backend = `http://localhost:${backendPort}`

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    // Every backend route is under /api, so one prefix is proxied and the
    // app's own pages (/settings, /skills, /mcp) stay with the SPA. Proxied
    // rather than reached cross-origin because the backend sends no CORS
    // headers, and the event stream is a long-lived response.
    proxy: {
      "/api": { target: backend, changeOrigin: true },
    },
  },
})
