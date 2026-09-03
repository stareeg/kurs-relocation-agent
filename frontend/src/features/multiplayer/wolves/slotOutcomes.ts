/** Итог закрытого слота — копится на клиенте при переходе slot_index / reveal. */
export type SlotOutcomeTone = "offer" | "reject" | "interview" | "mixed" | "quiet"

export type SlotOutcome = {
  offers: number
  rejects: number
  interviews: number
  probes: number
  headline?: string | null
  tone: SlotOutcomeTone
}

export type SlotOutcomeMap = Record<number, SlotOutcome>

/** Сводка по штампам слота (данные ещё в stamps_this_slot до open следующего слота). */
export function deriveSlotOutcome(
  stamps: Record<string, string> | undefined,
  headline?: string | null,
): SlotOutcome {
  const values = Object.values(stamps ?? {})
  const offers = values.filter((v) => v === "offer").length
  const rejects = values.filter((v) => v === "reject").length
  const interviews = values.filter((v) => v === "interview").length
  const probes = values.filter((v) => v === "probe").length

  let tone: SlotOutcomeTone = "quiet"
  if (offers > 0) tone = "offer"
  else if (rejects > 0 && (interviews > 0 || probes > 0)) tone = "mixed"
  else if (rejects > 0) tone = "reject"
  else if (interviews > 0 || probes > 0) tone = "interview"

  return { offers, rejects, interviews, probes, headline: headline ?? null, tone }
}

export function slotOutcomeTitle(o: SlotOutcome): string {
  const parts: string[] = []
  if (o.offers) parts.push(`${o.offers} оффер`)
  if (o.rejects) parts.push(`${o.rejects} отказ`)
  if (o.interviews) parts.push(`${o.interviews} собес`)
  if (o.probes) parts.push(`${o.probes} проверка`)
  const summary = parts.length ? parts.join(", ") : "без штампов"
  return o.headline ? `${summary} · ${o.headline}` : summary
}

export function slotOutcomeGlyph(tone: SlotOutcomeTone): string {
  switch (tone) {
    case "offer":
      return "★"
    case "reject":
      return "✕"
    case "interview":
      return "✓"
    case "mixed":
      return "±"
    default:
      return "·"
  }
}
