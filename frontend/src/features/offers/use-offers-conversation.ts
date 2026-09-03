import { useCallback, useEffect, useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { ApiError } from "@/api/client"
import type { AttachmentOut } from "@/api/attachments"
import { streamChat, type SseEvent } from "@/api/chat"
import {
  clearOffersChat,
  deleteOffersChatMessage,
  fetchOffersChat,
  type OffersChatMessage,
} from "@/api/offers-chat"

export const OFFERS_CHAT_KEY = ["offers-chat"] as const
const MAX_HISTORY = 12

export interface OffersPendingExchange {
  localId: string
  question: string
  answer: string
  error?: boolean
  askedAt: number
  attachments?: AttachmentOut[]
}

let nextLocalId = 0

export function useOffersConversation() {
  const qc = useQueryClient()
  const query = useQuery({
    queryKey: OFFERS_CHAT_KEY,
    queryFn: fetchOffersChat,
    staleTime: 15_000,
    refetchOnWindowFocus: false,
  })
  const messages: OffersChatMessage[] = useMemo(() => query.data?.items ?? [], [query.data])

  const [pending, setPending] = useState<OffersPendingExchange | null>(null)
  const [isRunning, setIsRunning] = useState(false)

  useEffect(() => {
    if (!pending || isRunning || pending.error || !pending.answer.trim()) return
    const persisted = messages.some(
      (m) => m.role === "assistant" && m.content.trim() === pending.answer.trim(),
    )
    // eslint-disable-next-line react-hooks/set-state-in-effect -- синхронизация с react-query кэшем истории после invalidate
    if (persisted) setPending(null)
  }, [messages, pending, isRunning])

  const askLlm = useCallback(
    (text: string, replyToMessageId?: number, attachments?: AttachmentOut[]) => {
      const trimmed = text.trim()
      const attachmentIds = (attachments ?? []).map((a) => a.id)
      if ((!trimmed && attachmentIds.length === 0) || isRunning) return

      const localId = `q${++nextLocalId}`
      const history = messages
        .filter((m) => m.content.trim())
        .slice(-MAX_HISTORY)
        .map((m) => ({ role: m.role, text: m.content }))

      setPending({ localId, question: trimmed, answer: "", askedAt: Date.now(), attachments })
      setIsRunning(true)
      let acc = ""
      let streamError: string | null = null

      streamChat(
        {
          message: trimmed,
          history,
          offers: true,
          reply_to_message_id: replyToMessageId,
          attachment_ids: attachmentIds,
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
          void qc.invalidateQueries({ queryKey: OFFERS_CHAT_KEY })
          if (streamError) {
            const message = streamError
            setPending((cur) =>
              cur && cur.localId === localId
                ? { ...cur, error: true, answer: cur.answer || message }
                : cur,
            )
          }
        })
    },
    [isRunning, messages, qc],
  )

  const dismissPending = useCallback(() => setPending(null), [])

  const deleteMessagesMutation = useMutation({
    mutationFn: async (ids: number[]) => {
      for (const id of ids) await deleteOffersChatMessage(id)
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: OFFERS_CHAT_KEY }),
    onError: (e: unknown) =>
      toast.error(e instanceof ApiError ? e.message : "Не удалось удалить сообщение"),
  })

  const clearMutation = useMutation({
    mutationFn: clearOffersChat,
    onSuccess: () => {
      setPending(null)
      qc.setQueryData(OFFERS_CHAT_KEY, { items: [] })
    },
    onError: (e: unknown) =>
      toast.error(e instanceof ApiError ? e.message : "Не удалось очистить чат"),
  })

  return {
    messages,
    pending,
    isRunning,
    isLoading: query.isLoading,
    askLlm,
    dismissPending,
    deleteMessages: (ids: number[]) => deleteMessagesMutation.mutateAsync(ids),
    isDeletingMessages: deleteMessagesMutation.isPending,
    clear: () => clearMutation.mutateAsync(),
    isClearing: clearMutation.isPending,
  }
}

export type OffersConversation = ReturnType<typeof useOffersConversation>
