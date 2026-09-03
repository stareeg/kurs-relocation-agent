/**
 * Отображение шкал балла резюме: бэк хранит каждую 0–100, итог — среднее доступных.
 * На карточке показываем вклад в итог (как «21/25» у вакансии), а не сырую сотку.
 */

export const RESUME_SUBSCALE_KEYS = [
  "structure",
  "market_coverage",
  "writing",
  "role_fit",
] as const

export type ResumeSubscaleKey = (typeof RESUME_SUBSCALE_KEYS)[number]

type ScoreLike = {
  structure: number
  market_coverage: number | null
  writing: number
  role_fit: number
}

/** Сколько шкал входит в среднее (рынок без корпуса — не входит). */
export function availableSubscaleCount(score: ScoreLike): number {
  return RESUME_SUBSCALE_KEYS.filter((key) => score[key] != null).length
}

/** Максимум вклада шкалы в итог 0–100. 4 шкалы → 25, без рынка → 33. */
export function subscaleWeight(availableCount: number): number {
  if (availableCount <= 0) return 0
  return Math.round(100 / availableCount)
}

/** Текущий вклад шкалы в итог: 84 из 100 при весе 25 → 21. */
export function subscaleContribution(score0to100: number, weight: number): number {
  return Math.round((Math.max(0, score0to100) * weight) / 100)
}

export function formatSubscaleScore(score0to100: number, weight: number): string {
  return `${subscaleContribution(score0to100, weight)}/${weight}`
}
