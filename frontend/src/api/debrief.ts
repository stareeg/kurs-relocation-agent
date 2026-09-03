import type { components } from "@/api/schema"
import { api, LLM_TIMEOUT_MS } from "@/api/client"

export type DebriefResult = components["schemas"]["DebriefResult"]
export type DebriefHistory = components["schemas"]["DebriefHistory"]
export type DebriefAnalysis = components["schemas"]["DebriefAnalysis"]
export type DebriefAnalyzeRequest = components["schemas"]["DebriefAnalyzeRequest"]
export type DebriefJobStarted = components["schemas"]["DebriefJobStarted"]
export type DebriefJobStatus = components["schemas"]["DebriefJobStatus"]
export type DebriefStageIndex = components["schemas"]["DebriefStageIndex"]
export type WeakAnswer = components["schemas"]["WeakAnswer"]
export type NextStepsSignal = DebriefAnalysis["next_steps_signal"]
// JS-14: карта компетенций + честный счёт + формат интервью.
export type DebriefCompetency = components["schemas"]["MockCompetency"]
// Уровень владения темой - общий словарь для Прогресса и разбора собеса (mastery.ts).
export type MockMastery = NonNullable<DebriefCompetency["level"]>
export type HonestNote = components["schemas"]["HonestNote"]
export type InterviewFormat = DebriefAnalysis["interview_format"]
// DBR-3: транскрипт, сегментированный LLM на реплики вопрос/ответ.
export type TranscriptTurn = components["schemas"]["TranscriptTurn"]

// POST /api/debrief/{id}/analyze — DBR-2: завести фоновую задачу разбора, вернуть job_id сразу
// (202) без ожидания LLM. Результат забирается опросом fetchDebriefJobStatus.
export function startDebriefAnalysis(vacancyId: string, body: DebriefAnalyzeRequest) {
  return api.post<DebriefJobStarted>(
    `/api/debrief/${encodeURIComponent(vacancyId)}/analyze`,
    body,
    { timeoutMs: LLM_TIMEOUT_MS },
  )
}

// GET /api/debrief/{id}/analyze/{job_id} — статус фоновой задачи разбора (running|done|error).
export function fetchDebriefJobStatus(vacancyId: string, jobId: string) {
  return api.get<DebriefJobStatus>(
    `/api/debrief/${encodeURIComponent(vacancyId)}/analyze/${encodeURIComponent(jobId)}`,
  )
}

// GET /api/debrief/{id} — накопленная история разборов по вакансии (свежие первыми, UI-5).
// Нет PG → пустой список (вкладка не падает).
export function fetchDebriefHistory(vacancyId: string) {
  return api.get<DebriefHistory>(`/api/debrief/${encodeURIComponent(vacancyId)}`)
}

// PATCH /api/debrief/{id}/{debrief_id} — UX5-5: точечная правка текста транскрипта (спойлер
// «звонка» в Чатах) без перезапуска LLM-анализа.
export function patchDebriefTranscript(vacancyId: string, debriefId: number, transcript: string) {
  return api.patch<DebriefResult>(`/api/debrief/${encodeURIComponent(vacancyId)}/${debriefId}`, {
    transcript,
  })
}

// GET /api/debrief/stage-index — по каким вакансиям/этапам расшифровка уже разобрана. Рельс
// Скринингов/Техничек рисует по этому индексу отметку на карточке: иначе пришлось бы тянуть
// историю разборов на каждую карточку списка.
export function fetchDebriefStageIndex() {
  return api.get<DebriefStageIndex>("/api/debrief/stage-index")
}
