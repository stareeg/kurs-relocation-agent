import type { components } from "@/api/schema"
import { api, ApiError, LLM_TIMEOUT_MS } from "@/api/client"
import { eventKind, streamSse } from "@/api/sse"

export type PrepResult = components["schemas"]["PrepResult"]
export type PrepQuestionOut = components["schemas"]["PrepQuestionOut"]
export type PrepCompanyProfile = components["schemas"]["PrepCompanyProfile"]
export type PrepGenerateRequest = components["schemas"]["PrepGenerateRequest"]
export type PrepChatHistory = components["schemas"]["PrepChatHistory"]
export type PrepChatMessageOut = components["schemas"]["PrepChatMessageOut"]
export type PrepChatRequest = components["schemas"]["PrepChatRequest"]
export type PrepChatResponse = components["schemas"]["PrepChatResponse"]
export type PrepSobesContextRequest = components["schemas"]["PrepSobesContextRequest"]
export type PrepSobesContextResponse = components["schemas"]["PrepSobesContextResponse"]
export type PrepPackDocument = components["schemas"]["PrepPackDocument"]
export type PrepPackRequest = components["schemas"]["PrepPackRequest"]
export type PrepPackRegenerateResponse = components["schemas"]["PrepPackRegenerateResponse"]
export type PrepPackSaveRequest = components["schemas"]["PrepPackSaveRequest"]
export type PrepExportContextResponse = components["schemas"]["PrepExportContextResponse"]
export type PrepTopicOut = components["schemas"]["PrepTopicOut"]
export type PrepTopicsResponse = components["schemas"]["PrepTopicsResponse"]
export type PrepTopicsGenerateRequest = components["schemas"]["PrepTopicsGenerateRequest"]
export type PrepTopicsReviewRequest = components["schemas"]["PrepTopicsReviewRequest"]
export type PrepTopicExpandRequest = components["schemas"]["PrepTopicExpandRequest"]
export type PrepTopicExpandResponse = components["schemas"]["PrepTopicExpandResponse"]
export type PrepParseExternalRequest = components["schemas"]["PrepParseExternalRequest"]

export function fetchPrep(vacancyId: string, stage: string, company?: string | null) {
  const params = new URLSearchParams({ stage })
  if (company?.trim()) params.set("company", company.trim())
  return api.get<PrepResult>(`/api/prep/${encodeURIComponent(vacancyId)}?${params}`)
}

export type PrepStreamEvent =
  | { type: "status"; stage?: string; label?: string }
  | { type: "questions"; questions: PrepQuestionOut[] }
  | { type: "part_error"; stage?: string; message?: string }
  | { type: "done"; prep: PrepResult }
  | { type: "error"; detail?: string }

/** SSE-стрим генерации (A-14/L-49): части вопросов (answers/ask_them) + финальная подготовка. */
export async function generatePrepStream(
  vacancyId: string,
  body: PrepGenerateRequest,
  onEvent: (event: PrepStreamEvent) => void,
  signal?: AbortSignal,
): Promise<PrepResult> {
  const path = `/api/prep/${encodeURIComponent(vacancyId)}/generate`
  let finalResult: PrepResult | null = null
  let streamError: string | null = null

  await streamSse(path, {
    body,
    signal,
    timeoutMs: LLM_TIMEOUT_MS,
    rumInteraction: "prep",
    onEvent: (e) => {
      const kind = eventKind(e)
      const data = e.data as PrepStreamEvent & Record<string, unknown>
      if (kind === "error" || e.event === "error") {
        const detail =
          (typeof data.detail === "string" && data.detail) ||
          (typeof data.message === "string" && data.message) ||
          "Не удалось собрать подготовку"
        streamError = detail
        onEvent({ type: "error", detail })
        return
      }
      if (kind === "done" || e.event === "done") {
        const result = data.prep as PrepResult | undefined
        if (result) {
          finalResult = result
          onEvent({ type: "done", prep: result })
        }
        return
      }
      onEvent(data as PrepStreamEvent)
    },
  })

  if (streamError) throw new ApiError(502, streamError)
  if (!finalResult) {
    throw new ApiError(502, "Стрим завершился без готовой подготовки")
  }
  return finalResult
}

