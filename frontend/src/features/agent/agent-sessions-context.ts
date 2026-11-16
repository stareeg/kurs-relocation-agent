import { createContext, useContext } from "react"
import type { AgentSessions } from "./use-agent-sessions"

// Диалоги агента — одно состояние на меню и экран (U-5): список живёт в основном меню под
// пунктом «Агент», экран агента показывает выбранный. Провайдер монтирует оболочка
// (`AppShell`), экран без оболочки (тесты) поднимает свой — `AgentSessionsBoundary`.

export const AgentSessionsContext = createContext<AgentSessions | null>(null)

export function useAgentSessionsContext(): AgentSessions {
  const ctx = useContext(AgentSessionsContext)
  if (ctx == null) throw new Error("Нет AgentSessionsProvider над экраном агента")
  return ctx
}
