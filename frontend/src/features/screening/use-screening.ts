import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { OPENROUTER_MISSING_TOAST } from "@/lib/toasts"
import { ApiError } from "@/api/client"
import {
  deleteScreeningQuestion,
  editScreeningPitch,
  fetchScreeningQuestions,
  generateMoreScreeningQuestions,
  generateScreeningQuestionsStream,
  pushScreeningChatSummary,
  regenerateScreeningPitch,
  type ScreeningMoreQuestionsInput,
  type ScreeningQuestionsInput,
  type SavedScreeningQuestions,
} from "@/api/screening"

// Сохранённые вопросы под вакансию (из БД). Включается, когда выбрана вакансия.
export function useScreeningQuestions(vacancyId: string | null) {
  return useQuery({
    queryKey: ["screening-questions", vacancyId],
    queryFn: () => fetchScreeningQuestions(vacancyId!),
    enabled: !!vacancyId,
    staleTime: 30_000,
  })
}

// Сгенерировать пакет под вакансию (LLM-стрим) и сохранить. Частичные куски сразу в кэш.
export function useGenerateScreeningQuestions() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ vacancyId, body }: { vacancyId: string; body: ScreeningQuestionsInput }) =>
      generateScreeningQuestionsStream(vacancyId, body, (event) => {
        if (event.type === "brief" || event.type === "pitch" || event.type === "questions") {
          qc.setQueryData<SavedScreeningQuestions>(
            ["screening-questions", vacancyId],
            event.partial,
          )
        }
        if (event.type === "part_error") {
          const msg =
            event.stage === "pitch"
              ? "Легенда не собралась — можно пересобрать отдельно"
              : "Вопросы не собрались — можно добавить отдельно"
          toast.error(msg)
        }
        if (event.type === "done") {
          qc.setQueryData<SavedScreeningQuestions>(["screening-questions", vacancyId], event.pack)
        }
      }),
    onSuccess: (data) => {
      qc.setQueryData<SavedScreeningQuestions>(["screening-questions", data.vacancy_id], data)
    },
    onError: () => toast.error(OPENROUTER_MISSING_TOAST),
  })
}

// Ещё пачка вопросов (hr|ask) без пересборки легенды.
export function useGenerateMoreScreeningQuestions() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ vacancyId, body }: { vacancyId: string; body: ScreeningMoreQuestionsInput }) =>
      generateMoreScreeningQuestions(vacancyId, body),
    onSuccess: (data) => {
      qc.setQueryData<SavedScreeningQuestions>(["screening-questions", data.vacancy_id], data)
      toast.success("Добавил ещё вопросы")
    },
    onError: () => toast.error(OPENROUTER_MISSING_TOAST),
  })
}

// Пересобрать только легенду под вакансию (вопросы HR не трогаем).
export function useRegenerateScreeningPitch() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ vacancyId, body }: { vacancyId: string; body: ScreeningQuestionsInput }) =>
      regenerateScreeningPitch(vacancyId, body),
    onSuccess: (data) => {
      qc.setQueryData<SavedScreeningQuestions>(["screening-questions", data.vacancy_id], data)
      toast.success("Легенда пересобрана")
    },
    onError: () => toast.error(OPENROUTER_MISSING_TOAST),
  })
}

// Ручная правка «Рассказа об опыте» (закреплённое сообщение в чате Скринингов, п.2) — молча
// схлопывает pitch_blocks в плоский oral_pitch, как автосохранение VacancyPinnedText.
export function useEditScreeningPitch() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ vacancyId, oralPitch }: { vacancyId: string; oralPitch: string }) =>
      editScreeningPitch(vacancyId, oralPitch),
    onSuccess: (data) => {
      qc.setQueryData<SavedScreeningQuestions>(["screening-questions", data.vacancy_id], data)
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Не удалось сохранить рассказ об опыте"),
  })
}

// Саммари переписки «Агент»-чата (LLM) → пуш в Telegram-бота (продолжить разговор там же).
export function usePushScreeningChatSummary() {
  return useMutation({
    mutationFn: (vacancyId: string) => pushScreeningChatSummary(vacancyId),
    onSuccess: () => toast.success("Саммари отправлено в Telegram"),
    onError: (err) =>
      toast.error(err instanceof Error ? err.message : "Не удалось отправить в Telegram"),
  })
}

// Удалить один вопрос (hr|ask) из пакета. Обновляет кэш и сегмент карточек локально.
export function useDeleteScreeningQuestion() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      vacancyId,
      body,
    }: {
      vacancyId: string
      body: { kind: "hr" | "ask"; question: string }
    }) => deleteScreeningQuestion(vacancyId, body),
    onSuccess: (data) => {
      qc.setQueryData<SavedScreeningQuestions>(["screening-questions", data.vacancy_id], data)
      toast.success("Вопрос удалён")
    },
    onError: () => toast.error("Не удалось удалить вопрос"),
  })
}
