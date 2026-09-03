import type { AdminUserRow } from "@/api/admin"
import {
  PEOPLE_COLUMN_LABELS,
  type PeopleColumnKey,
} from "@/features/admin/admin-filters"
import { atHandle, usd } from "@/features/admin/admin-format"

/**
 * CSV текущего среза таблицы людей — то, что оператор видит, а не дамп всех полей.
 *
 * Чистая функция: скачивание живёт у кнопки, чтобы тест не трогал `document`.
 */
export function peopleCsv(
  people: readonly AdminUserRow[],
  cols: readonly PeopleColumnKey[],
): string {
  const header = cols.map((key) => csvCell(PEOPLE_COLUMN_LABELS[key])).join(",")
  const lines = people.map((user) =>
    cols.map((key) => csvCell(peopleCsvValue(user, key))).join(","),
  )
  return [header, ...lines].join("\r\n")
}

export function peopleCsvValue(user: AdminUserRow, key: PeopleColumnKey): string {
  switch (key) {
    case "person":
      return atHandle(user.telegram_username)
    case "key":
      return user.has_openrouter_key ? "да" : "нет"
    case "resume":
      return user.has_resume ? "да" : "нет"
    case "extension":
      return user.extension_confirmed ? "да" : "нет"
    case "seen":
      return user.last_seen_at ?? ""
    case "cost_month":
      return usd(user.month_cost_usd)
    case "errors":
      return String(user.errors_24h)
    case "jobs":
      return String(user.active_jobs)
    case "cost_today":
      return usd(user.today_cost_usd)
  }
}

export function csvCell(value: string | number | null | undefined): string {
  const raw = value == null ? "" : String(value)
  if (/[",\r\n]/.test(raw)) return `"${raw.replace(/"/g, '""')}"`
  return raw
}

export function downloadCsv(filename: string, csv: string): void {
  const blob = new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8" })
  const href = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = href
  a.download = filename
  a.rel = "noopener"
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(href)
}
