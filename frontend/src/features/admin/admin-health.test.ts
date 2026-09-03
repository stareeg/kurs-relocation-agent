import { describe, expect, it } from "vitest"
import type { AdminHealth } from "@/api/admin"
import { buildHealthItems } from "./admin-health"

const HEALTHY: AdminHealth = {
  extension_version: "1.4.0",
  git_sha: "abc1234",
  postgres_ok: true,
  postgres_size_bytes: 128 * 1024 * 1024,
  worker_running: true,
  worker_last_finished_at: new Date().toISOString(),
  queue: { pending: 0, running: 0, failed: 0, done: 12, cancelled: 0 },
  migrations_applied: 141,
  migrations_available: 141,
  model_tier_advanced: "google/gemini-3.7-flash",
  model_tier_basic: "openai/gpt-5.6-luna",
  model_tier_reserve: "google/gemini-3.7-flash",
}

describe("buildHealthItems", () => {
  it("пустые факты — пустой список, а не семь серых точек", () => {
    expect(buildHealthItems(undefined)).toEqual([])
  })

  it("здоровый флот — тон ok (точка не рисуется) и без «неизвестно»", () => {
    const items = buildHealthItems(HEALTHY)
    expect(items.map((item) => item.key)).toEqual([
      "extension",
      "backend",
      "postgres",
      "worker",
      "queue",
      "migrations",
      "llm",
    ])
    expect(items.every((item) => item.tone === "ok")).toBe(true)
    expect(items.find((i) => i.key === "postgres")?.value).toBe("128.0 МБ")
    expect(items.find((i) => i.key === "llm")?.value).toBe("gemini-3.7-flash · gpt-5.6-luna")
  })

  it("сбои очереди и мёртвый воркер — bad, чтобы красная точка была видна сразу", () => {
    const items = buildHealthItems({
      ...HEALTHY,
      worker_running: false,
      queue: { pending: 2, running: 0, failed: 12, done: 0, cancelled: 0 },
      postgres_ok: false,
      postgres_size_bytes: null,
    })
    expect(items.find((i) => i.key === "worker")?.tone).toBe("bad")
    expect(items.find((i) => i.key === "queue")?.tone).toBe("bad")
    expect(items.find((i) => i.key === "queue")?.value).toBe("12 сбоев")
    expect(items.find((i) => i.key === "postgres")?.tone).toBe("bad")
  })

  it("отстающие миграции — bad, неизвестный коммит — warn", () => {
    const items = buildHealthItems({
      ...HEALTHY,
      git_sha: "",
      extension_version: "",
      migrations_applied: 140,
      migrations_available: 141,
      model_tier_basic: "",
    })
    expect(items.find((i) => i.key === "backend")?.tone).toBe("warn")
    expect(items.find((i) => i.key === "extension")?.tone).toBe("warn")
    expect(items.find((i) => i.key === "migrations")?.tone).toBe("bad")
    expect(items.find((i) => i.key === "llm")?.tone).toBe("warn")
  })
})
