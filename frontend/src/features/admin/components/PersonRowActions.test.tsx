// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import type { AdminUserRow } from "@/api/admin"

vi.mock("@/features/admin/use-admin", () => ({
  useAdminUser: () => ({ data: { recent_actions: [] } }),
  useAdminSupportThread: () => ({ data: { items: [] }, isLoading: false }),
  useSendAdminSupportMessage: () => ({ isPending: false, mutate: vi.fn() }),
}))

import { PersonRowActions } from "./PersonRowActions"

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
    ...over,
  }
}

describe("PersonRowActions", () => {
  it("Чат открывает мини-ленту поддержки", () => {
    render(<PersonRowActions user={user()} />)
    fireEvent.mouseEnter(screen.getByRole("button", { name: "Чат" }).parentElement!)
    expect(screen.getByLabelText("Текст сообщения")).toBeTruthy()
    expect(screen.getByRole("button", { name: "Пользователь" })).toBeTruthy()
  })

  it("без чата кнопка неактивна", () => {
    render(<PersonRowActions user={user({ telegram_chat_id: null })} />)
    expect((screen.getByRole("button", { name: "Чат" }) as HTMLButtonElement).disabled).toBe(true)
  })
})
