import type { components } from "@/api/schema"
import { api } from "@/api/client"

export type InterviewStageOut = components["schemas"]["InterviewStageOut"]
export type InterviewStageListResponse = components["schemas"]["InterviewStageListResponse"]
export type InterviewStageCreate = components["schemas"]["InterviewStageCreate"]
export type InterviewStagePatch = components["schemas"]["InterviewStagePatch"]
export type InterviewStageType = InterviewStageOut["stage_type"]

const BASE = "/api/interview-stages"

// GET — цепочка этапов вакансии по порядку (RD-19). Нет PG → пустой список, степпер не падает.
export function fetchInterviewStages(vacancyId: string) {
  return api.get<InterviewStageListResponse>(`${BASE}/${encodeURIComponent(vacancyId)}`)
}

// POST — добавить этап из канона в конец цепочки.
export function createInterviewStage(vacancyId: string, body: InterviewStageCreate) {
  return api.post<InterviewStageOut>(`${BASE}/${encodeURIComponent(vacancyId)}`, body)
}

// PATCH — точечная правка этапа (дата/формат/статус/заметка), None-поля не трогает.
export function patchInterviewStage(vacancyId: string, stageId: number, body: InterviewStagePatch) {
  return api.patch<InterviewStageOut>(`${BASE}/${encodeURIComponent(vacancyId)}/${stageId}`, body)
}

// PATCH — переставить порядок цепочки (перетаскивание в UI).
export function reorderInterviewStages(vacancyId: string, orderedIds: number[]) {
  return api.patch<InterviewStageListResponse>(`${BASE}/${encodeURIComponent(vacancyId)}/reorder`, {
    ordered_ids: orderedIds,
  })
}

// DELETE — убрать этап из цепочки.
export function deleteInterviewStage(vacancyId: string, stageId: number) {
  return api.del<void>(`${BASE}/${encodeURIComponent(vacancyId)}/${stageId}`)
}
