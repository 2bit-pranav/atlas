import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import * as Tooltip from "@radix-ui/react-tooltip";

import "@/index.css";
import "@fontsource-variable/inter/index.css";
import "@fontsource/poppins/500.css";
import "@fontsource/poppins/600.css";
import "@/state/prefs";
import { Panel } from "./Panel";

createRoot(document.getElementById("root")!).render(
    <StrictMode>
        <Tooltip.Provider delayDuration={300}>
            <Panel />
        </Tooltip.Provider>
    </StrictMode>,
);
