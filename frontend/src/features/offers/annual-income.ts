import type { OfferRecord } from "@/api/offers"
import { offerBonusTypes } from "./bonus"

const CURRENCY_SYMBOL: Record<string, string> = { RUB: "₽", USD: "$", EUR: "€" }

export type AnnualIncome = {
  /** Итоговый доход за первый год: годовой оклад + годовая премия + welcome-бонус (разово). */
  total: number
  currency: string
  hasSignon: boolean
}

function annualBaseOf(offer: OfferRecord): number {
  const base = offer.base_salary ?? 0
  return offer.base_salary_period === "year" ? base : base * 12
}

// Годовая N% от года и квартальная N% от квартала в годовом выражении совпадают:
// (оклад за период × N / 100) × число периодов в году = годовой оклад × N / 100.
function annualBonusFromPct(offer: OfferRecord, annualBase: number): number {
  const types = offerBonusTypes(offer)
  let extra = 0
  if (types.includes("annual") && offer.annual_bonus_pct) {
    extra += Math.round((annualBase * offer.annual_bonus_pct) / 100)
  }
  if (types.includes("quarterly") && offer.quarterly_bonus_pct) {
    extra += Math.round((annualBase * offer.quarterly_bonus_pct) / 100)
  }
  return extra
}

// «ЗП в год» в шапке карточки — арифметика над полями оффера, без LLM.
// Годовая/квартальная считаются из процента слайдера (источник истины), а не из
// bonus_monthly_equiv: тот пересчитывается фоном и в кэше часто ещё старый, либо
// в нём лежит весь пакет вместо добавки — тогда «оклад + equiv×12» ломает сумму,
// а если equiv принимают за итог, годовой доход падает до одной премии.
export function computeAnnualIncome(offer: OfferRecord): AnnualIncome | null {
  if (offer.base_salary == null || offer.base_salary <= 0) return null
  const annualBase = annualBaseOf(offer)
  const types = offerBonusTypes(offer)
  const fromPct = annualBonusFromPct(offer, annualBase)
  const fromEquiv = (offer.bonus_monthly_equiv ?? 0) * 12
  // KPI (и легаси-сумма без %) — только помесячный эквивалент с бэка.
  // Если процент уже известен и KPI нет, equiv не подмешиваем: иначе двойной счёт
  // или подмена оклада старой оценкой.
  const annualBonus =
    fromPct > 0 && !types.includes("kpi") ? fromPct : fromEquiv > 0 ? fromEquiv : fromPct
  const signon = offer.signon ?? 0
  return {
    total: Math.round(annualBase + annualBonus + signon),
    currency: CURRENCY_SYMBOL[offer.base_salary_currency] ?? offer.base_salary_currency,
    hasSignon: signon > 0,
  }
}
