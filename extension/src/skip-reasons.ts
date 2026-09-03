/**
 * Канон чипов пропуска вакансии (JS-22.0 / FR2-78).
 * Sync: core/domains/opportunities/skip_reasons.json ← SELF_SKIP_REASONS
 * (python -m core.domains.opportunities.dump_skip_reasons).
 *
 * Статичные канонические причины — фолбэк, когда LLM-причины ещё не сгенерированы
 * или недоступны. «Избегать компанию» — отдельная статичная кнопка (не в массиве
 * LLM-причин): она не зависит от текста вакансии и всегда доступна.
 */
export const SKIP_REASONS = [
  'Низкий грейд',
  'Низкая зарплата',
  'Не тот стек/домен',
  'Не тот формат',
  'Не та роль (IC vs рук)',
  'Избегать компанию',
] as const

export type SkipReason = (typeof SKIP_REASONS)[number]

/** Статичная кнопка «Избегать компанию» — отдельная от LLM-чипов пропуска. */
export const DODGY_COMPANY_REASON = 'Избегать компанию' as const

/** LLM-генерируемые чипы — те 5 осей, под которые LLM формирует конкретные причины. */
export const LLM_CANONICAL_AXES = [
  'Низкий грейд',
  'Низкая зарплата',
  'Не тот стек/домен',
  'Не тот формат',
  'Не та роль (IC vs рук)',
] as const

/** Один LLM-чип: краткий лейбл + каноническая причина для маппинга. */
export interface SkipReasonSuggestion {
  text: string
  canonical: string
}
