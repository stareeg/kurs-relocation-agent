// Карточки фактов «Зарплата · Формат · Грейд» — общая логика панели расширения и дровера (U-05).
// Чистые функции без React/DOM; веб сводит FormatChipTone к StatusTone на своей стороне.

import {
  GRADE_LABEL,
  GRADE_TONE,
  MANAGEMENT_LABEL,
  REMOTE_ABROAD_LABEL,
  gradeLevelKey,
} from "./criteria"

export type FormatChipTone = "strong" | "good" | "warn" | "bad" | "info"

/** Формат работы (hh work_format) → короткий ярлык, как workFormatChip в funnel.ts. */
export function workFormatChip(
  workFormat?: string | null,
  currencyRemote?: boolean,
): { label: string; tone: FormatChipTone } | null {
  if (currencyRemote) return { label: "Валютка", tone: "info" }
  const low = (workFormat ?? "").toLowerCase().replace(/ё/g, "е").trim()
  if (!low) return null
  if (/удален|remote|дистанц/.test(low)) return { label: "Удалёнка", tone: "strong" }
  if (/гибрид|hybrid/.test(low)) return { label: "Гибрид", tone: "warn" }
  if (/релокац|relocat|переезд/.test(low)) return { label: "Релокация", tone: "good" }
  if (/офис|на месте|office|on-?site|разъезд/.test(low)) return { label: "Офис", tone: "bad" }
  return null
}

export type RemoteVerdict = "real" | "conditional" | "unlikely"

export const REMOTE_VERDICT_ORDER: readonly RemoteVerdict[] = ["real", "conditional", "unlikely"]

export const REMOTE_FEASIBILITY: Record<
  RemoteVerdict,
  { label: string; short: string; tone: FormatChipTone }
> = {
  real: { label: "Удалёнка реальна", short: "Реальна", tone: "strong" },
  conditional: { label: "Удалёнка условно", short: "Скорее Гибрид", tone: "warn" },
  unlikely: { label: "Удалёнка вряд ли", short: "Скорее Офис", tone: "bad" },
}

export type RemoteFeasibilityView = {
  score?: number
  verdict?: RemoteVerdict
  signals?: { text: string; polarity: "pro" | "contra" }[]
  note?: string
}

export function remoteFeasibilityOf(
  record: { remote_feasibility?: unknown },
): RemoteFeasibilityView | undefined {
  const rf = record.remote_feasibility
  if (!rf || typeof rf !== "object") return undefined
  const view = rf as RemoteFeasibilityView
  return REMOTE_VERDICT_ORDER.includes(view.verdict as RemoteVerdict) ? view : undefined
}

/** Конфликт заявленного формата и remote_feasibility — как formatConflictOf в funnel.ts. */
export function formatConflictOf(
  formatChip: { label: string; tone: FormatChipTone } | null | undefined,
  remote: RemoteFeasibilityView | undefined,
): { tone: FormatChipTone; caption: string } | null {
  if (!formatChip || (formatChip.tone !== "strong" && formatChip.tone !== "good")) return null
  if (!remote?.verdict || remote.verdict === "real") return null
  // «Скорее Офис/Гибрид» вместо обрывочного «Вряд ли» — понятно, какой формат вероятнее.
  return {
    tone: REMOTE_FEASIBILITY[remote.verdict].tone,
    caption: REMOTE_FEASIBILITY[remote.verdict].short,
  }
}

const SALARY_UNSPECIFIED = /не\s*указ|не\s*обознач|договор|по\s*резул|обсужд|з\/п\s*не/i

function salarySpecified(text?: string | null): boolean {
  const t = (text ?? "").trim()
  if (!t || t.toLowerCase() === "не указана") return false
  if (SALARY_UNSPECIFIED.test(t)) return false
  return /\d/.test(t)
}

/** Срезаем канцелярит hh, «/мес», суффикс «(… оценка)»; nbsp → пробел. */
export function cleanSalaryText(text: string): string {
  return text
    .replace(/\s*\([^)]*оценка[^)]*\)\s*/i, " ")
    .replace(/[,;]?\s*(за|в)\s+месяц/gi, "")
    .replace(/\s*₽?\s*\/\s*мес\w*/gi, "")
    .replace(/[,;]?\s*(до|после)\s+вычета\s+налог\w*/gi, "")
    .replace(/\u00A0/g, " ")
    .replace(/\s{2,}/g, " ")
    .replace(/[,\s]+$/g, "")
    .trim()
}

