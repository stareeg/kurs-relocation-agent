/** Подсказки в спойлерах «Формулировки» / «Релевантность роли» — коротко, по одной строке. */

import type { ResumeScoreBreakdown } from "@/api/resume"

const SLOP_PREFIX =
  /(?:^|\s)(?:(?:буллет\s+)?(?:слаб(?:ый|ая|ое)|strong|weak)[^:—\-]*[:—\-]\s*|(?:рекоменду(?:ю|ется)|следует|желательно|стоит|нужно)\s+|(?:вердикт|оценка|комментарий)\s*[:—\-]\s*)+/gi

const META_WORDS = /\b(?:слаб(?:ый|ая|ое)|strong|weak|вердикт)\b/gi

const DEFAULT_WRITING_TIP = "добавьте действие, технологии или измеримый результат"

const GENITIVE_TO_NOMINATIVE: Record<string, string> = {
  результата: "результат",
  метрик: "метрики",
  технологий: "технологии",
  "конкретного действия": "конкретное действие",
  масштаба: "масштаб",
}

export function normalizeScoreTip(text: string): string {
  let line = text.replace(/\s+/g, " ").trim()
  if (!line) return ""
  line = line.replace(SLOP_PREFIX, "").trim()
  line = line.replace(META_WORDS, "").replace(/\s{2,}/g, " ").trim()
  line = line.replace(/^[.\-–—\s]+|[.\-–—\s]+$/g, "")
  const noMatch = /^нет\s+(.+)$/i.exec(line)
  if (noMatch) {
    const rest = noMatch[1]!.trim()
    const fixed = GENITIVE_TO_NOMINATIVE[rest.toLowerCase()] ?? rest
    return `добавьте ${fixed}`
  }
  return line
}

export function formatWritingTip(ref: string, text: string, reason?: string | null, quoteMax = 55): string {
  const place = ref.trim()
  let quote = text.trim()
  if (quote.length > quoteMax) quote = `${quote.slice(0, quoteMax - 1).trim()}…`
  let tip = normalizeScoreTip(reason ?? "") || DEFAULT_WRITING_TIP
  if (place) return `${place}: «${quote}» — ${tip}`
  return `«${quote}» — ${tip}`
}

export function formatRoleFitNote(note: string): string {
  let line = normalizeScoreTip(note)
  if (!line) return ""
  if (/^[A-ZА-ЯЁ]/.test(line) && !/^["«]/.test(line)) {
    line = line.charAt(0).toLowerCase() + line.slice(1)
  }
  return line
}

export function writingTipsFromScore(score: ResumeScoreBreakdown, limit = 5): string[] {
  const weak = score.weak_bullets ?? []
  if (weak.length) {
    return weak.slice(0, limit).map((b) => formatWritingTip(b.ref, b.text, b.reason))
  }
  if ((score.writing ?? 0) >= 75) return []
  return ["Добавьте буллеты с действием и измеримым результатом"]
}

export function roleFitTipsFromScore(score: ResumeScoreBreakdown, limit = 4): string[] {
  const notes = (score.role_fit_notes ?? []).map(formatRoleFitNote).filter(Boolean)
  if (notes.length) return notes.slice(0, limit)
  if ((score.role_fit ?? 0) >= 75) return []
  return ["Подтяните должность, навыки и «Обо мне» под целевую роль"]
}
