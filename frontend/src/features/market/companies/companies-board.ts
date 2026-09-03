/**
 * Редьюсер перемещений компаний (K-01).
 * Компания не может быть сразу в «Целевых» и «Избегать»; возврат в «Кандидаты»
 * снимает разметку из обоих списков. Лимиты — как в rules.py.
 */

export const MAX_TARGET = 20
// «Избегать» без лимита: компания должна попадать туда по skip без потолка,
// иначе реальный сигнал теряется на десятой записи.
export const MAX_AVOID = Number.POSITIVE_INFINITY

/**
 * Видимый эффект правила (K-03): дублирует core/domains/opportunities/rules.py
 * (TARGET_COMPANY_DELTA — тай-брейкер к оценке вакансий целевой компании).
 * В OpenAPI не отдаётся — правило не имеет транспортного контракта, дублируется
 * тут одним местом.
 */
export const TARGET_COMPANY_DELTA = 5

export type CompanyZone = "target" | "avoid" | "candidates"

export type CompanyBoardState = {
  target: string[]
  avoid: string[]
}

/** Значение для PATCH search_criteria. */
export type CompanyListsValue = {
  target_companies: string[]
  avoid_companies: string[]
}

export function toListsValue(state: CompanyBoardState): CompanyListsValue {
  return {
    target_companies: state.target,
    avoid_companies: state.avoid,
  }
}

export function fromListsValue(value: CompanyListsValue): CompanyBoardState {
  return {
    target: value.target_companies,
    avoid: value.avoid_companies,
  }
}

export function zoneOf(state: CompanyBoardState, company: string): CompanyZone {
  if (state.target.includes(company)) return "target"
  if (state.avoid.includes(company)) return "avoid"
  return "candidates"
}

/** Зона принимает дроп (лимит ещё не выбран). «Кандидаты» всегда принимают. */
export function canAccept(state: CompanyBoardState, zone: CompanyZone): boolean {
  if (zone === "candidates") return true
  if (zone === "target") return state.target.length < MAX_TARGET
  return state.avoid.length < MAX_AVOID
}

/**
 * Переместить компанию в зону. `null` — без изменений (та же зона, пустое имя, лимит).
 * При переезде target↔avoid компания сначала снимается со старого списка.
 */
export function moveCompany(
  state: CompanyBoardState,
  company: string,
  to: CompanyZone,
): CompanyBoardState | null {
  const name = company.trim()
  if (!name) return null

  const from = zoneOf(state, name)
  if (from === to) return null

  if (to === "target") {
    if (state.target.length >= MAX_TARGET) return null
    return {
      target: [...state.target.filter((c) => c !== name), name],
      avoid: state.avoid.filter((c) => c !== name),
    }
  }

  if (to === "avoid") {
    if (state.avoid.length >= MAX_AVOID) return null
    return {
      target: state.target.filter((c) => c !== name),
      avoid: [...state.avoid.filter((c) => c !== name), name],
    }
  }

  // candidates: снять разметку
  if (from === "candidates") return null
  return {
    target: state.target.filter((c) => c !== name),
    avoid: state.avoid.filter((c) => c !== name),
  }
}

/** Ручное добавление в целевые / избегать (как AddOwnInput). */
export function addCompany(
  state: CompanyBoardState,
  company: string,
  to: "target" | "avoid",
): CompanyBoardState | null {
  return moveCompany(state, company, to)
}

/** Кандидаты реестра минус уже размеченные (для колонки «Кандидаты»). */
export function filterCandidates<T extends { company: string }>(
  items: readonly T[],
  state: CompanyBoardState,
): T[] {
  const marked = new Set([...state.target, ...state.avoid])
  return items.filter((item) => item.company.trim() && !marked.has(item.company))
}

/** Поиск по имени над колонкой «Кандидаты» (K-04): регистронезависимая подстрока. */
export function matchesCompanyQuery(company: string, query: string): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return true
  return company.toLowerCase().includes(q)
}

/** Компактная дата последнего появления в потоке для карточки кандидата (K-04): «12.07», без
 * года — last_seen_at на этом чипе всегда в пределах последних месяцев. */
export function formatLastSeen(iso: string | null | undefined): string | null {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  const day = String(d.getDate()).padStart(2, "0")
  const month = String(d.getMonth() + 1).padStart(2, "0")
  return `${day}.${month}`
}
