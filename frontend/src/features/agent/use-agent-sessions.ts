import { useCallback, useEffect, useState } from "react"
import {
  createAgentChat,
  deleteAgentChat,
  listAgentChats,
  type AgentChatSession,
} from "@/api/agent"

// Сессии главного чата (A-3): серверные диалоги вместо localStorage-треда.
// Активная сессия помнится в localStorage — на перезагрузке вкладка открывает тот же диалог.

const ACTIVE_SESSION_KEY = "copilot.agent-chat.session"

function loadActiveId(): number | null {
  try {
    const raw = localStorage.getItem(ACTIVE_SESSION_KEY)
    const id = raw ? Number(raw) : NaN
    return Number.isFinite(id) && id > 0 ? id : null
  } catch {
    return null
  }
}

function saveActiveId(id: number | null) {
  try {
    if (id == null) localStorage.removeItem(ACTIVE_SESSION_KEY)
    else localStorage.setItem(ACTIVE_SESSION_KEY, String(id))
  } catch {
    /* ignore */
  }
}

export function useAgentSessions() {
  const [sessions, setSessions] = useState<AgentChatSession[]>([])
  const [activeId, setActiveId] = useState<number | null>(loadActiveId)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async (): Promise<AgentChatSession[]> => {
    try {
      const items = await listAgentChats()
      setSessions(items)
      setActiveId((cur) => {
        if (cur != null && items.some((s) => s.id === cur)) return cur
        return items[0]?.id ?? null
      })
      return items
    } catch {
      return []
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- первичная загрузка списка с сервера (внешняя система)
    void refresh()
  }, [refresh])

  useEffect(() => saveActiveId(activeId), [activeId])

  const create = useCallback(async (): Promise<AgentChatSession | null> => {
    try {
      const session = await createAgentChat()
      setSessions((cur) => [session, ...cur])
      setActiveId(session.id)
      return session
    } catch {
      return null
    }
  }, [])

  const remove = useCallback(async (id: number): Promise<boolean> => {
    try {
      await deleteAgentChat(id)
      setSessions((cur) => cur.filter((s) => s.id !== id))
      setActiveId((cur) => (cur === id ? null : cur))
      return true
    } catch {
      return false
    }
  }, [])

  return { sessions, activeId, setActiveId, loading, refresh, create, remove }
}

export type AgentSessions = ReturnType<typeof useAgentSessions>
