import type { Job } from "@/api/jobs"
import { _hhSourcesSet } from "./source-registry"

/** UI-группа источника вакансии (GM-6): одна доска, три иконки. */
export type SourceGroup = "hh" | "getmatch" | "habr" | "telegram"

export const SOURCE_GROUPS: SourceGroup[] = ["hh", "getmatch", "habr", "telegram"]

// 7.4 / D2 / D3: перечень HH_SOURCES больше не хардкодится — читается из реестра
// `source-registry.ts`, который инициализируется дефолтом, а после старта приложения
// обновляется из `GET /api/meta/sources` (канон `ALL_JOB_SOURCES` с бэка). При добавлении
// нового источника на бэке достаточно регенерации `schema.d.ts` — фронт подхватит.

export const SOURCE_GROUP_LABEL: Record<SourceGroup, string> = {
  hh: "HeadHunter",
  getmatch: "getmatch",
  habr: "Хабр Карьера",
  telegram: "Telegram",
}

/** Канон `jobs.source` → UI-группа. Фолбэк по vacancy_id, если source пуст/неизвестен. */
export function resolveSourceGroup(source?: string | null, vacancyId?: string | null): SourceGroup {
  const s = (source ?? "").trim()
  if (s === "getmatch") return "getmatch"
  if (s === "habr") return "habr"
  if (s === "telegram_channel") return "telegram"
  if (_hhSourcesSet().has(s)) return "hh"
  const vid = (vacancyId ?? "").trim()
  if (vid.startsWith("gm_")) return "getmatch"
  if (vid.startsWith("habr_")) return "habr"
  if (vid.startsWith("tg_")) return "telegram"
  if (/^\d+$/.test(vid)) return "hh"
  return "hh"
}

export function jobSourceGroup(job: Job): SourceGroup {
  return resolveSourceGroup(job.source, job.vacancy_id)
}

/** Ссылка на площадку: job.url или построенная из vacancy_id (gm_* / hh id). */
export function resolveJobListingUrl(job: Job): string | null {
  const url = (job.url ?? "").trim()
  if (url) return url
  const vid = (job.vacancy_id ?? "").trim()
  const gm = vid.match(/^gm_(\d+)$/)
  if (gm) return `https://getmatch.ru/vacancies/${gm[1]}`
  const habr = vid.match(/^habr_(\d+)$/)
  if (habr) return `https://career.habr.com/vacancies/${habr[1]}`
  if (/^\d+$/.test(vid)) return `https://hh.ru/vacancy/${vid}`
  return null
}

/**
 * Лейбл кнопки «Открыть на {label}» — lowercase для консистентности с брендами
 * hh.ru/getmatch.ru (их brand guidelines используют lowercase); Telegram в UI
 * тоже приводим к lowercase для единого стиля (D7). Канон SOURCE_GROUP_* в бэке:
 * "hh" / "getmatch" / "tg".
 */
export function listingLinkLabel(group: SourceGroup): string {
  if (group === "getmatch") return "getmatch"
  if (group === "habr") return "habr"
  if (group === "telegram") return "telegram"
  return "hh"
}

export function countJobsBySourceGroup(jobs: Job[]): Record<SourceGroup, number> {
  const out: Record<SourceGroup, number> = { hh: 0, getmatch: 0, habr: 0, telegram: 0 }
  for (const j of jobs) out[jobSourceGroup(j)] += 1
  return out
}

const SOURCE_TOKEN_RE = /(?<![a-zа-яё0-9])(hh|getmatch|tg|telegram)(?![a-zа-яё0-9])/gi
const SOURCE_TOKEN_MAP: Record<string, SourceGroup> = {
  hh: "hh",
  getmatch: "getmatch",
  tg: "telegram",
  telegram: "telegram",
}

/**
 * Извлечь упоминаемые группы источников из текста (для situation narrative).
 * Токены: hh / getmatch / tg / telegram как отдельные слова (case-insensitive).
 * Возвращает уникальные группы в порядке первого вхождения.
 */
export function extractSourceGroupsFromText(text: string | null | undefined): SourceGroup[] {
  const t = (text ?? "").trim()
  if (!t) return []
  const seen = new Set<SourceGroup>()
  const out: SourceGroup[] = []
  for (const m of t.matchAll(SOURCE_TOKEN_RE)) {
    const group = SOURCE_TOKEN_MAP[m[1].toLowerCase()]
    if (group && !seen.has(group)) {
      seen.add(group)
      out.push(group)
    }
  }
  return out
}

/** Показывать фильтр источника, когда ≥2 групп с ≥5 вакансиями (GM-6). */
export function sourceFilterEligible(jobs: Job[]): boolean {
  const counts = countJobsBySourceGroup(jobs)
  return SOURCE_GROUPS.filter((g) => counts[g] >= 5).length >= 2
}
