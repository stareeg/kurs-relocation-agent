import { describe, expect, it } from "vitest"
import { normalizePoints, sparklineKind, sparklineLayout } from "./sparkline-geometry"

describe("Sparkline geometry (W-01 / W-12)", () => {
  it("пустые данные → пустой массив (ничего не рисуем)", () => {
    expect(normalizePoints([])).toEqual([])
    expect(sparklineKind([])).toBe("empty")
  })

  it("одна точка → точка, не линия", () => {
    expect(normalizePoints([42])).toEqual([{ x: 0, y: 42 }])
    expect(sparklineKind([42])).toBe("point")
  })

  it("две+ точки → линия", () => {
    expect(sparklineKind([10, 20])).toBe("line")
  })

  it("числа → индекс как x", () => {
    expect(normalizePoints([10, 20, 15])).toEqual([
      { x: 0, y: 10 },
      { x: 1, y: 20 },
      { x: 2, y: 15 },
    ])
  })

  it("явный x сохраняет разрывы по оси", () => {
    expect(normalizePoints([{ x: 0, y: 28 }, { x: 3, y: 35 }, { y: 40 }])).toEqual([
      { x: 0, y: 28 },
      { x: 3, y: 35 },
      { x: 2, y: 40 },
    ])
  })
})

describe("sparklineLayout (V-07)", () => {
  it("пустой набор → []", () => {
    expect(sparklineLayout([], 100, 30).coords).toEqual([])
  })

  it("растущий ряд идёт слева направо и снизу вверх", () => {
    const { coords } = sparklineLayout(normalizePoints([10, 20, 30]), 100, 30, 0)
    expect(coords[0]!.cx).toBe(0)
    expect(coords[2]!.cx).toBe(100)
    // выше значение → меньше cy (SVG y растёт вниз)
    expect(coords[2]!.cy).toBeLessThan(coords[0]!.cy)
  })

  it("плоский ряд (одна и та же y) не даёт NaN", () => {
    const { coords } = sparklineLayout(normalizePoints([5, 5, 5]), 100, 30)
    expect(coords.every((c) => Number.isFinite(c.cy))).toBe(true)
  })
})
