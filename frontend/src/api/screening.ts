import type { components } from "@/api/schema"
import { api, ApiError, LLM_TIMEOUT_MS } from "@/api/client"
import { eventKind, streamSse } from "@/api/sse"
import type { TelegramPushResponse } from "@/api/telegram"

// Раздел «Скрининги»: канонический пакет (защита + нападение, FR3-49/50).
export type QuestionGroup = components["schemas"]["QuestionGroup"]
export type ScreeningQuestion = components["schemas"]["ScreeningQuestion"]
export type HrQuestion = components["schemas"]["HrQuestion"]
export type PitchBlock = components["schemas"]["PitchBlock"]
export type SavedScreeningQuestions = components["schemas"]["SavedScreeningQuestions"]

export type ScreeningQuestionsInput = {
  title?: string
  company?: string
  vacancy_text?: string
}

export type ScreeningMoreQuestionsInput = ScreeningQuestionsInput & {
  kind: "hr" | "ask"
  count?: number
}

export type ScreeningStreamEvent =
  | { type: "status"; stage?: string; label?: string }
  | { type: "brief" | "pitch" | "questions"; partial: SavedScreeningQuestions }
  | { type: "part_error"; stage?: string; message?: string }
  | { type: "done"; pack: SavedScreeningQuestions }
  | { type: "error"; detail?: string }

// GET /api/screening/{vacancy_id} — сохранённый пакет. Нет записи → пустые groups/pitch_blocks.
export function fetchScreeningQuestions(vacancyId: string) {
  return api.get<SavedScreeningQuestions>(`/api/screening/${encodeURIComponent(vacancyId)}`)
}

/** SSE-стрим генерации (A-14): частичные пакеты + финальный saved pack. */
export async function generateScreeningQuestionsStream(
  vacancyId: string,
  body: ScreeningQuestionsInput,
  onEvent: (event: ScreeningStreamEvent) => void,
  signal?: AbortSignal,
): Promise<SavedScreeningQuestions> {
  const path = `/api/screening/${encodeURIComponent(vacancyId)}/generate`
  let finalPack: SavedScreeningQuestions | null = null
  let streamError: string | null = null

  await streamSse(path, {
    body,
    signal,
    timeoutMs: LLM_TIMEOUT_MS,
    rumInteraction: "screening",
    onEvent: (e) => {
      const kind = eventKind(e)
      const data = e.data as ScreeningStreamEvent & Record<string, unknown>
      if (kind === "error" || e.event === "error") {
        const detail =
          (typeof data.detail === "string" && data.detail) ||
          (typeof data.message === "string" && data.message) ||
          "Не удалось собрать пакет"
        streamError = detail
        onEvent({ type: "error", detail })
        return
      }
      if (kind === "done" || e.event === "done") {
        const pack = data.pack as SavedScreeningQuestions | undefined
        if (pack) {
          finalPack = pack
          onEvent({ type: "done", pack })
        }
        return
      }
      onEvent(data as ScreeningStreamEvent)
    },
  })

  if (streamError) throw new ApiError(502, streamError)
  if (!finalPack) {
    throw new ApiError(502, "Стрим завершился без готового пакета")
  }
  return finalPack
}

// POST /api/screening/{vacancy_id}/more-questions — ещё пачка вопросов (hr|ask).
export function generateMoreScreeningQuestions(
  vacancyId: string,
  body: ScreeningMoreQuestionsInput,
) {
  return api.post<SavedScreeningQuestions>(
    `/api/screening/${encodeURIComponent(vacancyId)}/more-questions`,
    body,
    { timeoutMs: LLM_TIMEOUT_MS },
  )
}

// POST /api/screening/{vacancy_id}/delete-question — удалить один вопрос (hr|ask).
export function deleteScreeningQuestion(
  vacancyId: string,
  body: { kind: "hr" | "ask"; question: string },
) {
  return api.post<SavedScreeningQuestions>(
    `/api/screening/${encodeURIComponent(vacancyId)}/delete-question`,
    body,
  )
}

// POST /api/screening/{vacancy_id}/regen-pitch — только легенда/мосты, вопросы не трогать.
export function regenerateScreeningPitch(vacancyId: string, body: ScreeningQuestionsInput) {
  return api.post<SavedScreeningQuestions>(
    `/api/screening/${encodeURIComponent(vacancyId)}/regen-pitch`,
    body,
    { timeoutMs: LLM_TIMEOUT_MS },
  )
}

// PATCH /api/screening/{vacancy_id}/pitch — ручная правка «Рассказа об опыте» (закреплённое
// сообщение в чате Скринингов, п.2) — схлопывает pitch_blocks в плоский oral_pitch.
export function editScreeningPitch(vacancyId: string, oralPitch: string) {
  return api.patch<SavedScreeningQuestions>(`/api/screening/${encodeURIComponent(vacancyId)}/pitch`, {
    oral_pitch: oralPitch,
  })
}

// POST /api/screening/{vacancy_id}/chat-summary-push — LLM-саммари «Агент»-чата → пуш в Telegram
// (продолжить разговор про вакансию там же).
export function pushScreeningChatSummary(vacancyId: string) {
  return api.post<TelegramPushResponse>(
    `/api/screening/${encodeURIComponent(vacancyId)}/chat-summary-push`,
    undefined,
    { timeoutMs: LLM_TIMEOUT_MS },
  )
}
