// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, render, screen } from "@testing-library/react"
import type { AdminAttention } from "@/api/admin"

const attentionData = vi.fn<() => AdminAttention | undefined>()

vi.mock("@/features/admin/use-admin", () => ({
  ADMIN_BADGE_POLL_MS: 120_000,
  useAdminAttention: () => ({ data: attentionData() }),
}))

import { AdminAttentionBadge } from "./AdminAttentionBadge"

afterEach(() => {
  cleanup()
  attentionData.mockReset()
})

const EMPTY: AdminAttention = {
  key_requests: [],
  failed_tasks: [],
  failed_tasks_total: 0,
  errors: [],
  errors_total: 0,
  error_bursts: [],
  stale: [],
  no_key: [],
  spend_over: [],
  spend_alert_usd: 0,
  degraded: false,
  degraded_reason: "",
}

describe("AdminAttentionBadge", () => {
  it("дел нет — бейджа нет вовсе, а не «0»", () => {
    attentionData.mockReturnValue(EMPTY)
    const { container } = render(<AdminAttentionBadge enabled />)
    expect(container.textContent).toBe("")
  })

  it("данные ещё не приехали — тоже ничего не рисуем", () => {
    attentionData.mockReturnValue(undefined)
    const { container } = render(<AdminAttentionBadge enabled />)
    expect(container.textContent).toBe("")
  })

  it("считает дела той же меркой, что список на Обзоре", () => {
    attentionData.mockReturnValue({
      ...EMPTY,
      stale: [
        { account_id: 2, telegram_username: "a", days_silent: 9 },
        { account_id: 3, telegram_username: "b", days_silent: 12 },
      ],
    })
    render(<AdminAttentionBadge enabled />)
    expect(screen.getByText("2")).toBeTruthy()
  })

  it("дело, блокирующее человека, показывает бейдж", () => {
    attentionData.mockReturnValue({
      ...EMPTY,
      no_key: [{ account_id: 4, telegram_username: "c", days_waiting: 3 }],
    })
    render(<AdminAttentionBadge enabled />)
    expect(screen.getByText("1")).toBeTruthy()
  })
})
