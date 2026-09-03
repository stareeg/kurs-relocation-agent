import { describe, expect, it } from "vitest"
import type { AdminAuditRow, AdminLogRow } from "@/api/admin"
import { mergeJournalEntries } from "./journal-merge"

function log(over: Partial<AdminLogRow> = {}): AdminLogRow {
  return {
    id: 1,
    ts: "2026-08-25T15:00:00Z",
    level: "ERROR",
    logger: "api",
    event: "HTTP",
    msg: "boom",
    account_id: 4,
    ...over,
  }
}

function audit(over: Partial<AdminAuditRow> = {}): AdminAuditRow {
  return {
    id: 9,
    at: "2026-08-25T15:01:00Z",
    actor_id: 1,
    actor_username: "op",
    action: "key_issue",
    target_id: 4,
    target_username: "kate",
    details: {},
    ...over,
  }
}

describe("mergeJournalEntries", () => {
  it("кладёт аудит и логи в одну ленту, новые сверху, без дубля АДМИН", () => {
    const entries = mergeJournalEntries(
      [log({ id: 2, event: "АДМИН", ts: "2026-08-25T15:01:00Z" }), log({ id: 3, ts: "2026-08-25T14:00:00Z" })],
      [audit()],
    )
    expect(entries.map((item) => item.kind)).toEqual(["audit", "log"])
    expect(entries[1]?.kind === "log" && entries[1].log.id).toBe(3)
  })
})
