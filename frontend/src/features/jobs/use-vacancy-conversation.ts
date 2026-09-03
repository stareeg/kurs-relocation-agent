import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { ApiError } from "@/api/client"
import type { AttachmentOut, AttachmentRoute } from "@/api/attachments"
import {
  applyFunnelSuggestion,
  attachVacancyText,
  deleteConversationMessage,
  dismissFunnelSuggestion,
  fetchConversation,
  importConversationDump,
  type ConversationOut,
  type ConvMessage,
} from "@/api/conversations"
import type { Job } from "@/api/jobs"
import { invalidateResumeScore } from "@/features/resume/use-resume"
import {
  FUNNEL_SUGGEST_POLL_MS,
  remainingAwaitMs,
  resolveFunnelAwait,
  shouldPollFunnelSuggestion,
  startFunnelAwait,
  type FunnelAwaitState,
} from "./funnel-suggestion-await"
import {
  convKey,
  conversationsListKey,
  exchangePersistedInMessages,
  vacancyChatStreamStore,
  type PendingExchange,
} from "./vacancy-chat-stream"

// Единый разговор по вакансии (R-4): персистентная лента HR-переписки + LLM-чата (Postgres,
// `core.repo.hr_threads`) + стрим нового LLM-ответа поверх. Заменяет старый useVacancyChat
// (эфемерный, localStorage-тред, плодил чаты). Теперь и веб-дровер, и расширение пишут в ОДИН
// разговор вакансии; здесь читаем его и дописываем три типа реплик: вопрос ассистенту (стрим),
// ручное HR-сообщение, импорт вставленного дампа переписки.

export { conversationsListKey, exchangePersistedInMessages }
export type { PendingExchange }