export type ResolvedSalaryCard = {
  text: string
  isEstimate: boolean
  meetsMin: boolean | null
  estimateSuffix: string | null
  source: string
}

function asConfidence(raw: unknown): "high" | "medium" | "low" {
  if (raw === "high" || raw === "medium" || raw === "low") return raw
  return "low"
}

function estimateSuffixFor(confidence: "high" | "medium" | "low", isEstimate: boolean): string | null {
  if (!isEstimate) return null
  return confidence === "low" ? "грубая оценка" : "оценка"
}

function salaryAmountK(n: number): string {
  if (n >= 1_000_000) {
    const v = n / 1_000_000
    return `${Number.isInteger(v) ? v : v.toFixed(1).replace(/\.0$/, "")}М`
  }
  return `${Math.round(n / 1000)}к`
}

type SalaryView = {
  value_or_range?: string
  estimated_range?: string
  estimated_min?: number | null
  estimated_max?: number | null
  meets_min?: boolean
  estimate_pending?: boolean
  confidence?: string
  source?: string
  note?: string
}

function meetsMinValue(sal: SalaryView | undefined): boolean | null {
  if (sal?.meets_min === true) return true
  if (sal?.meets_min === false) return false
  return null
}

/** Итоговая вилка для карточки «Зарплата» — упрощённый resolveJobSalary под запись расширения. */
export function resolveSalaryForCard(record: {
  salary_text?: string | null
  score?: { salary?: SalaryView }
}): ResolvedSalaryCard {
  const sal = record.score?.salary
  const meetsMin = meetsMinValue(sal)
  const confidence = asConfidence(sal?.confidence)
  const rawSource = sal?.source || "none"

  if (salarySpecified(record.salary_text)) {
    return {
      text: cleanSalaryText(record.salary_text as string),
      isEstimate: false,
      meetsMin,
      estimateSuffix: null,
      source: "explicit",
    }
  }

  if (rawSource === "explicit") {
    const val = sal?.value_or_range || ""
    if (salarySpecified(val)) {
      return {
        text: cleanSalaryText(val),
        isEstimate: false,
        meetsMin,
        estimateSuffix: null,
        source: "explicit",
      }
    }
  }

  const estimateSources = new Set(["corpus", "anchor", "llm"])
  if (estimateSources.has(rawSource)) {
    const est = sal?.estimated_range || sal?.value_or_range || ""
    if (salarySpecified(est)) {
      return {
        text: cleanSalaryText(est),
        isEstimate: true,
        meetsMin,
        estimateSuffix: estimateSuffixFor(confidence, true),
        source: rawSource,
      }
    }
  }

  if (rawSource === "none" || !sal?.source) {
    if (sal?.estimate_pending) {
      return {
        text: "оценка…",
        isEstimate: true,
        meetsMin: null,
        estimateSuffix: null,
        source: "none",
      }
    }
    const legacyEst = sal?.estimated_range
    if (salarySpecified(legacyEst)) {
      return {
        text: cleanSalaryText(legacyEst as string),
        isEstimate: true,
        meetsMin,
        estimateSuffix: estimateSuffixFor(confidence, true),
        source: "llm",
      }
    }
    if (sal?.estimated_min != null && sal?.estimated_max != null && sal.estimated_min > 0) {
      const lo = salaryAmountK(sal.estimated_min)
      const hi = salaryAmountK(sal.estimated_max)
      const text = lo === hi ? lo : `${lo}–${hi}`
      return {
        text,
        isEstimate: true,
        meetsMin,
        estimateSuffix: estimateSuffixFor(confidence, true),
        source: "llm",
      }
    }
  }

  const fromLlm = salarySpecified(sal?.value_or_range) ? sal?.value_or_range : null
  const estimated = salarySpecified(sal?.estimated_range) ? sal?.estimated_range : null
  if (fromLlm) {
    return {
      text: cleanSalaryText(fromLlm),
      isEstimate: false,
      meetsMin,
      estimateSuffix: null,
      source: rawSource,
    }
  }
  if (estimated) {
    return {
      text: cleanSalaryText(estimated),
      isEstimate: true,
      meetsMin,
      estimateSuffix: estimateSuffixFor(confidence, true),
      source: rawSource,
    }
  }

  if (sal?.estimate_pending) {
    return {
      text: "оценка…",
      isEstimate: true,
      meetsMin: null,
      estimateSuffix: null,
      source: "none",
    }
  }

  return {
    text: "—",
    isEstimate: false,
    meetsMin: null,
    estimateSuffix: null,
    source: "none",
  }
}

