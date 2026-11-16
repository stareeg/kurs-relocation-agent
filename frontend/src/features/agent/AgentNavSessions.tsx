import { useLocation, useNavigate } from "react-router-dom"
import { useAgentSessionsContext } from "./agent-sessions-context"
import { AgentSessionList } from "./AgentSessionList"

const AGENT_PATH = "/chat"

/** Диалоги агента под пунктом «Агент» основного меню (U-5): из любого раздела ведут на экран. */
export function AgentNavSessions() {
  const sessions = useAgentSessionsContext()
  const navigate = useNavigate()
  const onAgent = useLocation().pathname === AGENT_PATH
  return (
    <AgentSessionList
      className="ml-3.5 border-l border-slate-200/70 py-0.5 pl-1.5"
      sessions={sessions}
      activeId={onAgent ? sessions.activeId : null}
      newActive={onAgent && sessions.activeId == null}
      limit={8}
      onSelect={(id) => {
        sessions.setActiveId(id)
        if (!onAgent) navigate(AGENT_PATH)
      }}
      onCreate={() => {
        sessions.setActiveId(null)
        if (!onAgent) navigate(AGENT_PATH)
      }}
      onDelete={(id) => void sessions.remove(id)}
    />
  )
}
