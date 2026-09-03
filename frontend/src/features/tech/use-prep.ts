import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import {
  deletePrepChatMessage,
  fetchExportContext,
  fetchPrep,
  fetchPrepChat,
  fetchPrepPack,
  fetchPrepTopics,
  expandPrepTopic,
  generatePrepStream,
  generatePrepTopics,
  generateSobesContext,
  parseExternalPrep,
  regeneratePrepPack,
  reviewPrepTopics,
  savePrepPack,
  sendPrepChat,
  type PrepChatHistory,
  type PrepChatRequest,
  type PrepGenerateRequest,
  type PrepPackDocument,
  type PrepPackRequest,
  type PrepPackSaveRequest,
  type PrepParseExternalRequest,
  type PrepQuestionOut,
  type PrepResult,
  type PrepSobesContextRequest,
  type PrepSobesContextResponse,
  type PrepTopicExpandRequest,
  type PrepTopicsGenerateRequest,
  type PrepTopicsResponse,
  type PrepTopicsReviewRequest,
} from "@/api/prep"

// Сохранённая подготовка под (vacancy, stage). Тянем только когда выбрана вакансия; не собираем
// заново при каждом фокусе — подготовка стабильна, генерация дёргается кнопкой. `company`
// подбирает профиль РФ-бигтеха и подгоняет состав подготовки (JS-4.2).
export function usePrep(vacancyId: string | null, stage: string, company?: string | null) {
  return useQuery({
    queryKey: ["prep", vacancyId, stage, company ?? ""],
    queryFn: () => fetchPrep(vacancyId!, stage, company),
    enabled: !!vacancyId,
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  })
}

// Генерация подготовки (LLM): части вопросов (answers/ask_them) приезжают по мере готовности
// (L-49) — партиал сразу в кэш ["prep", vacancy, stage]. Также инвалидируем sobes-context — он
// опирается на prep-вопросы, должен перегенериться.
export function useGeneratePrep(vacancyId: string | null, stage: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: PrepGenerateRequest) =>
      generatePrepStream(vacancyId!, body, (event) => {
        if (event.type === "questions") {
          qc.setQueriesData<PrepResult>({ queryKey: ["prep", vacancyId, stage] }, (prev) =>
            prev ? { ...prev, questions: event.questions } : prev,
          )
        }
        if (event.type === "part_error") {
          toast.error(
            event.stage === "answers"
              ? "Вопросы не собрались — попробуйте ещё раз"
              : "Вопросы к HR не собрались — попробуйте ещё раз",
          )
        }
        if (event.type === "done") {
          // queryKey usePrep включает company — setQueryData без него не обновлял UI после генерации.
          qc.setQueriesData<PrepResult>({ queryKey: ["prep", vacancyId, stage] }, () => event.prep)
        }
      }),
    onSuccess: () => {
      qc.removeQueries({ queryKey: ["sobes-context", vacancyId, stage] })
      toast.success("Подготовка готова")
    },
    onError: (err) =>
      toast.error(err instanceof Error ? err.message : "Не удалось собрать подготовку"),
  })
}

// История чата подготовки по вакансии (накопительная, общая для всех этапов).
export function usePrepChat(vacancyId: string | null) {
  return useQuery({
    queryKey: ["prep-chat", vacancyId],
    queryFn: () => fetchPrepChat(vacancyId!),
    enabled: !!vacancyId,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  })
}

// Отправить сообщение в чат подготовки. onSuccess инвалидируем историю — она перетянется с
// обеими новыми репликами (user + assistant). PREP-3: если ассистент распознал «ещё пачку
// вопросов», result.questions непусто — смёрджить их в кэш ["prep", vacancy, stage] (append),
// чтобы грид карточек обновился сразу, без похода на бэк (тот же паттерн, что useGeneratePrep
// кладёт результат через setQueriesData). `onQuestions` — коллбэк для подсветки новых карточек
// (TechPage), общий для обычного композера и кнопки «Ещё вопросов».
export function useSendPrepChat(
  vacancyId: string | null,
  stage?: string,
  onQuestions?: (questions: PrepQuestionOut[], topic: string | null) => void,
) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: PrepChatRequest) => sendPrepChat(vacancyId!, body),
    onSuccess: (result) => {
      void qc.invalidateQueries({ queryKey: ["prep-chat", vacancyId] })
      if (result.questions.length > 0 && stage) {
        qc.setQueriesData<PrepResult>({ queryKey: ["prep", vacancyId, stage] }, (prev) =>
          prev ? { ...prev, questions: [...prev.questions, ...result.questions] } : prev,
        )
        onQuestions?.(result.questions, result.topic ?? null)
      }
    },
    onError: (err) =>
      toast.error(err instanceof Error ? err.message : "Не удалось отправить сообщение"),
  })
}

// Удалить реплики чата подготовки (выделение → Удалить, аналогично разделу «Чаты»). Бэкенд удаляет
// по одной — последовательный цикл, как useVacancyConversation.deleteMessages.
export function useDeletePrepChatMessage(vacancyId: string | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (ids: number[]) => {
      let last: PrepChatHistory | null = null
      for (const id of ids) {
        last = await deletePrepChatMessage(vacancyId!, id)
      }
      return last
    },
    onSuccess: (history) => {
      if (history) qc.setQueryData<PrepChatHistory>(["prep-chat", vacancyId], history)
    },
    onError: (err) =>
      toast.error(err instanceof Error ? err.message : "Не удалось удалить сообщение"),
  })
}

