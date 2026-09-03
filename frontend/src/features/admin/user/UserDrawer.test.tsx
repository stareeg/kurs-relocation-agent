// @vitest-environment jsdom
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"
import { cleanup, render, screen } from "@testing-library/react"
import type { AdminUserRow } from "@/api/admin"

vi.mock("@/features/admin/use-admin", () => ({
  useAdminUser: () => ({ data: undefined }),
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
  useAdminSupportThread: () => ({ data: { items: [] }, isLoading: false }),
  useSendAdminSupportMessage: () => ({ isPending: false, mutate: vi.fn() }),
}))

import { UserDrawer } from "./UserDrawer"

beforeAll(() => {
  class Observer {
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords() {
      return []
    }
  }
  Object.assign(globalThis, { ResizeObserver: Observer, IntersectionObserver: Observer })
})

afterEach(cleanup)

function user(over: Partial<AdminUserRow> = {}): AdminUserRow {
  return {
    account_id: 4,
    telegram_username: "kate",
    telegram_user_id: 100,
    role: "member",
    status: "active",
    has_resume: true,
    has_openrouter_key: false,
    extension_confirmed: false,
    active_jobs: 0,
    today_cost_usd: 0,
    errors_24h: 0,
    session_count: 1,
    telegram_chat_id: 11,
    key_origin: null,
    key_hint: "",
    month_cost_usd: 0,
    month_tokens_in: 0,
    month_tokens_out: 0,
    spend_month_usd: 0,
    spend_alert: false,
    last_seen_at: new Date().toISOString(),
    ...over,
  }
}

describe("UserDrawer", () => {
  it("шапка с ролью справа, вкладки и Отключить, чат закреплён снизу", () => {
    render(
      <UserDrawer
        accountId={4}
        onClose={() => {}}
        people={[user()]}
        tab="profile"
        onTabChange={() => {}}
      />,
    )
    expect(screen.getByText("@kate")).toBeTruthy()
    expect(screen.getByText("роль")).toBeTruthy()
    expect(screen.getByText("активен")).toBeTruthy()
    expect(screen.getByText("Был сейчас")).toBeTruthy()
    expect(screen.getByRole("button", { name: "Отключить" })).toBeTruthy()
    expect(screen.queryByRole("button", { name: "Написать" })).toBeNull()
    expect(screen.queryByRole("button", { name: "Выдать ключ" })).toBeNull()
    expect(screen.getByRole("button", { name: "Пользователь" })).toBeTruthy()
    expect(screen.getByRole("button", { name: "Агент" })).toBeTruthy()
    expect(screen.getByLabelText("Текст сообщения")).toBeTruthy()
    expect(screen.queryByText(/Пока пусто/)).toBeNull()
  })
})
