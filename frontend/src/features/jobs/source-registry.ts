import type { JobSourceItem } from "@/api/meta"

/**
 * 7.4 / D2 / D3: реестр источников вакансий по UI-группам.
 *
 * Бэк (`core/repo/jobs.py:ALL_JOB_SOURCES`) — единственный источник истины для перечня
 * `jobs.source`. Фронт раньше хардкодил `HH_SOURCES` в `source.ts`, что рассинхронизировалось
 * с бэком при добавлении нового источника (D2). Теперь реестр — единственное место, где
 * хранится маппинг source→group, и оно обновляемое: `applyJobSources` вызывается при старте
 * приложения из `useJobSources` (после `GET /api/meta/sources`).
 *
 * Дефолт-инициализация — каноничные значения из бэка на момент написания (для мгновенного
 * старта, пока `/api/meta/sources` не пришёл: фолбэк `resolveSourceGroup` должен работать
 * с первого рендера, без ожидания fetch). После первого успешного `applyJobSources` дефолт
 * заменяется актуальным списком с бэка.
 */

// Канон `SOURCE_GROUP_*` из `core/repo/jobs.py` (lowercase). Должен совпадать с бэком.
export const SOURCE_GROUP_HH = "hh" as const
export const SOURCE_GROUP_GETMATCH = "getmatch" as const
export const SOURCE_GROUP_HABR = "habr" as const
export const SOURCE_GROUP_TELEGRAM = "tg" as const

// UI-группа в типе SourceGroup — "telegram" (не "tg"), чтобы читалось человеком в UI.
// Конверсия "tg" → "telegram" делается в `_uiGroup`.
const _BACKEND_TO_UI: Record<string, string> = {
  [SOURCE_GROUP_HH]: "hh",
  [SOURCE_GROUP_GETMATCH]: "getmatch",
  [SOURCE_GROUP_HABR]: "habr",
  [SOURCE_GROUP_TELEGRAM]: "telegram",
}

/** Группа для UI-кода (SourceGroup: "hh" | "getmatch" | "habr" | "telegram"). */
function _uiGroup(backendGroup: string): string {
  return _BACKEND_TO_UI[backendGroup] ?? "hh"
}

/** Backend-группа для UI-значения (обратная конверсия для согласованности). */
export function toBackendGroup(uiGroup: "hh" | "getmatch" | "habr" | "telegram"): string {
  switch (uiGroup) {
    case "hh":
      return SOURCE_GROUP_HH
    case "getmatch":
      return SOURCE_GROUP_GETMATCH
    case "habr":
      return SOURCE_GROUP_HABR
    case "telegram":
      return SOURCE_GROUP_TELEGRAM
  }
}

// Дефолт-реестр (канон `core/repo/jobs.py` на момент написания). После первого
// `applyJobSources` заменяется актуальным списком с бэка. Не Remove — это стартовая
// точка, без которой `resolveSourceGroup` не сможет работать до fetch.
const _DEFAULT_SOURCES: ReadonlyArray<JobSourceItem> = [
  { source: "vacancy_page", group: SOURCE_GROUP_HH },
  { source: "hh_negotiations", group: SOURCE_GROUP_HH },
  { source: "hh_apply_stub", group: SOURCE_GROUP_HH },
  { source: "serp", group: SOURCE_GROUP_HH },
  { source: "search_batch", group: SOURCE_GROUP_HH },
  { source: "search_batch_fallback", group: SOURCE_GROUP_HH },
  { source: "score_cli", group: SOURCE_GROUP_HH },
  { source: "hr_thread_stub", group: SOURCE_GROUP_HH },
  { source: "manual", group: SOURCE_GROUP_HH },
  { source: SOURCE_GROUP_GETMATCH, group: SOURCE_GROUP_GETMATCH },
  { source: SOURCE_GROUP_HABR, group: SOURCE_GROUP_HABR },
  { source: "telegram_channel", group: SOURCE_GROUP_TELEGRAM },
]

// source → UI-группа. Инициализируется дефолтом, обновляется через `applyJobSources`.
let _sourceToUiGroup: Map<string, string> = new Map(
  _DEFAULT_SOURCES.map((it) => [it.source, _uiGroup(it.group)]),
)

let _initialized = false

/**
 * Применить справочник источников из бэка (`GET /api/meta/sources`).
 * Идемпотентно. Вызывается один раз при старте приложения (через `useJobSources`).
 * После вызова все последующие `resolveSourceGroup` используют актуальный перечень.
 */
export function applyJobSources(items: ReadonlyArray<JobSourceItem>): void {
  const next = new Map<string, string>()
  for (const it of items) {
    next.set(it.source, _uiGroup(it.group))
  }
  _sourceToUiGroup = next
  _initialized = true
}

/** Возвращает true, если `applyJobSources` уже вызывался (реестр синхронизирован с бэком). */
export function isSourceRegistryInitialized(): boolean {
  return _initialized
}

/**
 * Множество источников группы "hh" (для быстрого lookup в `resolveSourceGroup`).
 * Не экспортируется наружу — используйте `resolveSourceGroup`.
 */
export function _hhSourcesSet(): Set<string> {
  const out = new Set<string>()
  for (const [src, group] of _sourceToUiGroup) {
    if (group === "hh") out.add(src)
  }
  return out
}

/**
 * Полный реестр source → UI-группа (для отладки/тестов). Не мутировать.
 * Возвращает копию, чтобы случайная мутация не сломала реестр.
 */
export function getSourceRegistrySnapshot(): Record<string, string> {
  const out: Record<string, string> = {}
  for (const [src, group] of _sourceToUiGroup) {
    out[src] = group
  }
  return out
}

/** Сбросить реестр к дефолту (для тестов). */
export function _resetSourceRegistryForTests(): void {
  _sourceToUiGroup = new Map(_DEFAULT_SOURCES.map((it) => [it.source, _uiGroup(it.group)]))
  _initialized = false
}
