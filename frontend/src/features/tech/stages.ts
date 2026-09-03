// Этапы подготовки / sobes-context — подмножество PrepStage (HR-скрининг в «Скрининги»).
// RD-9.2: «Другое» убрано — пять явных форматов, каждый однозначно выбираем в левой панели Техничек.
export const PREP_STAGES = [
  { value: "theory", label: "Теория" },
  { value: "system_design", label: "System design" },
  { value: "live_coding", label: "Live coding" },
  { value: "business_case", label: "Бизнес-кейс" },
  { value: "final", label: "Финал" },
] as const

export const PREP_STAGE_VALUES = PREP_STAGES.map((s) => s.value) as readonly string[]
export const DEFAULT_PREP_STAGE = "theory"

export function toPrepStage(stage?: string): string {
  return stage && PREP_STAGE_VALUES.includes(stage) ? stage : DEFAULT_PREP_STAGE
}

// RD-9.3: interview_format (LLM-классификация транскрипта, core/schemas/interview.py) → PrepStage
// (левая панель форматов Техничек). Разные перечисления — маппинг лучший-по-смыслу, не 1:1.
const INTERVIEW_FORMAT_TO_PREP_STAGE: Record<string, string> = {
  technical: "theory",
  system_design: "system_design",
  final: "final",
  hr_screening: "theory",
  other: DEFAULT_PREP_STAGE,
}

export function mapInterviewFormatToPrepStage(format?: string | null): string {
  return toPrepStage(format ? INTERVIEW_FORMAT_TO_PREP_STAGE[format] : undefined)
}

// RD-19: канон формата собеса на вебе — `interview_stages.stage_type` (core/schemas/interview.py
// InterviewStageType). PrepStage — его проекция для Техничек (подмножество без hr_screening,
// которое живёт в «Скринингах»). soft_skills/manager остаются валидными для LLM-классификатора
// бота (HR-переписка различает «с руководителем»/«софт-скиллы»), но цепочка Техничек не оперирует
// этими категориями отдельно — проецируем обе в «Финал» здесь же, где и `final`. Это уже не только
// фронтовая проекция: FS-3 завёл тот же маппинг soft_skills/manager → FunnelStatus.FINAL на
// бэкенде (STAGE_TO_FUNNEL_STATUS), так что доска и Технички теперь согласованно называют оба
// формата «Финалом» — совпадение сознательное, не два независимых решения.
export const CHAIN_STAGE_LABELS: Record<string, string> = {
  hr_screening: "HR-скрининг",
  live_coding: "Live coding",
  system_design: "System design",
  theory: "Теория",
  business_case: "Бизнес-кейс",
  final: "Финал",
  soft_skills: "Финал",
  manager: "Финал",
}

const CHAIN_STAGE_TO_PREP_STAGE: Record<string, string> = {
  live_coding: "live_coding",
  system_design: "system_design",
  theory: "theory",
  business_case: "business_case",
  final: "final",
  soft_skills: "final",
  manager: "final",
}

// Этап цепочки → PrepStage для генерации подготовки. hr_screening вне Техничек — фолбэк на дефолт.
export function mapChainStageToPrepStage(stageType: string): string {
  return toPrepStage(CHAIN_STAGE_TO_PREP_STAGE[stageType])
}

/** Этап, у которого нет подготовки в Техничках: он живёт в другом разделе. */
export const HR_SCREENING_STAGE_TYPE = "hr_screening"

/**
 * Раздел, которому принадлежит этап цепочки. hr_screening готовится в «Скринингах», поэтому
 * клик по нему уводит туда, а не пытается выбрать несуществующий формат технички: раньше он
 * молча падал в `toPrepStage(undefined)` → «Теория», и по ощущению «этап не выбирается вообще».
 */
export function stageChainTarget(stageType: string): "screening" | "tech" {
  return stageType === HR_SCREENING_STAGE_TYPE ? "screening" : "tech"
}

/** Этап цепочки, к которому Технички умеют готовить (всё, кроме HR-скрининга). */
export function isTechChainStage(stageType: string): boolean {
  return stageChainTarget(stageType) === "tech"
}

// Типы этапов, которые можно добавить в цепочку руками (StageChain «+ Добавить этап»). soft_skills/
// manager сюда не входят — это категории LLM-классификатора HR-переписки бота, не ручного выбора.
export const CHAIN_ADDABLE_STAGE_TYPES = [
  "hr_screening",
  "live_coding",
  "system_design",
  "theory",
  "business_case",
  "final",
] as const

/** У вакансии максимум один HR-скрининг: оставляем «лучший» экземпляр, дубликаты отбрасываем. */
const HR_SCREENING_STATUS_RANK: Record<string, number> = {
  completed: 0,
  failed: 1,
  scheduled: 2,
  rescheduled: 2,
  cancelled: 3,
}

export function preferUniqueHrScreeningStages<
  T extends { id: number; stage_type: string; status: string; position: number },
>(stages: T[]): T[] {
  const hrs = stages.filter((s) => s.stage_type === "hr_screening")
  if (hrs.length <= 1) return stages
  const keep = hrs.reduce((best, cur) => {
    const br = HR_SCREENING_STATUS_RANK[best.status] ?? 9
    const cr = HR_SCREENING_STATUS_RANK[cur.status] ?? 9
    if (cr !== br) return cr < br ? cur : best
    if (cur.position !== best.position) return cur.position < best.position ? cur : best
    return cur.id < best.id ? cur : best
  })
  return stages.filter((s) => s.stage_type !== "hr_screening" || s.id === keep.id)
}
