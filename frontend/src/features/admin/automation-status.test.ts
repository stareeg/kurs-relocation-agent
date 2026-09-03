import { describe, expect, it } from "vitest"
import {
  applyStateChip,
  briefApplyTone,
  briefDiscoveryTone,
  capPct,
  countActive,
  discoveryStateChip,
  runnerAsleep,
} from "./automation-status"

describe("discoveryStateChip", () => {
  it("running → strong «работает»", () => {
    expect(discoveryStateChip("running")).toEqual({ label: "работает", tone: "strong" })
  })
  it("дневной лимит и блок различаются по тону", () => {
    expect(discoveryStateChip("paused_daily_cap").tone).toBe("warn")
    expect(discoveryStateChip("paused_suspected_block").tone).toBe("bad")
  })
  it("любая другая пауза → warn «на паузе»", () => {
    expect(discoveryStateChip("paused_by_user")).toEqual({ label: "на паузе", tone: "warn" })
  })
  it("idle → info «выключен»", () => {
    expect(discoveryStateChip("idle").tone).toBe("info")
  })
})

describe("applyStateChip", () => {
  it("выключен → info", () => {
    expect(applyStateChip(false, false).tone).toBe("info")
  })
  it("включён без проверки → strong", () => {
    expect(applyStateChip(true, false)).toEqual({ label: "включён", tone: "strong" })
  })
  it("включён в режиме проверки → warn", () => {
    expect(applyStateChip(true, true)).toEqual({ label: "проверка", tone: "warn" })
  })
})

describe("brief tones", () => {
  it("discovery running/paused/idle", () => {
    expect(briefDiscoveryTone("running")).toBe("strong")
    expect(briefDiscoveryTone("paused")).toBe("warn")
    expect(briefDiscoveryTone(undefined)).toBe("info")
  })
  it("apply live/stale/off", () => {
    expect(briefApplyTone("live")).toBe("strong")
    expect(briefApplyTone("stale")).toBe("warn")
    expect(briefApplyTone("off")).toBe("info")
  })
})

describe("countActive", () => {
  it("считает площадки в активном состоянии", () => {
    const map = { hh: "running", getmatch: "idle", habr: "running" }
    expect(countActive(map, (s) => s === "running")).toBe(2)
  })
  it("пустая карта → 0", () => {
    expect(countActive(undefined, (s) => s === "running")).toBe(0)
  })
})

describe("runnerAsleep", () => {
  const now = new Date("2026-08-28T12:00:00Z").getTime()
  it("тик минуту назад при 60с-периоде — жив", () => {
    expect(runnerAsleep("2026-08-28T11:59:00Z", 60, now)).toBe(false)
  })
  it("тик 5 минут назад при 60с-периоде — усыплён", () => {
    expect(runnerAsleep("2026-08-28T11:55:00Z", 60, now)).toBe(true)
  })
  it("нет тика — не считаем усыплённым (могли не запускать)", () => {
    expect(runnerAsleep(null, 60, now)).toBe(false)
  })
})

describe("capPct", () => {
  it("45 из 200 ≈ 23%", () => {
    expect(capPct(45, 200)).toBe(23)
  })
  it("сверх потолка → 100", () => {
    expect(capPct(250, 200)).toBe(100)
  })
  it("нулевой потолок → 0", () => {
    expect(capPct(5, 0)).toBe(0)
  })
})
