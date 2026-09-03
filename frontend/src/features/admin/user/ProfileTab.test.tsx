// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, render, screen } from "@testing-library/react"
import type { AdminUserRow } from "@/api/admin"

vi.mock("@/features/admin/use-admin", () => ({
  useDisableAdminUser: () => ({ isPending: false, mutate: vi.fn() }),
  useEnableAdminUser: () => ({ isPending: false, mutate: vi.fn() }),
  useRevokeAdminSessions: () => ({ isPending: false, mutate: vi.fn() }),
  useRevokeAdminUserSession: () => ({ isPending: false, mutate: vi.fn() }),
  useRevokeAdminKey: () => ({ isPending: false, mutate: vi.fn() }),
  useSetAdminUserRole: () => ({ isPending: false, mutate: vi.fn() }),
  useIssueAdminKey: () => ({ isPending: false, mutate: vi.fn(), mutateAsync: vi.fn() }),
  useVerifyAdminKey: () => ({ isPending: false, mutateAsync: vi.fn() }),
  useVerifyStoredAdminKey: () => ({ isPending: false, mutateAsync: vi.fn() }),
  useAdminUserDiagnosis: () => ({ data: undefined, isLoading: false }),
}))

import { ProfileTab } from "./ProfileTab"

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
    today_cost_usd: 0.2,
    errors_24h: 0,
    session_count: 2,
    telegram_chat_id: 11,
    key_origin: "self",
    key_hint: "…ab",
    month_cost_usd: 1,
    month_tokens_in: 10,
    month_tokens_out: 5,
    spend_month_usd: 1,
    spend_alert: false,
    last_seen_at: "2026-08-25T10:00:00Z",
    last_seen_ip: "1.2.3.4",
    ...over,
  }
}

describe("ProfileTab", () => {
  it("ключ и сессии сверху, деньги таблицей, без отдельного доступа и блока роли", () => {
    render(<ProfileTab user={user()} detail={undefined} />)
    expect(screen.getByRole("heading", { name: "Ключ OpenRouter" })).toBeTruthy()
    expect(screen.getByRole("heading", { name: "Сессии" })).toBeTruthy()
    expect(screen.queryByText("Доступ")).toBeNull()
    expect(screen.getByText("Что не так")).toBeTruthy()
    expect(screen.getByText("Всё на месте")).toBeTruthy()
    expect(screen.getByText("Деньги")).toBeTruthy()
    expect(screen.getByText("Период")).toBeTruthy()
    expect(screen.getByText("Работа")).toBeTruthy()
    expect(screen.queryByRole("heading", { name: "Роль" })).toBeNull()
    expect(screen.queryByText("Воронка")).toBeNull()
    expect(screen.queryByText("Был")).toBeNull()
  })
})
