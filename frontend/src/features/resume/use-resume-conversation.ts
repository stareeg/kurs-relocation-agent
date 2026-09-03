import { useEffect, useMemo, useSyncExternalStore } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { ApiError } from "@/api/client"
import type { AttachmentOut } from "@/api/attachments"
import {
  clearResumeChat,
  deleteResumeChatMessage,
  fetchResumeChat,
  type ResumeChatHistory,
  type ResumeChatMessage,
} from "@/api/resume"
import {
  resumeChatHistoryKey,
  resumeChatStreamStore,
  type ResumeChatMsg,
  type ResumePendingExchange,
} from "./resume-chat-stream"

// Чат по резюме: один разговор на аккаунт (не per-vacancy). В отличие от чата по рынку
// (`use-market-conversation.ts`), здесь стрим живёт в module-scope сторе (resume-chat-stream),
// который переживает размонтирование ResumeChat при уходе с вкладки «Резюме» — асинхронность
// «переключился на другой раздел, пока агент думает» (требование владельца). Хук поверх стора
// даёт тот же интерфейс, что `useMarketConversation`: messages/pending/isRunning/askLlm/
// deleteMessages/clear.

/** id реплик-источников цитат — чтобы показывать «ответ на» в пузыре (как в чате по рынку). */
export type ResumeReplyTarget = { id: number; label: string; body: string }

const ROLE_LABEL: Record<ResumeChatMessage["role"], string> = {
  user: "Я",
  assistant: "Агент",
}

/** Слить сохранённую историю с активными обменами стрима. Обмены, уже персистированные в
 * истории (по тексту вопроса), убираем из хвоста очереди — иначе дубли. Персистированные
 * обмены с пустым ответом (ошибка стрима) оставляем. */
function mergeMessages(
  saved: ResumeChatMsg[],
  queue: ResumePendingExchange[],
): ResumeChatMsg[] {
  const savedQuestions = new Set(saved.map((m) => m.text.trim()).filter(Boolean))
  const live = queue
    .filter((e) => !savedQuestions.has(e.question.trim()))
    .flatMap((e): ResumeChatMsg[] => {
      const msgs: ResumeChatMsg[] = [{ role: "user", text: e.question }]
      // Пустой ответ агента показываем только пока обмен не завершён (ожидание/стрим).
      if (e.answer.trim() || e.status !== "done") {
        msgs.push({ role: "assistant", text: e.answer, error: e.error })
      }
      return msgs
    })
  return [...saved, ...live]
}

/** Обмен уже персистирован в сохранённой истории — можно убирать его из очереди, не теряя
 * ответ. Зеркало `exchangePersistedInMessages` для чата по вакансии: вопрос обязан быть в ленте,
 * а ответ — только если он непустой (пустой ответ при записанном вопросе = персист прошёл). */
function exchangePersistedInSaved(
  saved: ResumeChatMessage[],
  question: string,
  answer: string,
): boolean {
  const q = question.trim()
  const hasUser = saved.some((m) => m.role === "user" && m.content.trim() === q)
  if (!hasUser) return false
  const a = answer.trim()
  if (!a) return true
  return saved.some((m) => m.role === "assistant" && m.content.trim() === a)
}

export function useResumeConversation() {
  const qc = useQueryClient()
  // Сохранённая история — в react-query, чтобы стрим-стор мог её инвалидировать/читать.
  const query = useQuery<ResumeChatHistory>({
    queryKey: resumeChatHistoryKey,
    queryFn: () => fetchResumeChat(),
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  })
  // Снимок стрима (очередь обменов + isRunning) — подписка на module-scope стор.
  const stream = useSyncExternalStore(
    resumeChatStreamStore.subscribe,
    resumeChatStreamStore.getSnapshot,
    resumeChatStreamStore.getSnapshot,
  )

  const savedItems: ResumeChatMessage[] = useMemo(
    () => query.data?.items ?? [],
    [query.data?.items],
  )
  const savedMessages: ResumeChatMsg[] = useMemo(
    () => savedItems.map((m) => ({ role: m.role, text: m.content })),
    [savedItems],
  )
  // Сливаем сохранённую историю с активной очередью стрима (дубли убираются в mergeMessages).
  const messages: ResumeChatMsg[] = useMemo(
    () => mergeMessages(savedMessages, stream.queue),
    [savedMessages, stream.queue],
  )

  // Обмен доотстрелялся (status "done"), а рефетч ленты отстал / персист на бэке ещё не прошёл —
  // не гасим пузырь, пока обмен не появится в сохранённой истории (иначе ответ «исчезает» после
  // токенов). По ВСЕЙ очереди — несколько обменов подряд могут ждать подтверждения персиста.
  // Зеркало use-vacancy-conversation.ts.
  useEffect(() => {
    for (const item of stream.queue) {
      if (item.status !== "done" || item.error) continue
      if (exchangePersistedInSaved(savedItems, item.question, item.answer)) {
        resumeChatStreamStore.clearPending(item.localId)
      }
    }
  }, [savedItems, stream.queue])

  // Текущий оптимистичный обмен — первый в очереди, чей вопрос ещё не в сохранённой истории
  // (неважно, queued/sending/done): пока реплики не подтверждены персистом, пузырь должен
  // оставаться видимым, иначе «вся переписка исчезает» после окончания стрима.
  const pending: ResumePendingExchange | null = useMemo(() => {
    const savedQuestions = new Set(savedItems.map((m) => m.content.trim()).filter(Boolean))
    return stream.queue.find((e) => !savedQuestions.has(e.question.trim())) ?? null
  }, [stream.queue, savedItems])

  const isRunning = stream.isRunning

  function askLlm(
    text: string,
    replyToMessageId?: number,
    attachments?: AttachmentOut[],
  ) {
    resumeChatStreamStore.ask(text, replyToMessageId, attachments)
  }

  const deleteMessagesMutation = useMutation({
    mutationFn: async (ids: number[]) => {
      for (const id of ids) await deleteResumeChatMessage(id)
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: resumeChatHistoryKey }),
    onError: (e: unknown) =>
      toast.error(e instanceof ApiError ? e.message : "Не удалось удалить сообщение"),
  })

  const clearMutation = useMutation({
    mutationFn: clearResumeChat,
    onSuccess: () => {
      resumeChatStreamStore.reset()
      qc.setQueryData(resumeChatHistoryKey, { items: [] })
    },
    onError: (e: unknown) =>
      toast.error(e instanceof ApiError ? e.message : "Не удалось очистить чат"),
  })

  return {
    messages,
    /** Сохранённые реплики с id/attachments/reply_to (для контекстного меню/цитат/удаления). */
    savedItems,
    pending,
    isRunning,
    isLoading: query.isLoading,
    askLlm,
    deleteMessages: (ids: number[]) => deleteMessagesMutation.mutateAsync(ids),
    isDeletingMessages: deleteMessagesMutation.isPending,
    clear: () => clearMutation.mutateAsync(),
    isClearing: clearMutation.isPending,
    roleLabel: ROLE_LABEL,
  }
}

export type ResumeConversation = ReturnType<typeof useResumeConversation>
