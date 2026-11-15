import { useCallback, useMemo, useState } from "react"
import { toast } from "sonner"
import { ApiError } from "@/api/client"
import type { AttachmentOut } from "@/api/attachments"
import { streamChat, type SseEvent } from "@/api/chat"

// Главный чат агента (шаг U-0/U-1, каркас): один разговор на аккаунт без привязки к вакансии.
// Персист — localStorage вкладки (серверного треда для свободного чата пока нет, придёт с A-3:
// бэкенд-тред без vacancy_id). Композер блокирует повторную отправку, пока предыдущий ответ
// не дошёл — тот же приём, что в use-market-conversation.ts.

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

function loadMessages(): AgentChatMessage[] {
  try {
    const raw = localStorage.getItem(AGENT_CHAT_STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as unknown
    if (!Array.isArray(parsed)) return []
    return parsed.filter(
      (m): m is AgentChatMessage =>
        typeof m === "object" &&
        m != null &&
        typeof (m as AgentChatMessage).id === "string" &&
        typeof (m as AgentChatMessage).content === "string" &&
        ((m as AgentChatMessage).role === "user" || (m as AgentChatMessage).role === "assistant"),
    )
  } catch {
    return []
  }
}

function saveMessages(messages: AgentChatMessage[]) {
  try {
    localStorage.setItem(AGENT_CHAT_STORAGE_KEY, JSON.stringify(messages.slice(-200)))
  } catch {
    /* переполнение localStorage — чат просто не переживёт F5, не роняем UI */
  }
}

let nextLocalId = 0

export function useAgentConversation() {
  const [messages, setMessages] = useState<AgentChatMessage[]>(loadMessages)
  const [pending, setPending] = useState<AgentPendingExchange | null>(null)
  const [isRunning, setIsRunning] = useState(false)

  const askLlm = useCallback(
    (text: string, attachments?: AttachmentOut[], tier: AgentChatTier = "") => {
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
          const assistantMessage: AgentChatMessage | null = answer.trim()
            ? {
                id: `${localId}-a`,
                role: "assistant",
                content: answer,
                createdAt: Date.now(),
                error: failed,
              }
            : failed
              ? {
                  id: `${localId}-a`,
                  role: "assistant",
                  content: streamError ?? "Ошибка",
                  createdAt: Date.now(),
                  error: true,
                }
              : null
          setMessages((cur) => {
            const next = [...cur, userMessage, ...(assistantMessage ? [assistantMessage] : [])]
            saveMessages(next)
            return next
          })
          setPending(null)
          if (failed) toast.error("Агент не ответил — проверьте доступ к модели")
        })
    },
    [isRunning, messages],
  )

  const clear = useCallback(() => {
    setPending(null)
    setMessages([])
    try {
      localStorage.removeItem(AGENT_CHAT_STORAGE_KEY)
    } catch {
      /* ignore */
    }
  }, [])

  const dismissPending = useCallback(() => setPending(null), [])

  return useMemo(
    () => ({
      messages,
      pending,
      isRunning,
      askLlm,
      clear,
      dismissPending,
    }),
    [messages, pending, isRunning, askLlm, clear, dismissPending],
  )
}

export type AgentConversation = ReturnType<typeof useAgentConversation>
