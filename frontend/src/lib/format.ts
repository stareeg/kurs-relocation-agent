// Возраст и свежесть фактов для citations (правило: факт старше 90 дней — «требует проверки»).
const DAY_MS = 86_400_000
/** Канон продукта: договорённости из HR-переписки ведутся по Москве (как Telegram у владельца). */
const EVENT_TZ = "Europe/Moscow"

export function parseDate(value?: string | null): Date | null {
  if (!value) return null
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? null : d
}

export function ageDays(value?: string | null): number | null {
  const d = parseDate(value)
  if (!d) return null
  return Math.floor((Date.now() - d.getTime()) / DAY_MS)
}

export function isStale(value?: string | null, maxDays = 90): boolean {
  const a = ageDays(value)
  return a != null && a > maxDays
}

export function formatDate(value?: string | null): string {
  const d = parseDate(value)
  if (!d) return ""
  return d.toLocaleDateString("ru-RU", { day: "numeric", month: "short", year: "numeric" })
}

export function formatDateTime(value?: string | null): string {
  const d = parseDate(value)
  if (!d) return ""
  return d.toLocaleString("ru-RU", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  })
}

/** «чт 09.07 15:00» — день недели + ДД.ММ + время по Москве (RD-15: созвон/собес). */
export function formatEventLabel(value?: string | null): string {
  const d = parseDate(value)
  if (!d) return ""
  // Явный Europe/Moscow: иначе weekday уезжает на соседний день в браузере не-МСК
  // (или при ISO без офсета), хотя час ещё «похож».
  const parts = new Intl.DateTimeFormat("ru-RU", {
    timeZone: EVENT_TZ,
    weekday: "short",
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(d)
  const get = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((p) => p.type === type)?.value ?? ""
  const weekday = get("weekday").replace(/\.$/, "")
  const day = get("day")
  const month = get("month")
  const hour = get("hour")
  const minute = get("minute")
  if (!weekday || !day || !month || !hour || !minute) return ""
  return `${weekday} ${day}.${month} ${hour}:${minute}`
}

/** «25:08 14:30» — день:месяц час:минута по Москве (лента событий вакансии). */
export function formatVacancyEventAt(value?: string | null): string {
  const d = parseDate(value)
  if (!d) return ""
  const parts = new Intl.DateTimeFormat("ru-RU", {
    timeZone: EVENT_TZ,
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(d)
  const get = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((p) => p.type === type)?.value ?? ""
  const day = get("day")
  const month = get("month")
  const hour = get("hour")
  const minute = get("minute")
  if (!day || !month || !hour || !minute) return ""
  return `${day}:${month} ${hour}:${minute}`
}

/**
 * Цена LLM-вызовов в долларах (E-9). Запуск агента стоит доли цента, поэтому мелкие суммы
 * показываются с четырьмя знаками («$0.0042»), а не округляются до «$0.00».
 * Разделитель — точка, как у сумм в админке (`features/admin/admin-format.ts`).
 */
export function formatUsd(value?: number | null): string {
  const n = value ?? 0
  if (n === 0) return "$0"
  if (n < 0.0001) return "<$0.0001"
  if (n < 1) return `$${n.toFixed(4)}`
  return `$${n.toFixed(2)}`
}

/** Число токенов с разрядами: «52 300». */
export function formatTokens(value?: number | null): string {
  return Math.round(value ?? 0).toLocaleString("ru-RU")
}
