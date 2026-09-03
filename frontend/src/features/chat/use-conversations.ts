import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { ApiError } from "@/api/client"
import {
  createOutreachVacancy,
  deleteConversationThread,
  fetchActiveConversationsCount,
  fetchConversation,
  fetchConversations,
  fetchTodayAttention,
  formatHrDialogText,
  patchConversationThread,
  updateConversationIdentity,
  type ConversationOut,
  type ConvThread,
  type ConversationOutreachPayload,
} from "@/api/conversations"
import { conversationsListKey } from "@/features/jobs/use-vacancy-conversation"
import { convKey } from "@/features/jobs/vacancy-chat-stream"
import { invalidateResumeScore } from "@/features/resume/use-resume"

export const conversationsActiveCountKey = ["conversations", "active-count"] as const

// Список-хаб всех разговоров по вакансиям (R-4). Ключ — общий с инвалидацией из дровера, поэтому
// добавление реплики/чата в дровере освежает и хаб.
export function useConversations(includeArchived: boolean) {
  return useQuery({
    queryKey: [...conversationsListKey, includeArchived] as const,
    queryFn: () => fetchConversations(includeArchived),
    staleTime: 15_000,
    refetchOnWindowFocus: false,
  })
}

/** Счётчик активных чатов (без архива) для бейджа в сайдбаре — зеркало jobs/active-count. */
export function useActiveConversationsCount() {
  return useQuery({
    queryKey: conversationsActiveCountKey,
    queryFn: fetchActiveConversationsCount,
    staleTime: 30_000,
  })
}

// RD-14: витрина дня для пустого состояния «Чатов» — чистый SQL, staleTime короткий (дешёвые
// агрегаты, но заход в Чаты не должен бить эндпоинт при каждом ре-рендере).
export function useTodayAttention() {
  return useQuery({
    queryKey: ["conversations", "attention"] as const,
    queryFn: () => fetchTodayAttention(),
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  })
}

/** HR написал первым: вакансия в воронке + разговор в «Чатах». */
export function useCreateOutreachVacancy() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: ConversationOutreachPayload) => createOutreachVacancy(body),
    onSuccess: (res) => {
      qc.setQueryData(["conversation", res.vacancy_id], res.conversation)
      void qc.invalidateQueries({ queryKey: conversationsListKey })
      void qc.invalidateQueries({ queryKey: conversationsActiveCountKey })
      void qc.invalidateQueries({ queryKey: ["jobs"] })
      if (res.scored) invalidateResumeScore(qc)
      toast.success(res.scored ? "Вакансия создана и оценена" : "Вакансия создана")
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Не удалось создать вакансию"),
  })
}

export function useArchiveConversation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ threadId, status }: { threadId: number; status: string }) =>
      patchConversationThread(threadId, { status }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: conversationsListKey })
      void qc.invalidateQueries({ queryKey: conversationsActiveCountKey })
      void qc.invalidateQueries({ queryKey: ["conversations", "attention"] })
      void qc.invalidateQueries({ queryKey: ["jobs"] })
    },
    onError: () => toast.error("Не удалось обновить разговор"),
  })
}

/** Закрепить/открепить диалог в списке слева — кнопка под «Удалить» в строке. */
export function usePinConversation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ threadId, pinned }: { threadId: number; pinned: boolean }) =>
      patchConversationThread(threadId, { pinned }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: conversationsListKey })
    },
    onError: () => toast.error("Не удалось закрепить разговор"),
  })
}

export function useDeleteConversation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (threadId: number) => deleteConversationThread(threadId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: conversationsListKey })
      void qc.invalidateQueries({ queryKey: conversationsActiveCountKey })
      toast.success("Разговор удалён")
    },
    onError: () => toast.error("Не удалось удалить разговор"),
  })
}

// F-09/UX7: иконка «Копировать диалог» в списке слева (было — кнопкой в композере открытого
// диалога). Переиспользует кэш `["conversation", vacancyId]`, если диалог уже открывали в этой
// сессии — иначе один лёгкий fetch по клику, без предзагрузки переписки для каждой строки списка.
export function useCopyDialog() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({
      vacancyId,
      contactName,
    }: {
      vacancyId: string
      contactName?: string | null
    }) => {
      const cached = qc.getQueryData<ConversationOut>(["conversation", vacancyId])
      const conv = cached ?? (await fetchConversation(vacancyId))
      return formatHrDialogText(conv.messages, contactName ?? conv.thread?.contact_name)
    },
    onSuccess: (text) => {
      if (!text) {
        toast.message("Нет сообщений с HR для копирования")
        return
      }
      navigator.clipboard.writeText(text).then(
        () => toast.success("Диалог с HR скопирован"),
        () => toast.error("Не удалось скопировать"),
      )
    },
    onError: () => toast.error("Не удалось загрузить диалог"),
  })
}

/** Имя HR и ссылка Telegram в enrichment. */
export function useUpdateHrMeta() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      threadId,
      contactName,
      hrLink,
    }: {
      threadId: number
      contactName?: string
      hrLink?: string
      vacancyId: string
    }) =>
      patchConversationThread(threadId, {
        ...(contactName !== undefined ? { contact_name: contactName.trim() } : {}),
        ...(hrLink !== undefined ? { hr_link: hrLink.trim() } : {}),
      }),
    onSuccess: (_thread: ConvThread, { vacancyId }) => {
      void qc.invalidateQueries({ queryKey: ["conversation", vacancyId] })
      void qc.invalidateQueries({ queryKey: conversationsListKey })
    },
    onError: () => toast.error("Не удалось сохранить контакт HR"),
  })
}

/** Карандаш в шапке: компания/должность (executive-recruiter кейс) — пересчитывает скор, если
 * уже есть текст вакансии. */
export function useUpdateVacancyIdentity() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      vacancyId,
      company,
      title,
    }: {
      vacancyId: string
      company: string
      title: string
    }) => updateConversationIdentity(vacancyId, { company, title }),
    onSuccess: (res) => {
      void qc.invalidateQueries({ queryKey: convKey(res.vacancy_id) })
      void qc.invalidateQueries({ queryKey: conversationsListKey })
      void qc.invalidateQueries({ queryKey: ["jobs"] })
      if (res.scored) invalidateResumeScore(qc)
      toast.success(
        res.scored
          ? `Сохранено, скор пересчитан: ${Math.round(res.overall_score ?? 0)}`
          : "Сохранено",
      )
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Не удалось сохранить компанию/должность"),
  })
}
