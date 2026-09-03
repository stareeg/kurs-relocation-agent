export const BONUS_KINDS = ["annual", "quarterly", "kpi", "welcome", "equity"] as const
export type BonusKind = (typeof BONUS_KINDS)[number]

/** Exponential % of the reporting period (year / quarter) — same ticks as the slider. */
export const BONUS_PCT_STEPS = [5, 10, 15, 20, 25, 30, 40, 50, 75, 100, 150] as const
export type BonusPct = (typeof BONUS_PCT_STEPS)[number]

export const BONUS_PCT_DEFAULT: BonusPct = 10

export function snapBonusPct(value: number | null | undefined): BonusPct | null {
  if (value == null || value <= 0) return null
  return BONUS_PCT_STEPS.reduce((best, step) =>
    Math.abs(step - value) < Math.abs(best - value) ? step : best,
  )
}

export function bonusPctIndex(value: number | null | undefined): number {
  const snapped = snapBonusPct(value) ?? BONUS_PCT_DEFAULT
  return Math.max(0, BONUS_PCT_STEPS.indexOf(snapped))
}

export function offerBonusTypes(offer: {
  bonus_types?: string[] | null
  bonus_type?: string | null
}): BonusKind[] {
  const raw = offer.bonus_types
  if (raw && raw.length > 0) {
    return BONUS_KINDS.filter((k) => raw.includes(k))
  }
  const singular = offer.bonus_type
  if (singular && singular !== "none" && (BONUS_KINDS as readonly string[]).includes(singular)) {
    return [singular as BonusKind]
  }
  return []
}

export function hasBonusKind(
  offer: { bonus_types?: string[] | null; bonus_type?: string | null },
  kind: BonusKind,
): boolean {
  return offerBonusTypes(offer).includes(kind)
}
