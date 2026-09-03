import { describe, expect, it } from "vitest"
import { interpolatedPosition, lerp, nearestIndex } from "./chart-hover"

describe("nearestIndex (V-08)", () => {
  const coords = [{ cx: 0 }, { cx: 50 }, { cx: 100 }]

  it("пустой набор → 0", () => {
    expect(nearestIndex([], 42)).toBe(0)
  })

  it("курсор точно на точке → её индекс", () => {
    expect(nearestIndex(coords, 50)).toBe(1)
  })

  it("курсор между точками → ближайшая (визир липнет)", () => {
    expect(nearestIndex(coords, 60)).toBe(1)
    expect(nearestIndex(coords, 80)).toBe(2)
  })

  it("курсор за пределами ряда → крайняя точка", () => {
    expect(nearestIndex(coords, -20)).toBe(0)
    expect(nearestIndex(coords, 500)).toBe(2)
  })
})

describe("lerp", () => {
  it("линейная интерполяция между a и b по доле t", () => {
    expect(lerp(0, 100, 0)).toBe(0)
    expect(lerp(0, 100, 1)).toBe(100)
    expect(lerp(0, 100, 0.5)).toBe(50)
    expect(lerp(10, 20, 0.25)).toBe(12.5)
  })
})

describe("interpolatedPosition (план 2026-08-11 п.6 — плавный курсор между снимками)", () => {
  const coords = [{ cx: 0 }, { cx: 50 }, { cx: 100 }]

  it("пусто → null", () => {
    expect(interpolatedPosition([], 42)).toBeNull()
  })

  it("одна точка → индекс 0, t=0", () => {
    expect(interpolatedPosition([{ cx: 30 }], 999)).toEqual({ index: 0, nextIndex: 0, t: 0 })
  })

  it("курсор ровно на точке → t=0 или t=1 на границе сегмента", () => {
    expect(interpolatedPosition(coords, 0)).toEqual({ index: 0, nextIndex: 1, t: 0 })
    expect(interpolatedPosition(coords, 100)).toEqual({ index: 1, nextIndex: 2, t: 1 })
  })

  it("курсор ровно посередине сегмента → t=0.5", () => {
    expect(interpolatedPosition(coords, 25)).toEqual({ index: 0, nextIndex: 1, t: 0.5 })
    expect(interpolatedPosition(coords, 75)).toEqual({ index: 1, nextIndex: 2, t: 0.5 })
  })

  it("курсор за пределами ряда — клиппится к крайнему сегменту", () => {
    expect(interpolatedPosition(coords, -50)).toEqual({ index: 0, nextIndex: 1, t: 0 })
    expect(interpolatedPosition(coords, 500)).toEqual({ index: 1, nextIndex: 2, t: 1 })
  })

  it("совпадающие координаты (одинаковый x) не делят на ноль", () => {
    expect(interpolatedPosition([{ cx: 10 }, { cx: 10 }], 10)).toEqual({
      index: 0,
      nextIndex: 1,
      t: 0,
    })
  })
})
