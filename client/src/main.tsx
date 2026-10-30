import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { BrowserRouter } from "react-router-dom"
import * as Tooltip from "@radix-ui/react-tooltip"

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
