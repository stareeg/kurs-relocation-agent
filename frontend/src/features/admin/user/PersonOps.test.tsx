// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, render, screen } from "@testing-library/react"
import type { AdminUserRow } from "@/api/admin"

vi.mock("@/features/admin/use-admin", () => ({
  useRevokeAdminSessions: () => ({ isPending: false, mutate: vi.fn() }),
  useRevokeAdminUserSession: () => ({ isPending: false, mutate: vi.fn() }),
  useRevokeAdminKey: () => ({ isPending: false, mutate: vi.fn() }),
  useIssueAdminKey: () => ({ isPending: false, mutate: vi.fn(), mutateAsync: vi.fn() }),
  useVerifyAdminKey: () => ({ isPending: false, mutateAsync: vi.fn() }),
  useVerifyStoredAdminKey: () => ({ isPending: false, mutateAsync: vi.fn() }),
}))

import { PersonOps } from "./PersonOps"

afterEach(cleanup)

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
    key_origin: "admin",
    key_hint: "…15fb",
    month_cost_usd: 0,
    month_tokens_in: 0,
    month_tokens_out: 0,
    spend_month_usd: 0,
    spend_alert: false,
    ...over,
  }
}

describe("PersonOps", () => {
  it("показывает ключ и сессии, без отдельного чата", () => {
    render(<PersonOps user={user()} detail={undefined} />)
    expect(screen.getByRole("heading", { name: "Ключ OpenRouter" })).toBeTruthy()
    expect(screen.getByRole("heading", { name: "Сессии" })).toBeTruthy()
    expect(screen.queryByRole("heading", { name: "Аккаунт" })).toBeNull()
    expect(screen.queryByRole("heading", { name: "Написать в Telegram" })).toBeNull()
    expect(screen.queryByText("Заметка")).toBeNull()
    expect(screen.queryByText("Логи файлом")).toBeNull()
  })
})
