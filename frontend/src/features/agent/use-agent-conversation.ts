import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { appendAgentChatMessage, listAgentChatMessages } from "@/api/agent"

// Реплики диалога агента (A-3): персист — сервер (agent_chat_sessions/messages), диалоги
// переживают браузер. С U-5 на экране один режим ввода — каждое сообщение запускает агента,
// поэтому здесь только история и запись реплики-цели; обычный чат с моделью остался в API
// (E-2), его старые ответы в истории показываются как реплики.

export interface AgentChatMessage {
  id: string
  role: "user" | "assistant"
  content: string
  createdAt: number
  error?: boolean
}

/** Сообщение сервера → локальная модель чата (id строкой, время из created_at). */
function fromServer(
  m: { id: number; role: string; content: string; created_at: string | null },
): AgentChatMessage {
  return {
    id: `s${m.id}`,
    role: m.role === "user" ? "user" : "assistant",
    content: m.content,
    createdAt: m.created_at ? Date.parse(m.created_at) : Date.now(),
  }
}

export function useAgentConversation(sessionId: number | null, onUserPersisted?: () => void) {
  const [messages, setMessages] = useState<AgentChatMessage[]>([])
  // Реплики, добавленные локально в эту сессию: не теряем их, если загрузка списка
  // с сервера (смена сессии) разрешилась уже после отправки.
  const localAdds = useRef<{ sid: number; message: AgentChatMessage }[]>([])

  // Смена сессии → перечитать реплики с сервера; без сессии — пусто (создастся на отправке).
  useEffect(() => {
    if (sessionId == null) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- синхронизация с внешним хранилищем (сессии в БД), не производное состояние
      setMessages([])
      return
    }
    let cancelled = false
    void (async () => {
      try {
        const items = await listAgentChatMessages(sessionId)
        if (cancelled) return
        const loaded = items.map(fromServer)
        const ids = new Set(loaded.map((m) => m.id))
        const extra = localAdds.current
          .filter((a) => a.sid === sessionId && !ids.has(a.message.id))
          .map((a) => a.message)
        setMessages([...loaded, ...extra].sort((a, b) => a.createdAt - b.createdAt))
      } catch {
        /* нет PG/сети — пустой диалог; отправка всё равно попробует дописать */
      }
    })()
    return () => {
      cancelled = true
    }
  }, [sessionId])

  /** Реплика-цель запуска агента: сессия гарантируется вызывающим; сервер недоступен — молча. */
  const persistUser = useCallback(
    async (text: string, explicitId: number | null) => {
      if (explicitId == null || !text.trim()) return
      let added: { sid: number; message: AgentChatMessage }
      try {
        const saved = await appendAgentChatMessage(explicitId, "user", text.trim())
        added = { sid: explicitId, message: fromServer(saved) }
      } catch {
        return
      }
      // Сервер сам ставит заголовок диалога по первой реплике — обновим список в меню.
      onUserPersisted?.()
      localAdds.current = [...localAdds.current.slice(-20), added]
      setMessages((cur) =>
        cur.some((m) => m.id === added.message.id) ? cur : [...cur, added.message],
      )
    },
    [onUserPersisted],
  )

  return useMemo(() => ({ messages, persistUser }), [messages, persistUser])
}
