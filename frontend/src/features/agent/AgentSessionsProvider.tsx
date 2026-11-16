import { useContext, type ReactNode } from "react"
import { AgentSessionsContext } from "./agent-sessions-context"
import { useAgentSessions } from "./use-agent-sessions"

/** Серверные диалоги агента для меню и экрана (один запрос списка на оболочку). */
export function AgentSessionsProvider({ children }: { children: ReactNode }) {
  const sessions = useAgentSessions()
  return <AgentSessionsContext.Provider value={sessions}>{children}</AgentSessionsContext.Provider>
}

/** Провайдер уже есть выше (оболочка) — ничего не делаем, иначе поднимаем свой. */
export function AgentSessionsBoundary({ children }: { children: ReactNode }) {
  const ctx = useContext(AgentSessionsContext)
  if (ctx != null) return <>{children}</>
  return <AgentSessionsProvider>{children}</AgentSessionsProvider>
}
