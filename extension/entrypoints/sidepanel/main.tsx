import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import * as Tooltip from "@radix-ui/react-tooltip"

import "@/index.css"
import "@/lib/prefs"
import { Panel } from "./Panel"

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Tooltip.Provider delayDuration={300}>
      <Panel />
    </Tooltip.Provider>
  </StrictMode>,
)
