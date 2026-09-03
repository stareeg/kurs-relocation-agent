import { describe, expect, it } from "vitest"
import type { AdminUserRow } from "@/api/admin"
import { csvCell, peopleCsv, peopleCsvValue } from "./people-export"

function user(over: Partial<AdminUserRow> = {}): AdminUserRow {
  return {
    account_id: 1,
    telegram_username: "kate",
    telegram_user_id: 100,
    role: "member",
    status: "active",
    has_resume: true,
    has_openrouter_key: true,
    extension_confirmed: false,
    active_jobs: 3,
    today_cost_usd: 0.11,
    errors_24h: 2,
    session_count: 1,
    telegram_chat_id: 1,
    key_origin: "admin",
    key_hint: "…15fb",
    month_cost_usd: 5.4,
    month_tokens_in: 0,
    month_tokens_out: 0,
    spend_month_usd: 5.4,
    spend_alert: false,
    last_seen_at: "2026-08-12T14:11:00Z",
    note: "друг, «кавычки»",
    ...over,
  }
}

describe("peopleCsv", () => {
  it("экранирует запятые и кавычки", () => {
    expect(csvCell("друг, «кавычки»")).toBe('"друг, «кавычки»"')
    expect(csvCell('скажи "привет"')).toBe('"скажи ""привет"""')
  })

  it("пишет видимые колонки в каноническом порядке", () => {
    const csv = peopleCsv([user()], ["person", "key", "errors"])
    expect(csv.split("\r\n")[0]).toBe("Человек,Ключ,Ошибки")
    expect(csv).toContain("@kate")
    expect(csv).toContain("да")
    expect(csv).toContain("2")
  })

  it("подключение — да/нет по ступеням", () => {
    expect(peopleCsvValue(user(), "resume")).toBe("да")
    expect(peopleCsvValue(user({ extension_confirmed: false }), "extension")).toBe("нет")
  })
})
