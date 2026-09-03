import { describe, expect, it } from "vitest"
import type { OfferChanceComponent } from "@/api/market"
import { offerChanceFactorBars, offerChanceFactorTooltipValue } from "./offer-chance"

const SAMPLE: OfferChanceComponent[] = [
  { key: "funnel", label: "Воронка", score: 0.6, weight: 0.25, contribution: 15 },
  { key: "skill", label: "Скиллы", score: 0.73, weight: 0.25, contribution: 18.3 },
  { key: "resume_quality", label: "Качество резюме", score: 0.36, weight: 0.15, contribution: 5.4 },
  { key: "market", label: "Рынок под вас", score: 0.5, weight: 0.15, contribution: 7.5 },
  { key: "applications", label: "Отклики", score: 0.4, weight: 0.08, contribution: 3.2 },
  { key: "activity", label: "Активность", score: 0.5, weight: 0.07, contribution: 3.5 },
  { key: "depth", label: "Этапы", score: 0.8, weight: 0.05, contribution: 4 },
]

describe("offerChanceFactorTooltipValue", () => {
  it("тройная подпись: суб-балл · вес · вклад", () => {
    expect(offerChanceFactorTooltipValue(SAMPLE[0]!)).toBe("60/100 · вес 25% · вклад 15 в итог")
    expect(offerChanceFactorTooltipValue(SAMPLE[2]!)).toBe("36/100 · вес 15% · вклад 5 в итог")
  })
})

describe("offerChanceFactorBars (гистограмма суб-баллов)", () => {
  it("каждый фактор с бэка — отдельный столбец, value = суб-балл (score*100), порядок как с бэка", () => {
    const bars = offerChanceFactorBars(SAMPLE)
    expect(bars).toHaveLength(SAMPLE.length)
    expect(bars.map((b) => b.key)).toEqual(SAMPLE.map((c) => c.key))
    expect(bars.map((b) => b.value)).toEqual([60, 73, 36, 50, 40, 50, 80])
  })

  it("подписи короткие, некоторые термины укорочены (план 2026-08-11 п.3)", () => {
    const bars = offerChanceFactorBars(SAMPLE)
    expect(bars[0]!.label).toBe("Воронка") // не в списке коротких — как с бэка
    expect(bars[1]!.label).toBe("Скиллы") // не в списке коротких
    expect(bars[2]!.label).toBe("Резюме") // было «Качество резюме»
    expect(bars[3]!.label).toBe("Рынок") // было «Рынок под вас»
    expect(bars[5]!.label).toBe("Общение") // было «Активность»
    expect(bars[6]!.label).toBe("Этапы") // было «Портфель» (правка 2026-08-14)
    expect(bars[0]!.label).not.toMatch(/повышают|ответы HR/i)
  })

  it("вклад в итог — числом в верхе столбца (inBarLabel), вес — в низу (bottomInBarLabel)", () => {
    // Правка 2026-08-14: верх столбца — «N балл/балла/баллов» (вклад), низ — «N%» (вес).
    const bars = offerChanceFactorBars(SAMPLE)
    expect(bars[0]!.inBarLabel).toBe("15 баллов")
    expect(bars[0]!.bottomInBarLabel).toBe("25%")
    expect(bars[6]!.inBarLabel).toBe("4 балла")
    expect(bars[6]!.bottomInBarLabel).toBe("5%")
  })

  it("склонение «балл/балла/баллов» по числу", () => {
    const bars = offerChanceFactorBars([
      { key: "a", label: "A", score: 0.5, weight: 0.1, contribution: 1 },
      { key: "b", label: "B", score: 0.5, weight: 0.1, contribution: 3 },
      { key: "c", label: "C", score: 0.5, weight: 0.1, contribution: 5 },
      { key: "d", label: "D", score: 0.5, weight: 0.1, contribution: 11 },
    ])
    expect(bars[0]!.inBarLabel).toBe("1 балл")
    expect(bars[1]!.inBarLabel).toBe("3 балла")
    expect(bars[2]!.inBarLabel).toBe("5 баллов")
    expect(bars[3]!.inBarLabel).toBe("11 баллов")
  })

  it("пустой набор → []", () => {
    expect(offerChanceFactorBars([])).toEqual([])
  })

  it("отрицательный суб-балл клиппится в 0 (не уходит ниже оси)", () => {
    const bars = offerChanceFactorBars([
      { key: "funnel", label: "Воронка", score: -0.05, weight: 0.25, contribution: 0 },
    ])
    expect(bars[0]!.value).toBe(0)
  })
})
