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
    // The backend serves its routes at the root (`/chats`, `/runs`, `/settings`),
    // not under a prefix, so each one is proxied explicitly rather than proxying
    // "/" -- which would swallow Vite's own HMR and asset requests. Proxied
    // rather than reached cross-origin because the backend sends no CORS
    // headers, and the `/runs/*/events` stream is a long-lived response that a
    // browser will not open to another origin at all.
    proxy: {
      "/health": { target: backend, changeOrigin: true },
      "/chats": { target: backend, changeOrigin: true },
      "/turns": { target: backend, changeOrigin: true },
      "/runs": { target: backend, changeOrigin: true },
      "/settings": { target: backend, changeOrigin: true },
      "/skills": { target: backend, changeOrigin: true },
    },
  },
})