// Сгенерировать markdown-контекст для оверлея sobes.tech под этап (по кнопке).
// Результат кладём в кэш ["sobes-context", vacancy, stage] — не дёргаем LLM на каждый чих.
export function useGenerateSobesContext(vacancyId: string | null, stage: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: PrepSobesContextRequest) => generateSobesContext(vacancyId!, body),
    onSuccess: (result) => {
      qc.setQueryData<PrepSobesContextResponse>(["sobes-context", vacancyId, stage], result)
    },
    onError: (err) =>
      toast.error(err instanceof Error ? err.message : "Не удалось собрать контекст"),
  })
}

// Сохранённый бриф подготовки под (vacancy, stage) — RD-16. Тянем только когда выбрана вакансия,
// не пересобирается сам: сборка/перегенерация — только по кнопке (LLM-вызов, деньги).
export function usePrepPack(vacancyId: string | null, stage: string) {
  return useQuery({
    queryKey: ["prep-pack", vacancyId, stage],
    queryFn: () => fetchPrepPack(vacancyId!, stage),
    enabled: !!vacancyId,
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  })
}

// Собрать свежий бриф (LLM). Ничего не сохраняет — кандидат для ревью на фронте (diff перед
// принятием), как «Перегенерировать легенду».
export function useRegeneratePrepPack(vacancyId: string | null) {
  return useMutation({
    mutationFn: (body: PrepPackRequest) => regeneratePrepPack(vacancyId!, body),
    onError: (err) =>
      toast.error(err instanceof Error ? err.message : "Не удалось собрать подготовку"),
  })
}

// Сохранить принятый бриф — кладём результат прямо в кэш ["prep-pack", vacancy, stage].
export function useSavePrepPack(vacancyId: string | null, stage: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: PrepPackSaveRequest) => savePrepPack(vacancyId!, body),
    onSuccess: (doc) => {
      qc.setQueryData<PrepPackDocument>(["prep-pack", vacancyId, stage], doc)
      // Авто-принятие после генерации - без лишнего тоста «Бриф сохранён».
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : "Не удалось сохранить бриф"),
  })
}

// Скопировать контекст для внешнего LLM (CTX-2) — мутация по клику (не запрос на каждый рендер,
// как остальные генерации LLM-контекста в этом файле). Компонент сам пишет результат в буфер.
export function useExportContext(vacancyId: string | null, stage: string) {
  return useMutation({
    mutationFn: () => fetchExportContext(vacancyId!, stage),
    onError: (err) =>
      toast.error(err instanceof Error ? err.message : "Не удалось собрать контекст"),
  })
}

export function usePrepTopics(vacancyId: string | null, stage: string) {
  return useQuery({
    queryKey: ["prep-topics", vacancyId, stage],
    queryFn: () => fetchPrepTopics(vacancyId!, stage),
    enabled: !!vacancyId,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  })
}

export function useGeneratePrepTopics(vacancyId: string | null, stage: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: PrepTopicsGenerateRequest) => generatePrepTopics(vacancyId!, body),
    onSuccess: (result) => {
      qc.setQueryData<PrepTopicsResponse>(["prep-topics", vacancyId, stage], result)
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : "Не удалось собрать темы"),
  })
}

export function useReviewPrepTopics(vacancyId: string | null, stage: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: PrepTopicsReviewRequest) => reviewPrepTopics(vacancyId!, body),
    onSuccess: (result) => {
      qc.setQueryData<PrepTopicsResponse>(["prep-topics", vacancyId, stage], result)
    },
  })
}

// П.5c: раскрытие темы из разбора реального собеса. useQuery (не мутация) — кэшируем по теме,
// staleTime 5 мин: повторный клик по той же теме не бьёт в LLM. enabled — по клику (open topic).
export function useExpandPrepTopic(
  vacancyId: string | null,
  stage: string,
  topic: string | null,
) {
  return useQuery({
    queryKey: ["prep-topic-expand", vacancyId, stage, topic],
    queryFn: async () => {
      if (!vacancyId || !topic) throw new Error("Не передана тема")
      const body: PrepTopicExpandRequest = { stage: stage as never, topic }
      return expandPrepTopic(vacancyId, body)
    },
    enabled: Boolean(vacancyId && topic),
    staleTime: 5 * 60 * 1000,
    gcTime: 30 * 60 * 1000,
    retry: 0,
  })
}

export function useParseExternalPrep(
  vacancyId: string | null,
  stage: string,
  onQuestions?: (questions: PrepQuestionOut[], topic: string | null) => void,
) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: PrepParseExternalRequest) => parseExternalPrep(vacancyId!, body),
    onSuccess: (result) => {
      void qc.invalidateQueries({ queryKey: ["prep-chat", vacancyId] })
      if (result.questions.length > 0) {
        qc.setQueriesData<PrepResult>({ queryKey: ["prep", vacancyId, stage] }, (prev) =>
          prev ? { ...prev, questions: [...prev.questions, ...result.questions] } : prev,
        )
        onQuestions?.(result.questions, result.topic ?? null)
        toast.success(`Добавил ${result.questions.length} вопросов из переписки`)
      } else {
        toast.message(result.message.content || "Новых вопросов не нашлось")
      }
    },
    onError: (err) =>
      toast.error(err instanceof Error ? err.message : "Не удалось распарсить переписку"),
  })
}