/** Краткая форма суммы для карточки (как abbrevSalary в funnel.ts). */
export function abbrevSalary(text: string): string {
  if (!text || text === "—") return text
  return text.replace(/\d[\d\s]*\d|\d+/g, (m) => {
    const n = parseInt(m.replace(/[\s]/g, ""), 10)
    if (!Number.isFinite(n) || n < 1000) return m
    if (n >= 1_000_000) {
      const v = n / 1_000_000
      return `${Number.isInteger(v) ? v : v.toFixed(1).replace(/\.0$/, "")}М`
    }
    return `${Math.round(n / 1000)}к`
  })
}

/** Вилка «от 350к до 400к» без ₽/мес — период и так очевиден на карточке. */
export function polishSalaryDisplay(text: string): string {
  let t = text
    .replace(/\s*₽(?:\s*\/\s*мес\w*)?/gi, "")
    .replace(/\s*\/\s*мес\w*/gi, "")
    .replace(/\s*руб\.?/gi, "")
    .replace(/\s{2,}/g, " ")
    .trim()
  // «350к — 400к» / «350к-400к» → «от 350к до 400к»
  const bare = t.match(
    /^(\d+(?:[.,]\d+)?(?:к|К|М|м)?)\s*[–—−-]+\s*(\d+(?:[.,]\d+)?(?:к|К|М|м)?)$/i,
  )
  if (bare) return `от ${bare[1]} до ${bare[2]}`
  // уже «от … до …» — нормализуем тире между суммами, если остались
  t = t.replace(/\bот\s+/i, "от ").replace(/\s+до\s+/i, " до ")
  return t
}

export function formatSalaryCardText(salary: ResolvedSalaryCard): string {
  if (salary.text === "—" || salary.text === "оценка…") return salary.text
  const base = polishSalaryDisplay(abbrevSalary(salary.text))
  return salary.estimateSuffix ? `${base} · ${salary.estimateSuffix}` : base
}

/** Подпись карточки «Зарплата» — вердикт по порогу или провенанс (как FactCards дровера). */
export function salaryCardCaption(
  salary: ResolvedSalaryCard,
  provenance?: string | null,
): string {
  if (salary.meetsMin === true) return "выше цели"
  if (salary.meetsMin === false) return "ниже цели"
  if (salary.isEstimate) return "оценка"
  return provenance ?? "—"
}

export function salaryCardValueTone(salary: ResolvedSalaryCard): "muted" | "good" | "neutral" {
  // Бледный «muted» только пока вилки ещё нет; оценка с цифрами читается как обычное значение.
  if (salary.text === "оценка…") return "muted"
  if (salary.meetsMin === true) return "good"
  return "neutral"
}

/** Укороченный провенанс вилки без help-texts (расширение). */
export function salaryProvenanceShort(source: string, note?: string): string | null {
  if (source === "offer" || source === "none") return null
  const lower = (note || "").toLowerCase()
  if (source === "explicit") {
    if (lower.includes("hr") || lower.includes("рекрутер")) return "со слов HR"
    if (lower.includes("карточки") || lower.includes("страницы")) return "со страницы"
    return "из вакансии"
  }
  if (source === "corpus") {
    const n = (note || "").match(/по\s+(\d+)\s+наблюден/i)?.[1]
    return n ? `по ${n} похожим вакансиям` : "по похожим вакансиям"
  }
  if (source === "anchor") return "по резюме"
  if (source === "llm") return "оценка модели"
  return null
}

export function levelLabel(
  map: Record<string, string>,
  level: string | null | undefined,
): { label: string; rawTitle?: string } {
  if (!level) return { label: "—" }
  const known = map[level]
  return known ? { label: known } : { label: "—", rawTitle: level }
}