export function useVacancyConversation(job: Job | null) {
  const vacancyId = job?.vacancy_id ?? null
  const qc = useQueryClient()

  // FR2-86 / FR3-75: после импорта предложение пишется фоном — поллим только ЭТУ vacancyId.
  const [funnelAwait, setFunnelAwait] = useState<FunnelAwaitState>(null)
  const awaitingThis = shouldPollFunnelSuggestion(funnelAwait, vacancyId)

  const query = useQuery({
    queryKey: convKey(vacancyId),
    queryFn: () => fetchConversation(vacancyId!),
    enabled: !!vacancyId,
    staleTime: 15_000,
    refetchOnWindowFocus: false,
    refetchInterval: awaitingThis ? FUNNEL_SUGGEST_POLL_MS : false,
  })
  // useMemo: query.data?.messages ?? [] иначе новый массив каждый рендер → эффекты/лента дёргаются.
  const messages: ConvMessage[] = useMemo(() => query.data?.messages ?? [], [query.data])

  useEffect(() => {
    if (!awaitingThis || !vacancyId || !funnelAwait) return

    const next = resolveFunnelAwait({
      awaitState: funnelAwait,
      currentVacancyId: vacancyId,
      suggestedStatus: query.data?.thread?.suggested_funnel_status,
    })
    if (next !== funnelAwait) {
      if (next === null) {
        // Ожидание только что закрылось — фон (event_extract/funnel_suggest) успел что-то
        // посчитать, и эта карточка (convKey) его уже подхватила поллингом. Список диалогов
        // слева свой такой поллинг не ведёт — без явной инвалидации бейдж следующего этапа был
        // виден в шапке диалога, но не появлялся в «Диалогах» слева (МТС «Топ менеджмент»,
        // 2026-08-12).
        void qc.invalidateQueries({ queryKey: conversationsListKey })
      }
      // eslint-disable-next-line react-hooks/set-state-in-effect -- синхронизация с результатом поллинга funnel-статуса
      setFunnelAwait(next)
      return
    }

    const ms = remainingAwaitMs(funnelAwait)
    const t = window.setTimeout(() => {
      setFunnelAwait((cur) => {
        const resolved = resolveFunnelAwait({
          awaitState: cur,
          currentVacancyId: vacancyId,
          suggestedStatus: null,
        })
        if (resolved === null && cur !== null) {
          void qc.invalidateQueries({ queryKey: conversationsListKey })
        }
        return resolved
      })
    }, ms)
    return () => window.clearTimeout(t)
  }, [awaitingThis, vacancyId, funnelAwait, query.data?.thread?.suggested_funnel_status, qc])

  // Оптимистичный стрим LLM-ответа поверх персистентной ленты (до рефетча после записи на бэке).
  // Живёт в внешнем сторе (vacancy-chat-stream.ts), а не в useState — так переключение диалога
  // (VacancyConversationPane монтируется с key={vacancyId}, ChatPage.tsx) не рвёт фетч и не роняет
  // ответ агента: стор переживает размонтирование компонента, стрим доходит и пишется в БД в фоне.
  const streamKey = vacancyId ?? ""
  const subscribeStream = useCallback(
    (onChange: () => void) => vacancyChatStreamStore.subscribe(streamKey, onChange),
    [streamKey],
  )
  const getStreamSnapshot = useCallback(
    () => vacancyChatStreamStore.getSnapshot(streamKey),
    [streamKey],
  )
  const { queue, isRunning, lastFollowUps } = useSyncExternalStore(
    subscribeStream,
    getStreamSnapshot,
  )

  // Обмен доотстрелялся (status "done"), а рефетч ленты отстал / персист на бэке ещё не прошёл —
  // не гасим пузырь, пока обмен не появится в messages (иначе ответ «исчезает» после токенов).
  // По ВСЕЙ очереди, не только по «текущему» — несколько обменов подряд могут ждать подтверждения
  // персиста одновременно (следующий вопрос уже стримится, пока предыдущий ещё не подтверждён).
  useEffect(() => {
    if (!vacancyId) return
    for (const item of queue) {
      if (item.status !== "done" || item.error) continue
      const attachmentIds = (item.attachments ?? []).map((a) => a.id)
      if (exchangePersistedInMessages(messages, item.question, item.answer, attachmentIds)) {
        vacancyChatStreamStore.clearPending(vacancyId, item.localId)
      }
    }
  }, [vacancyId, messages, queue])

  const askLlm = useCallback(
    (raw: string, noteIds?: number[], replyToMessageId?: number, attachments?: AttachmentOut[]) => {
      if (!job || !vacancyId) return
      vacancyChatStreamStore.ask({
        vacancyId,
        job,
        qc,
        text: raw,
        noteIds,
        replyToMessageId,
        attachments,
      })
    },
    [job, vacancyId, qc],
  )

  const dismissPending = useCallback(
    (localId: string) => {
      if (!vacancyId) return
      vacancyChatStreamStore.clearPending(vacancyId, localId)
    },
    [vacancyId],
  )

  const importDump = useMutation({
    mutationFn: (payload: {
      text: string
      attachmentIds: number[]
      attachmentRoutes: Record<number, AttachmentRoute>
    }) =>
      importConversationDump(
        vacancyId!,
        payload.text,
        payload.attachmentIds,
        payload.attachmentRoutes,
      ),
    onSuccess: (res) => {
      // Импорт не трогает hr_link в БД — сохраняем из ответа или из прежнего кэша.
      qc.setQueryData(convKey(vacancyId), (prev: ConversationOut | undefined) => ({
        vacancy_id: res.vacancy_id,
        thread: res.thread,
        messages: res.messages,
        hr_link: res.hr_link || prev?.hr_link || "",
      }))
      void qc.invalidateQueries({ queryKey: conversationsListKey })
      if (res.added > 0) {
        toast.success(`Добавлено сообщений: ${res.added}`)
        // FR3-75: ключ по vacancy_id импорта (не глобальный boolean).
        if (vacancyId) setFunnelAwait(startFunnelAwait(vacancyId))
      } else if (res.unrecognized_attachment_ids.length === 0) {
        // Скрины-непереписку (Э4-1) композер разбирает сам — там точнее тост с кнопкой.
        toast.message("Новых сообщений не найдено")
      }
      if (vacancyId) vacancyChatStreamStore.clearFollowUps(vacancyId)
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Не удалось разобрать переписку"),
  })

  const attachText = useMutation({
    mutationFn: (text: string) => attachVacancyText(vacancyId!, text),
    onSuccess: (res) => {
      void qc.invalidateQueries({ queryKey: convKey(vacancyId) })
      void qc.invalidateQueries({ queryKey: ["jobs"] })
      void qc.invalidateQueries({ queryKey: conversationsListKey })
      if (res.overall_score != null) invalidateResumeScore(qc)
      toast.success(
        res.overall_score != null
          ? `Текст вакансии добавлен, скор пересчитан: ${Math.round(res.overall_score)}`
          : "Текст вакансии добавлен",
      )
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Не удалось сохранить текст вакансии"),
  })

  const deleteMessages = useMutation({
    mutationFn: async (ids: number[]) => {
      let last: ConversationOut | null = null
      for (const id of ids) {
        last = await deleteConversationMessage(vacancyId!, id)
      }
      return last
    },
    onSuccess: (res) => {
      if (res) qc.setQueryData(convKey(vacancyId), res)
      void qc.invalidateQueries({ queryKey: conversationsListKey })
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Не удалось удалить сообщение"),
  })

  const applySuggestion = useMutation({
    mutationFn: () => applyFunnelSuggestion(vacancyId!),
    onSuccess: (res) => {
      void qc.invalidateQueries({ queryKey: convKey(vacancyId) })
      void qc.invalidateQueries({ queryKey: ["jobs"] })
      void qc.invalidateQueries({ queryKey: ["interview-stages", vacancyId] })
      if (res.applied && res.status) {
        toast.success(`Этап: ${res.status}`)
      } else {
        toast.message("Предложение уже не актуально")
      }
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Не удалось сменить этап"),
  })

  const dismissSuggestion = useMutation({
    mutationFn: () => dismissFunnelSuggestion(vacancyId!),
    onSuccess: () => {
      qc.setQueryData(convKey(vacancyId), (prev: ConversationOut | undefined) => {
        if (!prev?.thread) return prev
        return {
          ...prev,
          thread: {
            ...prev.thread,
            suggested_funnel_status: null,
            suggested_stage_type: null,
          },
        }
      })
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Не удалось скрыть предложение"),
  })

  return {
    thread: query.data?.thread ?? null,
    hrLink: query.data?.hr_link ?? "",
    messages,
    queue,
    isRunning,
    lastFollowUps,
    isLoading: query.isLoading,
    askLlm,
    dismissPending,
    importDump: (
      text: string,
      attachmentIds: number[] = [],
      attachmentRoutes: Record<number, AttachmentRoute> = {},
    ) => importDump.mutateAsync({ text, attachmentIds, attachmentRoutes }),
    isImporting: importDump.isPending,
    attachVacancyText: (text: string) => attachText.mutateAsync(text),
    isAttachingText: attachText.isPending,
    deleteMessages: (ids: number[]) => deleteMessages.mutateAsync(ids),
    isDeletingMessages: deleteMessages.isPending,
    applyFunnelSuggestion: () => applySuggestion.mutate(),
    dismissFunnelSuggestion: () => dismissSuggestion.mutate(),
    funnelSuggestionPending: applySuggestion.isPending || dismissSuggestion.isPending,
  }
}

export type VacancyConversation = ReturnType<typeof useVacancyConversation>
