import { useCallback, useEffect, useMemo, useState } from "react"
import { toast } from "sonner"
import { ApiError } from "@/api/client"
import type { AttachmentOut } from "@/api/attachments"
import { streamChat, type SseEvent } from "@/api/chat"
import { appendAgentChatMessage, deleteAgentChat, listAgentChatMessages } from "@/api/agent"

// Главный чат агента (U-0/U-1 + A-3): свободный чат без привязки к вакансии.
// Персист — сервер (agent_chat_sessions/messages, A-3): диалоги переживают браузер,
// список слева берётся из БД. localStorage остаётся резервной копией на случай,
// пока БД недоступна (пишется, но источником правды служит сервер, если отвечает).
// Композер блокирует повторную отправку, пока предыдущий ответ не дошёл — тот же
// приём, что в use-market-conversation.ts.

export const AGENT_CHAT_STORAGE_KEY = "copilot.agent-chat.messages"
const MAX_HISTORY = 12

export type AgentChatRole = "user" | "assistant"

export interface AgentChatMessage {
  id: string
  role: AgentChatRole
  content: string
  createdAt: number
  attachments?: AttachmentOut[]
  error?: boolean
}

export interface AgentPendingExchange {
  localId: string
  question: string
  answer: string
  error?: boolean
  askedAt: number
  attachments?: AttachmentOut[]
}

export type AgentChatTier = "" | "advanced" | "basic"

function saveMessages(messages: AgentChatMessage[]) {
  try {
    localStorage.setItem(AGENT_CHAT_STORAGE_KEY, JSON.stringify(messages.slice(-200)))
  } catch {
    /* переполнение localStorage — чат просто не переживёт F5, не роняем UI */
  }
}

let nextLocalId = 0

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

export function useAgentConversation(
  sessionId: number | null,
  ensureSession: () => Promise<number | null>,
) {
  const [messages, setMessages] = useState<AgentChatMessage[]>([])
  const [pending, setPending] = useState<AgentPendingExchange | null>(null)
  const [isRunning, setIsRunning] = useState(false)

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
        if (!cancelled) setMessages(items.map(fromServer))
      } catch {
        /* нет PG/сети — пустой диалог; отправка всё равно попробует дописать */
      }
    })()
    return () => {
      cancelled = true
    }
  }, [sessionId])

  /** Дописать реплику на сервер (best effort): сессия могла не создаться — тогда молча. */
  const persist = useCallback(
    async (role: AgentChatRole, content: string, explicitId?: number | null) => {
      const id = explicitId !== undefined ? explicitId : sessionId
      if (id == null || !content.trim()) return
      try {
        await appendAgentChatMessage(id, role, content.trim())
      } catch {
        /* сервер недоступен — реплика останется только локально */
      }
    },
    [sessionId],
  )

  const askLlm = useCallback(
    async (text: string, attachments?: AttachmentOut[], tier: AgentChatTier = "") => {
      const trimmed = text.trim()
      const attachmentIds = (attachments ?? []).map((a) => a.id)
      if ((!trimmed && attachmentIds.length === 0) || isRunning) return

      const localId = `q${++nextLocalId}`
      const history = messages
        .filter((m) => m.content.trim() && !m.error)
        .slice(-MAX_HISTORY)
        .map((m) => ({ role: m.role, text: m.content }))

      setPending({
        localId,
        question: trimmed,
        answer: "",
        askedAt: Date.now(),
        attachments,
      })
      setIsRunning(true)
      const sid = await ensureSession()
      void persist("user", trimmed, sid)
      let acc = ""
      let streamError: string | null = null

      streamChat(
        {
          message: trimmed,
          history,
          attachment_ids: attachmentIds,
          tier: tier || undefined,
        },
        (e: SseEvent) => {
          const kind = typeof e.data.type === "string" && e.data.type ? e.data.type : e.event
          if (kind === "token" || kind === "part") {
            const piece = (typeof e.data.text === "string" ? e.data.text : e.data.content) ?? ""
            acc += piece
            setPending((cur) => (cur && cur.localId === localId ? { ...cur, answer: acc } : cur))
            return
          }
          if (kind === "error") {
            streamError =
              (typeof e.data.detail === "string" && e.data.detail) ||
              (typeof e.data.message === "string" && e.data.message) ||
              "Ошибка"
          }
        },
      )
        .catch((err: Error) => {
          streamError = err instanceof ApiError ? err.message : err.message
        })
        .finally(() => {
          setIsRunning(false)
          const answer = acc
          const failed = Boolean(streamError)
          const userMessage: AgentChatMessage = {
            id: `${localId}-q`,
            role: "user",
            content: trimmed,
            createdAt: Date.now(),
            attachments,
          }
          const assistantContent = answer.trim()
            ? answer
            : failed
              ? (streamError ?? "Ошибка")
              : ""
          const assistantMessage: AgentChatMessage | null = assistantContent
            ? {
                id: `${localId}-a`,
                role: "assistant",
                content: assistantContent,
                createdAt: Date.now(),
                error: failed,
              }
            : null
          setMessages((cur) => {
            const next = [...cur, userMessage, ...(assistantMessage ? [assistantMessage] : [])]
            saveMessages(next)
            return next
          })
          if (assistantMessage) void persist("assistant", assistantContent, sid)
          setPending(null)
          if (failed) toast.error("Агент не ответил — проверьте доступ к модели")
        })
    },
    [ensureSession, isRunning, messages, persist],
  )

  /** Реплика пользователя от запуска агента (режим «Агент»): сессия гарантируется вызывающим. */
  const persistUser = useCallback(
    async (text: string, explicitId: number | null) => {
      await persist("user", text, explicitId)
    },
    [persist],
  )

  /** Очистить диалог: удалить серверную сессию и локальную копию. */
  const clear = useCallback(async (): Promise<boolean> => {
    setPending(null)
    setMessages([])
    saveMessages([])
    if (sessionId == null) return true
    try {
      await deleteAgentChat(sessionId)
      return true
    } catch {
      toast.error("Не удалось удалить диалог на сервере")
      return false
    }
  }, [sessionId])

  const dismissPending = useCallback(() => setPending(null), [])

  return useMemo(
    () => ({
      messages,
      pending,
      isRunning,
      askLlm,
      persistUser,
      clear,
      dismissPending,
    }),
    [messages, pending, isRunning, askLlm, persistUser, clear, dismissPending],
  )
}

export type AgentConversation = ReturnType<typeof useAgentConversation>