/** Junior/Middle/Senior из reasoning скорера — понятнее Hands-on/Смешанный. */
export function extractGradeName(reasoning?: string | null): string | null {
  const text = (reasoning ?? "").trim()
  if (!text) return null
  const en = text.match(/\b(Intern|Junior|Middle|Senior|Lead|Staff|Principal|Head)\b/i)
  if (en) {
    const raw = en[1]
    return raw.charAt(0).toUpperCase() + raw.slice(1).toLowerCase()
  }
  const ru = text.match(/\b(джун(?:иор)?|мидд?л|сень?ор|синьор|лид)\b/i)
  if (!ru) return null
  const map: Record<string, string> = {
    джун: "Junior",
    джуниор: "Junior",
    мидл: "Middle",
    миддл: "Middle",
    сеньор: "Senior",
    сенор: "Senior",
    синьор: "Senior",
    лид: "Lead",
  }
  return map[ru[1].toLowerCase()] ?? null
}

export function gradeFactCard(s: {
  grade_match?: { level?: string; reasoning?: string; off_profile_kind?: string | null }
  burnout_risk?: { level?: string }
}) {
  const gradeKey = gradeLevelKey(s.grade_match)
  const grade = levelLabel(GRADE_LABEL, gradeKey)
  const fromReasoning = extractGradeName(s.grade_match?.reasoning)
  const mgmtLevel = s.burnout_risk?.level
  // medium без отдельной подписи «смешанный» — только грейд или руки/люди.
  const management =
    mgmtLevel === "medium" && !fromReasoning
      ? { label: "—" }
      : levelLabel(MANAGEMENT_LABEL, mgmtLevel)
  const tone = gradeKey ? GRADE_TONE[gradeKey] ?? "neutral" : "neutral"
  // Крупная строка карточки — конкретный грейд (Middle/Senior/…), вторая строка — относительная
  // оценка к цели резюме (Совпадает/Чуть ниже/…). Раньше было наоборот — жирным шла именно
  // относительная оценка, а конкретный грейд прятался мелким текстом (Решение 3, редизайн).
  // Если извлечь грейд из reasoning не удалось — значение не пустеет (используем относительную
  // оценку), а подпись остаётся management.label, как и было для этого случая раньше.
  return {
    value: fromReasoning ?? grade.label,
    caption: fromReasoning ? grade.label : management.label,
    tone,
    title: grade.rawTitle ?? s.grade_match?.reasoning,
  }
}

export function formatFactCardTone(formatTone: FormatChipTone | undefined): string {
  const map: Record<FormatChipTone, string> = {
    strong: "good",
    good: "good",
    warn: "mid",
    bad: "bad",
    info: "info",
  }
  return formatTone ? map[formatTone] ?? "" : ""
}

export function formatFactCard(
  record: {
    work_format?: string | null
    remote_feasibility?: unknown
  },
  s: {
    currency_remote?: boolean
    remote_abroad_compat?: { level?: string }
  },
) {
  const formatChip = workFormatChip(record.work_format, s.currency_remote)
  const remote = remoteFeasibilityOf(record)
  const remoteChip = remote?.verdict ? REMOTE_FEASIBILITY[remote.verdict] : undefined
  const conflict = formatConflictOf(formatChip, remote)
  const abroadLevel = s.remote_abroad_compat?.level
  const abroadLabel = abroadLevel ? REMOTE_ABROAD_LABEL[abroadLevel] : undefined

  const note = remote?.note?.trim()
  const shortNote =
    note && note.length <= 42 ? note : remoteChip ? remoteChip.short : undefined
  const caption =
    conflict?.caption ?? shortNote ?? abroadLabel ?? (remoteChip ? remoteChip.short : "—")
  const contra = remote?.signals?.find((sig) => sig.polarity === "contra")
  return {
    value: formatChip?.label ?? "—",
    caption,
    tone: conflict
      ? formatFactCardTone(conflict.tone)
      : formatChip
        ? formatFactCardTone(formatChip.tone)
        : "",
    title: conflict
      ? contra?.text
        ? `В тексте: ${contra.text}`
        : "Заявлен формат, но по тексту вакансии это под вопросом"
      : note && note.length > 42
        ? note
        : undefined,
  }
}
