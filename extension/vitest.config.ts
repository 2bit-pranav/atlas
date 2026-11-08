import { resolve } from "node:path"
import { defineConfig } from "vitest/config"

// The same aliases WXT gives the build (wxt.config.ts), so tests import as the code does.
export default defineConfig({
  resolve: {
    alias: {
      "@ext": resolve(import.meta.dirname, "lib"),
      "@": resolve(import.meta.dirname, "../client/src"),
    },
  },
})
