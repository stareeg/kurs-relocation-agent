/**
 * Подписи блока «Условия работы» в дровере (Э3.2). Чистые функции — без React.
 * Словарь регионов зеркалит `_GEO_TOKEN_TO_REGION` в score_breakdown.py, чтобы подпись
 * «EMEA 7 ч из требуемых 4» совпадала с тем, что считает ось compat.
 */

const GEO_TOKEN_TO_REGION: Record<string, string> = {
  emea: "EMEA",
  eu: "EMEA",
  europe: "EMEA",
  uk: "UK",
  gb: "UK",
  "us-east": "US-East",
  "us-west": "US-West",
  pst: "US-West",
  pt: "US-West",
  pacific: "US-West",
  et: "US-East",
  est: "US-East",
  eastern: "US-East",
  us: "US-East",
  usa: "US-East",
  apac: "APAC",
  asia: "APAC",
}

export function regionFromHiringGeo(hiringGeo: string[] | undefined): string | null {
  for (const raw of hiringGeo ?? []) {
    const token = (raw || "").trim().toLowerCase().replace(/_/g, "-")
    if (["worldwide", "world", "anywhere", "remote"].includes(token)) continue
    const mapped = GEO_TOKEN_TO_REGION[token]
    if (mapped) return mapped
    for (const [key, region] of Object.entries(GEO_TOKEN_TO_REGION)) {
      if (token.includes(key)) return region
    }
  }
  return null
}

export function regionFromTimezone(tz: string | undefined): string | null {
  const token = (tz || "").trim().toLowerCase().replace(/_/g, "-")
  if (!token) return null
  const mapped = GEO_TOKEN_TO_REGION[token]
  if (mapped) return mapped
  for (const [key, region] of Object.entries(GEO_TOKEN_TO_REGION)) {
    if (token.includes(key)) return region
  }
  return null
}

/** «EMEA 7 ч из требуемых 4» — числом, не светофором. Пусто, если считать нечего. */
export function overlapCaption(
  terms: {
    hiring_geo?: string[]
    timezone_requirement?: string
    overlap_hours_required?: number | null
  },
  overlap: Record<string, number> | undefined,
): string {
  const required = terms.overlap_hours_required
  const region =
    regionFromHiringGeo(terms.hiring_geo) ?? regionFromTimezone(terms.timezone_requirement)
  const hoursFor = (key: string): number | undefined => {
    const v = overlap?.[key]
    return typeof v === "number" ? v : undefined
  }
  if (region != null) {
    const available = hoursFor(region)
    if (available != null && required != null) return `${region} ${available} ч из требуемых ${required}`
    if (available != null) return `${region} ${available} ч`
  }
  if (required != null && overlap) {
    const best = Object.entries(overlap).sort((a, b) => b[1] - a[1])[0]
    if (best) return `${best[0]} ${best[1]} ч из требуемых ${required}`
    return `требуется ${required} ч`
  }
  return ""
}

export const EXCLUSIVITY_LABEL: Record<string, string> = {
  required: "нельзя совмещать",
  allowed: "совмещение можно",
  not_mentioned: "не указано",
}
