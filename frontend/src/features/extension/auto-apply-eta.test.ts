import { describe, expect, it } from "vitest"
import {
  computeQueueEtaMs,
  formatEtaShort,
  runnerLooksAsleep,
  type AutoApplySchedule,
} from "./auto-apply-eta"

const NOW = Date.parse("2026-08-28T12:00:00Z")

function schedule(over: Partial<AutoApplySchedule> = {}): AutoApplySchedule {
  return {
    runner_last_tick_at: "2026-08-28T11:58:00Z", // 2 мин назад → следующий тик через 3 мин
    tick_seconds: 300,
    real_per_tick: 1,
    gap_seconds: 55,
    min_gap_seconds: 35,
    ...over,
  }
}

describe("computeQueueEtaMs", () => {
  it("первая строка — на следующем тике раннера", () => {
    const eta = computeQueueEtaMs(schedule(), 0, NOW)
    // last_tick + 300с = 11:58 + 5 мин = 12:03 → через 3 мин
    expect(Math.round((eta - NOW) / 60_000)).toBe(3)
  })

  it("при 1 реальном отклике за тик каждая следующая строка — на следующем тике", () => {
    const s = schedule()
    const first = computeQueueEtaMs(s, 0, NOW)
    const second = computeQueueEtaMs(s, 1, NOW)
    const third = computeQueueEtaMs(s, 2, NOW)
    expect(second - first).toBe(300_000)
    expect(third - second).toBe(300_000)
  })

  it("при нескольких за тик строки внутри тика разнесены по паузе (max gap vs min gap)", () => {
    const s = schedule({ real_per_tick: 3, gap_seconds: 40, min_gap_seconds: 35 })
    const first = computeQueueEtaMs(s, 0, NOW)
    const second = computeQueueEtaMs(s, 1, NOW)
    expect(second - first).toBe(40_000) // gap_seconds > min_gap_seconds
    const fourth = computeQueueEtaMs(s, 3, NOW) // следующий тик
    expect(fourth - first).toBe(300_000)
  })

  it("без heartbeat — первый тик не позже чем через период", () => {
    const eta = computeQueueEtaMs(schedule({ runner_last_tick_at: null }), 0, NOW)
    expect(Math.round((eta - NOW) / 60_000)).toBe(5)
  })

  it("протухший heartbeat не уводит ETA в прошлое", () => {
    const eta = computeQueueEtaMs(
      schedule({ runner_last_tick_at: "2026-08-28T09:00:00Z" }),
      0,
      NOW,
    )
    expect(eta).toBeGreaterThanOrEqual(NOW)
  })
})

describe("formatEtaShort", () => {
  it("округляет и подписывает", () => {
    expect(formatEtaShort(NOW + 4 * 60_000, NOW)).toBe("≈ через 4 мин")
    expect(formatEtaShort(NOW - 1000, NOW)).toBe("≈ сейчас")
    expect(formatEtaShort(NOW + 70 * 60_000, NOW)).toBe("≈ через 1 ч 10 мин")
    expect(formatEtaShort(NOW + 120 * 60_000, NOW)).toBe("≈ через 2 ч")
  })
})

describe("runnerLooksAsleep", () => {
  it("молчит дольше трёх периодов", () => {
    expect(runnerLooksAsleep(schedule({ runner_last_tick_at: "2026-08-28T11:58:00Z" }), NOW)).toBe(
      false,
    )
    expect(runnerLooksAsleep(schedule({ runner_last_tick_at: "2026-08-28T11:40:00Z" }), NOW)).toBe(
      true,
    )
    expect(runnerLooksAsleep(schedule({ runner_last_tick_at: null }), NOW)).toBe(false)
  })
})
