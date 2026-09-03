/**
 * Состояние журнала ⇄ query URL. Фильтры живут в адресе, чтобы ссылку на
 * инцидент можно было сохранить.
 */

export const JOURNAL_WINDOWS = ["15m", "1h", "24h", "7d"] as const
export type JournalWindow = (typeof JOURNAL_WINDOWS)[number]
export const DEFAULT_JOURNAL_WINDOW: JournalWindow = "1h"

export const JOURNAL_WINDOW_MS: Record<JournalWindow, number> = {
  "15m": 15 * 60_000,
  "1h": 60 * 60_000,
  "24h": 24 * 60 * 60_000,
  "7d": 7 * 24 * 60 * 60_000,
}

export const JOURNAL_WINDOW_CHIPS = [
  { value: "15m", label: "15 мин" },
  { value: "1h", label: "1 ч" },
  { value: "24h", label: "24 ч" },
  { value: "7d", label: "7 дней" },
] as const

export const JOURNAL_LEVELS = ["ERROR", "WARNING", "INFO", "DEBUG"] as const
export type JournalLevel = (typeof JOURNAL_LEVELS)[number]
export const DEFAULT_JOURNAL_LEVELS: JournalLevel[] = ["ERROR", "WARNING"]

export const JOURNAL_LEVEL_CHIPS = [
  { value: "ERROR", label: "ERROR" },
  { value: "WARNING", label: "WARNING" },
  { value: "INFO", label: "INFO" },
  { value: "DEBUG", label: "DEBUG" },
] as const

export type JournalFilters = {
  window: JournalWindow
  levels: JournalLevel[]
  telegramUserId: string
  /** Скрытый фильтр для ссылок из очереди внимания / карточки логов. */
  accountId: string
  live: boolean
  cursor: string
}

export const DEFAULT_JOURNAL_FILTERS: JournalFilters = {
  window: DEFAULT_JOURNAL_WINDOW,
  levels: DEFAULT_JOURNAL_LEVELS,
  telegramUserId: "",
  accountId: "",
  live: true,
  cursor: "",
}

export function isJournalWindow(value: string | null | undefined): value is JournalWindow {
  return JOURNAL_WINDOWS.includes((value ?? "") as JournalWindow)
}

export function isJournalLevel(value: string): value is JournalLevel {
  return JOURNAL_LEVELS.includes(value as JournalLevel)
}

export function parseJournalLevels(raw: string | null): JournalLevel[] {
  if (raw == null || raw.trim() === "") return [...DEFAULT_JOURNAL_LEVELS]
  const parsed = raw
    .split(",")
    .map((item) => item.trim().toUpperCase())
    .filter(isJournalLevel)
  return parsed.length > 0 ? parsed : [...DEFAULT_JOURNAL_LEVELS]
}

export function parseJournalFilters(params: URLSearchParams): JournalFilters {
  const live = params.get("live")
  const window = params.get("window")
  return {
    window: isJournalWindow(window) ? window : DEFAULT_JOURNAL_WINDOW,
    levels: parseJournalLevels(params.get("level")),
    telegramUserId: (params.get("telegram_user_id") ?? "").trim(),
    accountId: (params.get("account_id") ?? "").trim(),
    live: live == null ? true : live !== "0",
    cursor: (params.get("cursor") ?? "").trim(),
  }
}

export function journalFiltersToParams(filters: JournalFilters): URLSearchParams {
  const params = new URLSearchParams()
  if (filters.window !== DEFAULT_JOURNAL_WINDOW) params.set("window", filters.window)
  const levelValue = [...filters.levels].sort().join(",")
  const defaultLevel = [...DEFAULT_JOURNAL_LEVELS].sort().join(",")
  if (levelValue !== defaultLevel) params.set("level", filters.levels.join(","))
  if (filters.telegramUserId) params.set("telegram_user_id", filters.telegramUserId)
  if (filters.accountId) params.set("account_id", filters.accountId)
  if (!filters.live) params.set("live", "0")
  if (filters.cursor) params.set("cursor", filters.cursor)
  return params
}

export function adminJournalPath(patch: Partial<JournalFilters> = {}): string {
  const params = journalFiltersToParams({ ...DEFAULT_JOURNAL_FILTERS, ...patch })
  const query = params.toString()
  return query ? `/admin/journal?${query}` : "/admin/journal"
}

export function journalWindowBounds(
  window: JournalWindow,
  now = Date.now(),
): { since: string; until: string } {
  return {
    since: new Date(now - JOURNAL_WINDOW_MS[window]).toISOString(),
    until: new Date(now).toISOString(),
  }
}

export function journalRequestWindow(
  filters: JournalFilters,
  now = Date.now(),
): { since: string; until: string } {
  return journalWindowBounds(filters.window, now)
}

export function logLevelTone(level: string): "bad" | "warn" | "info" | null {
  if (level === "ERROR" || level === "CRITICAL") return "bad"
  if (level === "WARNING") return "warn"
  if (level === "INFO") return "info"
  return null
}

export const AUDIT_ACTION_LABELS: Record<string, string> = {
  disable: "Отключил",
  enable: "Включил",
  revoke_sessions: "Сбросил сессии",
  log_bundle: "Скачал логи файлом",
  key_issue: "Выдал ключ",
  key_revoke: "Отозвал ключ",
  key_reject: "Отклонил заявку",
  telegram: "Написал в Telegram",
  support_agent: "Спросил агента поддержки",
  revoke_session: "Завершил сессию",
  role_change: "Сменил роль",
  note: "Обновил заметку",
  task_retry: "Перезапустил задачу",
  task_cancel: "Отменил задачу",
  task_reclaim: "Вернул зависшие в очередь",
  logs_purge: "Удалил логи",
  friendships_repair: "Починил дружбы",
}

export function auditActionLabel(action: string): string {
  return AUDIT_ACTION_LABELS[action] ?? action
}
