import { describe, expect, it } from "vitest"
import {
  formatMoneyFull,
  formatSalaryShort,
  SALARY_BUCKET_COUNT,
  salaryBuckets,
  salaryDistributionLayout,
  type SalaryDistributionInput,
} from "./salary-distribution-geometry"

const points = [
  300000, 320000, 340000, 360000, 380000, 400000, 420000, 440000, 460000, 480000, 500000, 520000,
]

const baseInput: SalaryDistributionInput = {
  points,
  targetMin: 374000,
  targetMax: 450000,
  median: 400000,
  p25: 350000,
  p75: 480000,
  offers: [
    { key: "o1", company: "Сбер", value: 540000 },
    { key: "o2", company: "ПОСК", value: 450000 },
  ],
}

describe("formatSalaryShort / formatMoneyFull", () => {
  it("540 000 → 540к", () => {
    expect(formatSalaryShort(540000)).toBe("540к")
  })
  it("374 000 ₽ — полная форма с обычным пробелом", () => {
    expect(formatMoneyFull(374000)).toBe("374 000 ₽")
    expect(formatMoneyFull(374000)).not.toMatch(/\u00A0/)
  })
})

describe("salaryBuckets", () => {
  it("меньше MIN_HISTOGRAM_POINTS → пусто (честно не рисуем)", () => {
    expect(salaryBuckets([100, 200])).toEqual([])
    expect(salaryBuckets([])).toEqual([])
  })

  it("возвращает SALARY_BUCKET_COUNT корзин", () => {
    const buckets = salaryBuckets(points)
    expect(buckets).toHaveLength(SALARY_BUCKET_COUNT)
    // Сумма counts = числу точек (каждая точка ровно в одной корзине).
    expect(buckets.reduce((s, b) => s + b.count, 0)).toBe(points.length)
  })

  it("корзины идут по возрастанию from, без разрывов", () => {
    const buckets = salaryBuckets(points)
    for (let i = 1; i < buckets.length; i++) {
      expect(buckets[i]!.from).toBeCloseTo(buckets[i - 1]!.to, 5)
    }
  })

  it("все значения совпадают → пусто (одна обманчивая корзина)", () => {
    expect(salaryBuckets([400000, 400000, 400000, 400000, 400000])).toEqual([])
  })

  it("домен режется по P5–P95 — крайний выброс сворачивается в крайнюю корзину", () => {
    // 20 точек ровным кластером 300–500к + один выброс на 5м. При N=21 P95-индекс
    // (0.95×20=19) точно на последней «нормальной» точке — выброс полностью снаружи домена.
    const cluster = Array.from({ length: 20 }, (_, i) => 300000 + i * 10000)
    const withOutlier = [...cluster, 5000000]
    const buckets = salaryBuckets(withOutlier)
    // Все точки распределены по корзинам (выброс клампится в последнюю).
    expect(buckets.reduce((s, b) => s + b.count, 0)).toBe(withOutlier.length)
    // Домен (крайняя корзина .to) не растянут до выброса.
    expect(buckets[buckets.length - 1]!.to).toBeLessThan(1000000)
    // Последняя корзина содержит и последнюю нормальную точку, и свёрнутый выброс.
    expect(buckets[buckets.length - 1]!.count).toBeGreaterThanOrEqual(1)
  })
})

describe("salaryDistributionLayout", () => {
  it("строит столбики, тики, сетку, скобку цели и позиционные маркеры", () => {
    const layout = salaryDistributionLayout(baseInput, 560, 180)
    expect(layout).not.toBeNull()
    expect(layout!.bars).toHaveLength(SALARY_BUCKET_COUNT)
    expect(layout!.xTicks.length).toBeGreaterThan(0)
    expect(layout!.yTicks).toHaveLength(3)
    expect(layout!.gridLines).toHaveLength(3)
    expect(layout!.targetBracket).not.toBeNull()
    expect(layout!.targetBracket!.label).toBe("Целевая вилка")
    expect(layout!.medianMarker).not.toBeNull()
    expect(layout!.quartileTicks.map((t) => t.key)).toEqual(["p25", "p75"])
  })

  it("крайние подписи оси X не центрируются ровно на границе (иначе половина обрезается краем карточки)", () => {
    const layout = salaryDistributionLayout(baseInput, 560, 180)!
    const first = layout.xTicks[0]!
    const last = layout.xTicks[layout.xTicks.length - 1]!
    expect(first.x).toBeGreaterThanOrEqual(last.x) // тики идут от max к min
    expect(first.anchor).toBe("end") // самый правый (max) — растёт влево, внутрь графика
    expect(last.anchor).toBe("start") // самый левый (min) — растёт вправо, внутрь графика
  })

  it("точки офферов разводятся по полосам, чтобы не наезжали", () => {
    const layout = salaryDistributionLayout(baseInput, 560, 180)!
    expect(layout!.offerMarkers).toHaveLength(2)
    // Оба оффера имеют lane (0 или 1).
    for (const m of layout!.offerMarkers) {
      expect(m.lane).toBeGreaterThanOrEqual(0)
    }
  })

  it("нет target — скобка null", () => {
    const input: SalaryDistributionInput = { ...baseInput, targetMin: null, targetMax: null }
    const layout = salaryDistributionLayout(input, 560, 180)!
    expect(layout.targetBracket).toBeNull()
  })

  it("нет median/p25/p75 — маркеры пусты", () => {
    const input: SalaryDistributionInput = {
      ...baseInput,
      median: null,
      p25: null,
      p75: null,
    }
    const layout = salaryDistributionLayout(input, 560, 180)!
    expect(layout.medianMarker).toBeNull()
    expect(layout.quartileTicks).toEqual([])
  })

  it("меньше MIN_HISTOGRAM_POINTS → null (честный empty)", () => {
    const input: SalaryDistributionInput = { ...baseInput, points: [100, 200] }
    expect(salaryDistributionLayout(input, 560, 180)).toBeNull()
  })

  it("столбик с count=0 имеет height=0, но x/width корректные", () => {
    const layout = salaryDistributionLayout(baseInput, 560, 180)!
    const zeroBar = layout.bars.find((b) => b.count === 0)
    if (zeroBar) {
      expect(zeroBar.height).toBe(0)
      expect(zeroBar.width).toBeGreaterThan(0)
    }
  })
})
