/**
 * Данные под блок «Деньги» (редизайн 2026-08-09, правка 2026-08-09): распределение зарплат
 * (гистограмма SVG, `SalaryDistribution`) и форматы работы (гистограмма по категориям,
 * `CategoryBars`). Бывшие «полосы из кусков» (SegmentedBar) для форматов выпилены —
 * кривой тип визуализации, подписи сегментов наезжали друг на друга.
 *
 * Убраны: Бенчмарк по грейдам (RangeBars), ai slop подписи («моя цель», «середина»,
 * «здесь 430: выше 62%», «как рынок реагирует», «спрос по неделям»), DataList-двойник, Mosaic,
 * «Конъюнктура рынка» (2026-08-08 — вместо неё позже более умную визуализацию).
 *
 * Чистая подготовка — без БД и без React, тестируется отдельно от `MarketPage.tsx`.
 */
import type { LiveOfferPoint, MarketBucket, MarketSupplyFacts } from "@/api/market"
import type { CategoryBar } from "./charts/category-bars-geometry"
import type { SalaryDistributionInput } from "./charts/salary-distribution-geometry"

/** `374 000 ₽` — полная форма для тултипов и подписей, где место позволяет. */
export function formatMoney(value: number): string {
  return `${Math.round(value)
    .toLocaleString("ru-RU")
    .replace(/\u00A0/g, " ")} ₽`
}

/** `540к` — компактная форма для подписей на графике. */
export function formatMoneyShort(value: number): string {
  return `${Math.round(value / 1000)}к`
}

/**
 * Сборка входа для `SalaryDistribution` из `MarketSupplyFacts` + живых офферов.
 * Квартили (p25/p75) и min/max теперь пробрасываются в график (раньше не показывались).
 */
export function salaryDistributionInput(
  supply: MarketSupplyFacts,
  liveOffers: readonly LiveOfferPoint[],
): SalaryDistributionInput {
  return {
    points: supply.available ? (supply.salary_points ?? []) : [],
    targetMin: supply.target_min_net,
    targetMax: supply.target_max_net,
    median: supply.salary_median_net,
    p25: supply.salary_p25_net,
    p75: supply.salary_p75_net,
    offers: liveOffers.map((o, i) => ({
      key: `offer-${i}`,
      company: o.company,
      value: o.monthly_net,
    })),
  }
}

/**
 * Категории для `CategoryBars` — распределение форматов работы (remote/hybrid/office).
 * Подписи — короткие термины («Удалённо», «Гибрид», «Офис»), не «удалённо · 67%» —
 * доля видна в тултипе и на оси, без наезжающих подписей.
 *
 * Правка 2026-08-14: графики Формат/Грейд/Роль переведены с количества вакансий на доли (%).
 * Бэк уже отдаёт `pct` (0..100) в `MarketBucket` — пробрасываем его в `CategoryBar.pct`,
 * а на фронте включаем `showPercent: true`, чтобы шкала и подпись над столбцом были в %.
 */
export function workFormatBars(formats: readonly MarketBucket[] | null | undefined): CategoryBar[] {
  if (!formats || formats.length === 0) return []
  const KEY_MAP: Record<string, string> = {
    remote: "Удалённо",
    удалённо: "Удалённо",
    "удаленная работа": "Удалённо",
    hybrid: "Гибрид",
    гибрид: "Гибрид",
    office: "Офис",
    офис: "Офис",
  }
  return formats.map((f) => ({
    key: f.label,
    label: KEY_MAP[f.label?.toLowerCase() ?? ""] ?? cap(f.label),
    value: f.count,
    pct: f.pct,
  }))
}

function cap(s: string): string {
  if (!s) return s
  return s.charAt(0).toUpperCase() + s.slice(1)
}

/** Сколько строк «Роль» показывать в мини-графике совмещённой визуализации (2026-08-11) —
 * бэк отдаёт до 8 (`_TOP_NICHES`), но в узкой трети карточки читаемы только первые. */
const MAX_ROLE_BARS = 5

/** Абсолютный грейд вакансии на канонической лестнице (`GRADE_SCALE`: Junior / Middle /
 * Senior / Lead / C-level). Подписи уже на бэке — пробрасываем `pct` для процентной шкалы. */
export function gradeLevelBars(levels: readonly MarketBucket[] | undefined): CategoryBar[] {
  if (!levels || levels.length === 0) return []
  return levels.map((l) => ({ key: l.label, label: l.label, value: l.count, pct: l.pct }))
}

/** Топ-ниш стека/роли (`role_content_match.matched_niche`) — усечено под ширину мини-колонки.
 * Пробрасываем бэковый `pct` для процентной шкалы (правка 2026-08-14). */
export function roleNicheBars(niches: readonly MarketBucket[] | undefined): CategoryBar[] {
  if (!niches || niches.length === 0) return []
  return niches
    .slice(0, MAX_ROLE_BARS)
    .map((n) => ({ key: n.label, label: n.label, value: n.count, pct: n.pct }))
}
