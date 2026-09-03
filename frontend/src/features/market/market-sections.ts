/**
 * Якоря секций «Рынка» (редизайн 2026-08-09): двухколоночный лейаут читается тремя рядами —
 * Где стою / Поток / Реакция рынка. Бывший «Что сделать» (next-steps) удалён, заменён чатом.
 * `MARKET_SECTIONS` сохранён как источник id для `MarketEmpty` fallback-формулировок,
 * но лейаутом теперь рулит `MarketPage.tsx` напрямую.
 */
export const MARKET_SECTIONS = [
  { id: "gde-stoyu", label: "Зарплаты" },
  { id: "otklik-rynka", label: "Площадки" },
  { id: "voronka", label: "Воронка" },
  { id: "chto-rezhet-potok", label: "Причины в пропуске" },
  { id: "formats", label: "Условия" },
  { id: "shans-offera", label: "Шанс офферов" },
  { id: "stavki-valyuta", label: "Ставки" },
] as const

export type MarketSectionId = (typeof MARKET_SECTIONS)[number]["id"]

/** Секции с виджетом; все карточки рисуют честный empty через `MarketEmpty` + `resolveEmptyReason`. */
export const SECTIONS_WITH_CONTENT = new Set<MarketSectionId>([
  "gde-stoyu",
  "otklik-rynka",
  "chto-rezhet-potok",
  "voronka",
  "formats",
  "shans-offera",
  "stavki-valyuta",
])
