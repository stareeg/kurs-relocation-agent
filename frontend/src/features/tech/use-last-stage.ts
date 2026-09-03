import { HR_SCREENING_STAGE_TYPE, PREP_STAGE_VALUES } from "./stages"

// Технички запоминают последний выбранный этап на вакансию: раньше при возврате на вакансию
// всегда выбирался ближайший ожидаемый tech-этап (`autoTechStage`) - HR-скрининг никогда не был
// дефолтом, и выбор владельца не переживал переключение между вакансиями/разделами. Теперь дефолт
// для новой/незнакомой вакансии - HR-скрининг (он валиден всегда, в отличие от конкретного
// tech-формата), а для уже посещённой - последний выбор. Один ключ localStorage на вакансию, тот
// же приём, что `loadReviewed`/`saveReviewed` в QuestionsChatPanel.tsx.

export type LastStage = { stage: string; manualStageId: number | null }

function storageKey(vacancyId: string): string {
  return `copilot.tech.last-stage:${vacancyId}`
}

function isValidStage(stage: unknown): stage is string {
  return (
    typeof stage === "string" &&
    (stage === HR_SCREENING_STAGE_TYPE || PREP_STAGE_VALUES.includes(stage))
  )
}

export function loadLastStage(vacancyId: string): LastStage | null {
  try {
    const raw = localStorage.getItem(storageKey(vacancyId))
    if (!raw) return null
    const parsed = JSON.parse(raw) as unknown
    if (!parsed || typeof parsed !== "object") return null
    const stage = (parsed as Record<string, unknown>).stage
    if (!isValidStage(stage)) return null
    const rawId = (parsed as Record<string, unknown>).manualStageId
    const manualStageId = typeof rawId === "number" && Number.isFinite(rawId) ? rawId : null
    return { stage, manualStageId }
  } catch {
    // повреждённые данные/приватный режим - как будто записи не было, дефолт решит вызывающий
    return null
  }
}

export function saveLastStage(vacancyId: string, value: LastStage): void {
  try {
    localStorage.setItem(storageKey(vacancyId), JSON.stringify(value))
  } catch {
    // quota/приватный режим - деградируем без персиста
  }
}
