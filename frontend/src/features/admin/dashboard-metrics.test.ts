import { describe, expect, it } from "vitest"
import type { AdminSummary } from "@/api/admin"
import { buildDashboardMetrics, dashboardModelLabels } from "./dashboard-metrics"

const SUMMARY: AdminSummary = {
  degraded: false,
  degraded_reason: "",
  accounts_active: 3,
  seen_24h: 1,
  today_cost_usd: 0.11,
  today_cost_system_usd: 0,
  month_cost_usd: 4.2,
  errors_24h: 2,
  errors_24h_system: 0,
  pending_keys: 1,
  failed_tasks: 4,
  spend_alert_usd: 0,
  health: {
    extension_version: "1.4.0",
    git_sha: "abc",
    postgres_ok: true,
    postgres_size_bytes: 128 * 1024 * 1024,
    worker_running: true,
    queue: { pending: 0, running: 0, failed: 0, done: 0, cancelled: 0 },
    migrations_applied: 1,
    migrations_available: 1,
    model_tier_advanced: "google/gemini-3.7-flash",
    model_tier_basic: "openai/gpt-5.6-luna",
    model_tier_reserve: "google/gemini-3.7-flash",
  },
  onboarding: { telegram: 3, has_key: 2, has_resume: 2, has_extension: 1 },
}

describe("buildDashboardMetrics", () => {
  it("без сводки — пустой список", () => {
    expect(buildDashboardMetrics(undefined)).toEqual([])
  })

  it("заявки первые, база заменена на расход за 30 дней, провалы вместо сбоев", () => {
    const items = buildDashboardMetrics(SUMMARY)
    expect(items.map((item) => item.key)).toEqual([
      "keys",
      "people",
      "seen",
      "errors",
      "failed",
      "today",
      "month",
    ])
    expect(items.find((item) => item.key === "today")).toEqual({
      key: "today",
      value: "0.11",
      unit: "$",
      label: "Сегодня",
    })
    expect(items.find((item) => item.key === "month")).toEqual({
      key: "month",
      value: "4.20",
      unit: "$",
      label: "30 дней",
    })
    expect(items.find((item) => item.key === "failed")?.label).toBe("Провалы")
    expect(items.find((item) => item.key === "keys")).toEqual({
      key: "keys",
      value: "1",
      unit: "шт",
      label: "Заявки",
    })
    expect(dashboardModelLabels(SUMMARY)).toEqual(["gemini-3.7-flash", "gpt-5.6-luna"])
  })
})
