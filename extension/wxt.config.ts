import { resolve } from "node:path"
import { defineConfig } from "wxt"

// Atlas in the browser: a side panel (Edge, Chrome) on the same backend as the
// web UI. The chat UI is the web UI's own components. WXT always maps `@` to
// its source folder, so the source folder *is* the web UI's `client/src`, and
// the extension's entrypoints are pointed back here. React and the tooltip
// provider are deduplicated so both sides share one copy.
export default defineConfig({
  modules: ["@wxt-dev/module-react"],
  srcDir: resolve(import.meta.dirname, "../client/src"),
  entrypointsDir: resolve(import.meta.dirname, "entrypoints"),
  publicDir: resolve(import.meta.dirname, "public"),
  alias: {
    "@ext": resolve(import.meta.dirname, "lib"),
  },
  manifest: {
    name: "Atlas",
    description: "Ask your local Atlas about the page you are on.",
    permissions: ["sidePanel", "storage", "tabs", "contextMenus", "scripting"],
    // The backend, and every page the content script may read.
    host_permissions: ["http://127.0.0.1/*", "http://localhost/*", "<all_urls>"],
    action: { default_title: "Open Atlas" },
  },
  vite: () => ({
    resolve: { dedupe: ["react", "react-dom", "@radix-ui/react-tooltip"] },
  }),
})
