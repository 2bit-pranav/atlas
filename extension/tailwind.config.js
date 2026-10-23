import client from "../client/tailwind.config.js"

/** The web UI's theme, over the panel's files and the shared components. */
export default {
  ...client,
  content: ["./entrypoints/**/*.{html,ts,tsx}", "./lib/**/*.{ts,tsx}", "../client/src/**/*.{ts,tsx}"],
}
