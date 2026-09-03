import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { PersistQueryClientProvider } from "@tanstack/react-query-persist-client"
import { BrowserRouter } from "react-router-dom"
import { queryClient, queryPersistOptions } from "@/lib/query"
import { initErrorCapture } from "@/lib/error-capture"
import { initRum } from "@/lib/rum"
import { App } from "@/app/App"
import "@/styles/globals.css"

initErrorCapture()
initRum()

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <PersistQueryClientProvider client={queryClient} persistOptions={queryPersistOptions}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </PersistQueryClientProvider>
  </StrictMode>,
)
