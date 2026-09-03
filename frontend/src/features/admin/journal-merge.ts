import type { AdminAuditRow, AdminLogRow } from "@/api/admin"

export type JournalEntry =
  | { kind: "log"; id: string; ts: string; log: AdminLogRow }
  | { kind: "audit"; id: string; ts: string; audit: AdminAuditRow }

/**
 * Единый список: ошибки из copilot_logs + действия оператора из admin_audit.
 * Строки события «АДМИН» пропускаем — то же действие уже есть в аудите.
 */
export function mergeJournalEntries(
  logs: readonly AdminLogRow[],
  audit: readonly AdminAuditRow[],
): JournalEntry[] {
  const entries: JournalEntry[] = []
  for (const log of logs) {
    if (log.event === "АДМИН") continue
    entries.push({ kind: "log", id: `l${log.id ?? log.ts}`, ts: log.ts ?? "", log })
  }
  for (const row of audit) {
    entries.push({ kind: "audit", id: `a${row.id}`, ts: row.at ?? "", audit: row })
  }
  return entries.sort((a, b) => (a.ts < b.ts ? 1 : a.ts > b.ts ? -1 : 0))
}
