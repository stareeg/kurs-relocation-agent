import { describe, expect, it } from "vitest"
import type { AdminUserRow } from "@/api/admin"
import { personHoverTitle } from "./person-title"

function user(over: Partial<AdminUserRow> = {}): AdminUserRow {
  return {
    account_id: 4,
    telegram_username: "kate",
    telegram_user_id: 100,
    role: "member",
    status: "active",
    has_resume: true,
    has_openrouter_key: true,
    extension_confirmed: true,
    active_jobs: 1,
    today_cost_usd: 0,
    errors_24h: 0,
    session_count: 1,
    telegram_chat_id: 11,
    key_origin: "self",
    key_hint: "",
    spend_month_usd: 0,
    spend_alert: false,
    month_cost_usd: 0,
    month_tokens_in: 0,
    month_tokens_out: 0,
    ...over,
  }
}

describe("personHoverTitle", () => {
  it("здоровый — внутренний id", () => {
    expect(personHoverTitle(user())).toBe("id 4")
  })

  it("собирает, чего не хватает", () => {
    expect(
      personHoverTitle(
        user({
          has_openrouter_key: false,
          has_resume: false,
          extension_confirmed: false,
          telegram_chat_id: null,
          errors_24h: 3,
          spend_alert: true,
          note: "друг",
        }),
      ),
    ).toBe("нет ключа · нет резюме · нет расширения · нет чата с ботом · 3 ошибок за сутки · порог расхода · друг")
  })
})
