import type { components } from "@/api/schema"
import { api } from "@/api/client"

export type Job = components["schemas"]["Job"]
export type JobsPageResponse = components["schemas"]["JobsPage"]
export type JobStageResponse = components["schemas"]["JobStageResponse"]
export type JobSkipResponse = components["schemas"]["JobSkipResponse"]
export type JobDeleteResponse = components["schemas"]["JobDeleteResponse"]
export type JobApplyFieldsUpdate = components["schemas"]["JobApplyFieldsUpdate"]
export type JobApplyFieldsResponse = components["schemas"]["JobApplyFieldsResponse"]

// GET /api/jobs — курсорная страница вакансий (L-30, доска): активные этапы первыми, затем
// score/дата на бэке, как раньше. `column_counts` приходит только на первой странице (без cursor)
// — точные тоталы по колонкам kanban независимо от того, что уже догружено.
export function fetchJobsPage({ cursor, limit = 200 }: { cursor?: string; limit?: number } = {}) {
  const params = new URLSearchParams({ limit: String(limit) })
  if (cursor) params.set("cursor", cursor)
  return api.get<JobsPageResponse>(`/api/jobs?${params.toString()}`)
}

// GET /api/jobs/by-vacancy/{vacancy_id} — точечный поиск (F-08): фолбэк для deep-link на
// вакансию за пределами уже догруженных страниц курсора. 404 → ApiError(status=404).
export function fetchJobByVacancyId(vacancyId: string) {
  return api.get<Job>(`/api/jobs/by-vacancy/${encodeURIComponent(vacancyId)}`)
}

export type VacancyActivityEvent = components["schemas"]["VacancyActivityEvent"]
export type VacancyActivityHistory = components["schemas"]["VacancyActivityHistory"]

export function fetchVacancyEvents(vacancyId: string) {
  return api.get<VacancyActivityHistory>(
    `/api/jobs/by-vacancy/${encodeURIComponent(vacancyId)}/events`,
  )
}

// GET /api/jobs/active-count — активные процессы без лимита выборки (счётчик в шапке).
export function fetchActiveJobsCount() {
  return api.get<{ count: number }>("/api/jobs/active-count")
}

// GET /api/jobs/stage-counts — тоталы по колонкам kanban (P-05), без вытягивания страницы
// вакансий целиком: тот же `count_jobs_by_column`, что отдаёт `column_counts` внутри
// `/api/jobs`, но отдельной лёгкой ручкой для бейджей вне доски (шелл).
export function fetchJobStageCounts() {
  return api.get<Record<string, number>>("/api/jobs/stage-counts")
}

// PATCH /api/jobs/{id}/stage — сменить стадию воронки (kanban веба, JS-1.1). `stage` —
// каноническое значение (FUNNEL_STAGES). Источник истины — PG, Sheets — best-effort зеркало.
export function updateJobStage(jobId: number, stage: string) {
  return api.patch<JobStageResponse>(`/api/jobs/${jobId}/stage`, { stage })
}

// POST /api/jobs/{id}/skip — пометить «Пропущено» с доски (решение «не подавать»). reason
// опционален: бэк ставит нейтральный по умолчанию, уточнить можно в дровере. Ортогонально статусу.
export function skipJob(jobId: number, reason?: string) {
  return api.post<JobSkipResponse>(`/api/jobs/${jobId}/skip`, reason ? { reason } : {})
}

// DELETE /api/jobs/{id}/skip — снять пропуск (вернуть вакансию в воронку).
export function unskipJob(jobId: number) {
  return api.del<JobSkipResponse>(`/api/jobs/${jobId}/skip`)
}

// GET /vacancies/{vacancy_id}/skip-reasons — LLM-сгенерированные причины пропуска (6 чипов
// под конкретную вакансию). Пусто — LLM ещё не сгенерировал или недоступен; UI падает на
// статичные канонические причины. task_running — поллим дальше.
export type SkipReasonItem = { text: string; canonical: string }
export type SkipReasonsPoll = {
  vacancy_id: string | null
  reasons: SkipReasonItem[]
  task_running: boolean
}
export function fetchSkipReasons(vacancyId: string) {
  return api.get<SkipReasonsPoll>(`/vacancies/${encodeURIComponent(vacancyId)}/skip-reasons`)
}

// DELETE /api/jobs/{id} — удалить вакансию целиком с доски (JS-1.2: кривая/мусорная карточка).
export function deleteJob(jobId: number) {
  return api.del<JobDeleteResponse>(`/api/jobs/${jobId}`)
}

// PATCH /api/jobs/{id} — поля карточки вакансии (JS-1.2): заметка, дата отклика, флаг письма.
// PATCH-семантика: null/undefined = не менять; note:"" очищает заметку. PG — источник истины.
export function updateJobApplyFields(jobId: number, body: JobApplyFieldsUpdate) {
  return api.patch<JobApplyFieldsResponse>(`/api/jobs/${jobId}`, body)
}

// PATCH /api/jobs/{id}/track — ручная поправка трека (основная / вторая работа). Рескор
// не перетирает: тот же контракт, что у is_salary_locked.
export type JobTrackUpdate = components["schemas"]["JobTrackUpdate"]
export type JobTrackResponse = components["schemas"]["JobTrackResponse"]
export function patchJobTrack(jobId: number, body: JobTrackUpdate) {
  return api.patch<JobTrackResponse>(`/api/jobs/${jobId}/track`, body)
}

// POST /score/{vacancy_id}/salary/recompute — кнопка «Обновить» у зарплаты (шапка чата вакансии
// и дровер): узкий пересчёт вилки в обход полного /score. Зафиксированную вручную вилку
// (source=explicit) не трогает — молча возвращает текущее состояние.
export type SalaryEstimatePoll = components["schemas"]["SalaryEstimatePoll"]
export function recomputeSalary(vacancyId: string) {
  return api.post<SalaryEstimatePoll>(
    `/score/${encodeURIComponent(vacancyId)}/salary/recompute`,
    {},
  )
}

// GET /score/weights-version — версия рубрики скоринга ПРЯМО СЕЙЧАС (Этап 5 §5.1/§5.3): карточка
// сравнивает её со своим score_weights_version и показывает «пересчитать», если рубрика другая.
export type WeightsVersionOut = components["schemas"]["WeightsVersionOut"]
export function fetchCurrentWeightsVersion() {
  return api.get<WeightsVersionOut>("/score/weights-version")
}

// POST /score/{vacancy_id}/recompute-weights — кнопка «Пересчитать» на карточке: узкий пересчёт
// по текущей рубрике в обход полного /score, без LLM.
export type WeightsRecomputeOut = components["schemas"]["WeightsRecomputeOut"]
export function recomputeWeights(vacancyId: string) {
  return api.post<WeightsRecomputeOut>(
    `/score/${encodeURIComponent(vacancyId)}/recompute-weights`,
    {},
  )
}

// GET /score/axis-alignment — Этап 7 §7.2: насколько оси score_breakdown совпадают с решениями
// владельца (откликнулся/нет). Read-only, ничего не пишет.
export type AxisAlignmentReport = components["schemas"]["AxisAlignmentReport"]
export function fetchAxisAlignment() {
  return api.get<AxisAlignmentReport>("/score/axis-alignment")
}

// POST /score/axis-alignment/simulate — Этап 7 §7.3: превью «как изменится топ-20» под
// советующую подсказку. Ничего не сохраняет.
export type SimulatedRank = components["schemas"]["SimulatedRank"]
export function simulateAxisWeights(overrides: Record<string, number>) {
  return api.post<SimulatedRank[]>("/score/axis-alignment/simulate", { overrides })
}
