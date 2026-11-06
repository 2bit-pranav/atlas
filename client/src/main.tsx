import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { BrowserRouter } from "react-router-dom"
import * as Tooltip from "@radix-ui/react-tooltip"

// Bundled, not from Google Fonts: Atlas runs offline and makes no request it does not need.
import "@fontsource-variable/inter/index.css"
import "@fontsource/poppins/500.css"
import "@fontsource/poppins/600.css"
import "./index.css"
import "@/state/prefs"
import { App } from "@/app/App"

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <Tooltip.Provider delayDuration={300}>
        <App />
      </Tooltip.Provider>
    </BrowserRouter>
  </StrictMode>,
)
