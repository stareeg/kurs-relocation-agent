import type { ResumeData } from "@/api/resume"

type CriteriaInput = Pick<ResumeData, "position" | "search_criteria">

/** Зеркало `core/domains/profile/score_criteria.py` — ключи незаполненных полей.
 *  Пустой market_segment = «Любые», это валидный выбор, не gap. */
export type LeftPanelGapKey =
  | "role_kind"
  | "niches"
  | "grade_or_salary"
  | "schedule"

const LEFT_PANEL_HINTS: Record<LeftPanelGapKey, string> = {
  role_kind: "Укажите тип роли — «делаю руками» или «управляю людьми»",
  niches: "Добавьте хотя бы одну нишу в приоритетах",
  grade_or_salary: "Укажите целевой грейд или зарплатную вилку",
  schedule: "Выберите формат работы — офис, гибрид или удалёнка",
}

export function leftPanelGaps(data: CriteriaInput): LeftPanelGapKey[] {
  const gaps: LeftPanelGapKey[] = []
  const sc = data.search_criteria
  const pos = data.position
  if (!sc?.role_kind?.trim()) gaps.push("role_kind")
  if (!(sc?.niches ?? []).some((n) => n.trim())) gaps.push("niches")
  if (
    !(pos?.grade?.length ?? 0) &&
    !pos?.salary_min &&
    !pos?.salary_comfortable
  ) {
    gaps.push("grade_or_salary")
  }
  if (!(pos?.schedule ?? []).some((s) => s.trim())) gaps.push("schedule")
  return gaps
}

export function leftPanelReadyForScore(data: CriteriaInput): boolean {
  return leftPanelGaps(data).length === 0
}

export function leftPanelHints(data: CriteriaInput): string[] {
  return leftPanelGaps(data).map((k) => LEFT_PANEL_HINTS[k])
}
