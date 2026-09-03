import { describe, expect, it } from "vitest"
import {
  dayTickPositions,
  daysAgoFromIso,
  rangeBackgroundPoints,
  rangeBackgroundPolyline,
} from "./range-slider-geometry"

const NOW = new Date(Date.UTC(2026, 7, 3)) // 3 августа 2026

describe("daysAgoFromIso", () => {
  it("сегодня → 0", () => {
    expect(daysAgoFromIso("2026-08-03", NOW)).toBe(0)
  })

  it("вчера → 1", () => {
    expect(daysAgoFromIso("2026-08-02", NOW)).toBe(1)
  })

  it("14 дней назад → 14", () => {
    expect(daysAgoFromIso("2026-07-20", NOW)).toBe(14)
  })
})

describe("rangeBackgroundPoints", () => {
  it("меньше двух точек → []", () => {
    expect(rangeBackgroundPoints([], NOW)).toEqual([])
    expect(rangeBackgroundPoints([{ day: "2026-08-03", value: 50 }], NOW)).toEqual([])
  })

  it("сегодняшняя точка — на правом краю (xPct=100)", () => {
    const points = rangeBackgroundPoints(
      [
        { day: "2026-07-20", value: 10 },
        { day: "2026-08-03", value: 50 },
      ],
      NOW,
    )
    expect(points.at(-1)!.xPct).toBe(100)
  })

  it("значения нормализуются к 0..100 по своему мин/макс", () => {
    const points = rangeBackgroundPoints(
      [
        { day: "2026-08-01", value: 10 },
        { day: "2026-08-02", value: 30 },
        { day: "2026-08-03", value: 50 },
      ],
      NOW,
    )
    expect(points.map((p) => p.yPct)).toEqual([0, 50, 100])
  })

  it("одинаковые значения → плоская линия на середине (50), не NaN", () => {
    const points = rangeBackgroundPoints(
      [
        { day: "2026-08-01", value: 40 },
        { day: "2026-08-03", value: 40 },
      ],
      NOW,
    )
    expect(points.every((p) => p.yPct === 50)).toBe(true)
  })

  it("сортирует по календарному дню, даже если вход не по порядку", () => {
    const points = rangeBackgroundPoints(
      [
        { day: "2026-08-03", value: 50 },
        { day: "2026-07-20", value: 10 },
      ],
      NOW,
    )
    expect(points[0]!.xPct).toBeLessThan(points[1]!.xPct)
  })
})

describe("rangeBackgroundPolyline", () => {
  it("формирует валидные пары `x,y` для SVG polyline", () => {
    const result = rangeBackgroundPolyline(
      [
        { xPct: 0, yPct: 0 },
        { xPct: 100, yPct: 100 },
      ],
      40,
    )
    expect(result).toBe("0,40 100,0")
  })
})

describe("dayTickPositions", () => {
  it("по засечке на каждый день, когда домен узкий (не прорежено)", () => {
    const ticks = dayTickPositions(10, 560)
    expect(ticks).toHaveLength(11) // дни 0..10 включительно
    expect(ticks[0]).toBe(100) // день 0 (сегодня) — правый край
    expect(ticks.at(-1)).toBe(0) // день maxDays — левый край
  })

  it("прореживает шагом дней при широком домене (иначе засечки слипаются)", () => {
    const ticks = dayTickPositions(400, 560, 4) // 560/4 = 140 макс. засечек
    expect(ticks.length).toBeLessThan(401)
    expect(ticks.length).toBeGreaterThan(1)
  })

  it("нулевой домен/ширина → []", () => {
    expect(dayTickPositions(0, 560)).toEqual([])
    expect(dayTickPositions(10, 0)).toEqual([])
  })
})