export function fetchPrepChat(vacancyId: string) {
  return api.get<PrepChatHistory>(`/api/prep/${encodeURIComponent(vacancyId)}/chat`)
}

export function sendPrepChat(vacancyId: string, body: PrepChatRequest) {
  return api.post<PrepChatResponse>(`/api/prep/${encodeURIComponent(vacancyId)}/chat`, body, {
    timeoutMs: LLM_TIMEOUT_MS,
  })
}

export function clearPrepChat(vacancyId: string) {
  return api.del<{ removed: number }>(`/api/prep/${encodeURIComponent(vacancyId)}/chat`)
}

export function deletePrepChatMessage(vacancyId: string, messageId: number) {
  return api.del<PrepChatHistory>(`/api/prep/${encodeURIComponent(vacancyId)}/chat/${messageId}`)
}

export function clearPrepQuestions(vacancyId: string, stage: string) {
  const params = new URLSearchParams({ stage })
  return api.del<{ cleared: boolean }>(
    `/api/prep/${encodeURIComponent(vacancyId)}/questions?${params}`,
  )
}

export function generateSobesContext(vacancyId: string, body: PrepSobesContextRequest) {
  return api.post<PrepSobesContextResponse>(
    `/api/prep/${encodeURIComponent(vacancyId)}/sobes-context`,
    body,
    { timeoutMs: LLM_TIMEOUT_MS },
  )
}

export function fetchPrepPack(vacancyId: string, stage: string) {
  const params = new URLSearchParams({ stage })
  return api.get<PrepPackDocument>(`/api/prep/${encodeURIComponent(vacancyId)}/pack?${params}`)
}

export function regeneratePrepPack(vacancyId: string, body: PrepPackRequest) {
  return api.post<PrepPackRegenerateResponse>(
    `/api/prep/${encodeURIComponent(vacancyId)}/pack/regenerate`,
    body,
    { timeoutMs: LLM_TIMEOUT_MS },
  )
}

export function savePrepPack(vacancyId: string, body: PrepPackSaveRequest) {
  return api.put<PrepPackDocument>(`/api/prep/${encodeURIComponent(vacancyId)}/pack`, body)
}

export function fetchExportContext(vacancyId: string, stage?: string) {
  const params = stage ? `?${new URLSearchParams({ stage })}` : ""
  return api.get<PrepExportContextResponse>(
    `/api/prep/${encodeURIComponent(vacancyId)}/export-context${params}`,
  )
}

export function fetchPrepTopics(vacancyId: string, stage: string) {
  const params = new URLSearchParams({ stage })
  return api.get<PrepTopicsResponse>(`/api/prep/${encodeURIComponent(vacancyId)}/topics?${params}`)
}

export function generatePrepTopics(vacancyId: string, body: PrepTopicsGenerateRequest) {
  return api.post<PrepTopicsResponse>(
    `/api/prep/${encodeURIComponent(vacancyId)}/topics/generate`,
    body,
    { timeoutMs: LLM_TIMEOUT_MS },
  )
}

export function reviewPrepTopics(vacancyId: string, body: PrepTopicsReviewRequest) {
  return api.post<PrepTopicsResponse>(
    `/api/prep/${encodeURIComponent(vacancyId)}/topics/review`,
    body,
  )
}

// П.5c: раскрытие темы из разбора реального собеса (basic-tier LLM, stateles). Кэшируется
// на бэке по теме+вакансии; на клиенте — react-query по topic.
export function expandPrepTopic(vacancyId: string, body: PrepTopicExpandRequest) {
  return api.post<PrepTopicExpandResponse>(
    `/api/prep/${encodeURIComponent(vacancyId)}/topics/expand`,
    body,
    { timeoutMs: LLM_TIMEOUT_MS },
  )
}

export function parseExternalPrep(vacancyId: string, body: PrepParseExternalRequest) {
  return api.post<PrepChatResponse>(
    `/api/prep/${encodeURIComponent(vacancyId)}/parse-external`,
    body,
    { timeoutMs: LLM_TIMEOUT_MS },
  )
}
