// Единый канон причин отказа (JS-22.0).
// Sync: core/domains/opportunities/skip_reasons.json ← SELF_SKIP_REASONS (FR2-78; dump: python -m core.domains.opportunities.dump_skip_reasons).
//
// Канон был переименован (2026-08-10):
// - «Риск выгорания» → «Не та роль (IC vs рук)» — причина связана с балансом
//   IC/менеджерских функций, а не с выгоранием; старое название было неинтуитивно.
// - «Сомнительная компания» → «Избегать компанию» — вынесена как отдельная
//   статичная кнопка, но остаётся в каноне для совместимости. Legacy-строки
//   «Сомнительная компания» и «Риск выгорания» матчатся в новый канон.

export const SELF_REJECT_REASONS = [
  "Низкий грейд",
  "Низкая зарплата",
  "Не тот стек/домен",
  "Не тот формат",
  "Не та роль (IC vs рук)",
  "Избегать компанию",
] as const
export type SelfRejectReason = (typeof SELF_REJECT_REASONS)[number]

/** Статичная кнопка «Избегать компанию» — отдельная от LLM-чипов пропуска. */
export const DODGY_COMPANY_REASON = "Избегать компанию" as const

export const HR_REJECT_REASONS = [
  "Не те условия",
  "Не прошёл скрининг",
  "Не прошёл техничку",
  "Не подошёл оффер",
  "Вакансия закрылась",
  "Другое",
] as const
export type HrRejectReason = (typeof HR_REJECT_REASONS)[number]

const CANONICAL = new Set<string>(SELF_REJECT_REASONS)

const LEGACY_EXACT: Record<string, SelfRejectReason> = {
  "Зарплата ниже целевой": "Низкая зарплата",
  "Низкая зарплата": "Низкая зарплата",
  "Грейд ниже Senior+": "Низкий грейд",
  "Грейд не совпадает": "Низкий грейд",
  "Не полная удалёнка": "Не тот формат",
  "Офис / нет удалёнки": "Не тот формат",
  // Старое название причины пропуска (до переименования 2026-08-10).
  "Риск выгорания": "Не та роль (IC vs рук)",
  // Старое название причины пропуска (до переименования 2026-08-10).
  "Сомнительная компания": "Избегать компанию",
  Другое: "Избегать компанию",
  "Не интересно": "Избегать компанию",
  "без причины": "Избегать компанию",
  "Не тот стек": "Не тот стек/домен",
  "Не тот домен": "Не тот стек/домен",
  "Стек/домен далёкий": "Не тот стек/домен",
  "Не тот стек / домен": "Не тот стек/домен",
}

function norm(raw: string): string {
  return raw.toLowerCase().replace(/ё/g, "е").trim()
}

/** Свести произвольную причину пропуска к канону (legacy-строки из БД до миграции). */
export function canonicalSelfReason(raw?: string | null): SelfRejectReason {
  const stripped = (raw ?? "").trim()
  if (!stripped) return "Избегать компанию"
  if (CANONICAL.has(stripped)) return stripped as SelfRejectReason

  if (stripped in LEGACY_EXACT) {
    return LEGACY_EXACT[stripped]!
  }

  const s = norm(stripped)
  if (/recommendation=skip|^skip$/.test(s)) return "Избегать компанию"
  if (/зарплат|вилк|деньг|оплат|ниже\s*цел|мало\s*плат|low\s*salar/.test(s))
    return "Низкая зарплата"
  if (
    /выгор|burnout|переработ|нагрузк|токсич|управлен|менеджер|руковод|people\s*manager|\bic\b|individual\s*contributor|хендс-?он|hands-?on|доля\s*управлен|роль\s*менеджер|руководящ/.test(
      s,
    )
  ) {
    return "Не та роль (IC vs рук)"
  }
  if (/удален|офис|гибрид|формат|на\s*месте|on-?site|remote|релок/.test(s)) return "Не тот формат"
  if (/грейд|grade|junior|middle|уровень|позиц|не\s*тот\s*грейд/.test(s)) return "Низкий грейд"
  if (
    /стек|stack|домен|domain|технолог|rag|agent|llm|nlp|\bbi\b|\bcv\b|классическ.*ml|data engineer(?!.*llm)|аналитик|wrong_domain|generic_backend/.test(
      s,
    )
  ) {
    return "Не тот стек/домен"
  }
  if (/не\s*интерес|аутстафф|аутсорс|сомнительн|избегать|ненадеж|ненадёж/.test(s))
    return "Избегать компанию"

  return "Избегать компанию"
}
