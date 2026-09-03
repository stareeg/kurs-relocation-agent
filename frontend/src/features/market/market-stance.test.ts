import { describe, expect, it } from "vitest"
import type { LiveOfferPoint, MarketBucket, MarketSupplyFacts } from "@/api/market"
import {
  formatMoney,
  formatMoneyShort,
  gradeLevelBars,
  roleNicheBars,
  salaryDistributionInput,
  workFormatBars,
} from "./market-stance"

describe("formatMoney", () => {
  it("тысячи разделены обычным пробелом, не NBSP", () => {
    expect(formatMoney(374000)).toBe("374 000 ₽")
    expect(formatMoney(374000)).not.toMatch(/\u00A0/)
  })

  it("округляет дробные", () => {
    expect(formatMoney(374000.6)).toBe("374 001 ₽")
  })
})

describe("formatMoneyShort", () => {
  it("540 000 → 540к", () => expect(formatMoneyShort(540000)).toBe("540к"))
  it("округляет до тысяч", () => expect(formatMoneyShort(374499)).toBe("374к"))
})

describe("salaryDistributionInput", () => {
  const supply: MarketSupplyFacts = {
    available: true,
    window_days: 30,
    measured: 36,
    work_formats: [],
    salary_measured: 30,
    salary_median_net: 400000,
    salary_min_net: 250000,
    salary_max_net: 600000,
    salary_p25_net: 350000,
    salary_p75_net: 480000,
    salary_points: [300000, 350000, 400000, 450000, 500000],
    target_min_net: 374000,
    target_max_net: 450000,
  }
  const offers: LiveOfferPoint[] = [
    { company: "Сбер", position: "", monthly_net: 540000 },
    { company: "ПОСК", position: "", monthly_net: 450000 },
  ]

  it("пробрасывает points, target, median, квартили и офферы", () => {
    const input = salaryDistributionInput(supply, offers)
    expect(input.points).toEqual([300000, 350000, 400000, 450000, 500000])
    expect(input.targetMin).toBe(374000)
    expect(input.targetMax).toBe(450000)
    expect(input.median).toBe(400000)
    expect(input.p25).toBe(350000)
    expect(input.p75).toBe(480000)
    expect(input.offers).toHaveLength(2)
    expect(input.offers[0]!.company).toBe("Сбер")
    expect(input.offers[0]!.value).toBe(540000)
  })

  it("недоступный supply → пустые points, но target остаётся", () => {
    const empty: MarketSupplyFacts = {
      ...supply,
      available: false,
      salary_points: [],
      salary_median_net: null,
      salary_p25_net: null,
      salary_p75_net: null,
    }
    const input = salaryDistributionInput(empty, offers)
    expect(input.points).toEqual([])
    expect(input.median).toBeNull()
    expect(input.targetMin).toBe(374000) // зона цели не гасится вместе с остальным
  })
})

describe("workFormatBars (гистограмма форматов)", () => {
  it("пусто → []", () => {
    expect(workFormatBars([])).toEqual([])
    expect(workFormatBars(null)).toEqual([])
  })

  it("строит короткие подписи «Удалённо / Гибрид / Офис», не «удалённо · 67%»", () => {
    const formats: MarketBucket[] = [
      { label: "удалённо", count: 20, pct: 66.7 },
      { label: "гибрид", count: 6, pct: 20.0 },
      { label: "офис", count: 4, pct: 13.3 },
    ]
    const bars = workFormatBars(formats)
    expect(bars).toHaveLength(3)
    expect(bars.map((b) => b.label)).toEqual(["Удалённо", "Гибрид", "Офис"])
    expect(bars.map((b) => b.value)).toEqual([20, 6, 4])
    // Без наезжающих «· %» подписей сегментов — доля видна на оси/тултипе.
    expect(bars[0]!.label).not.toMatch(/·\s*\d/)
  })

  it("английские ключи remote/hybrid/office → те же подписи", () => {
    const formats: MarketBucket[] = [
      { label: "remote", count: 10, pct: 50 },
      { label: "hybrid", count: 5, pct: 25 },
      { label: "office", count: 5, pct: 25 },
    ]
    const bars = workFormatBars(formats)
    expect(bars.map((b) => b.label)).toEqual(["Удалённо", "Гибрид", "Офис"])
  })

  it("незнакомая метка — с заглавной буквы", () => {
    const formats: MarketBucket[] = [{ label: "надом", count: 1, pct: 100 }]
    expect(workFormatBars(formats)[0]!.label).toBe("Надом")
  })
})

describe("gradeLevelBars", () => {
  it("пусто → []", () => {
    expect(gradeLevelBars(undefined)).toEqual([])
    expect(gradeLevelBars([])).toEqual([])
  })

  it("подписи с бэка идут как есть (уже короткие), pct пробрасывается (правка 2026-08-14)", () => {
    const levels: MarketBucket[] = [
      { label: "Senior", count: 5, pct: 71.4 },
      { label: "Lead", count: 2, pct: 28.6 },
    ]
    expect(gradeLevelBars(levels)).toEqual([
      { key: "Senior", label: "Senior", value: 5, pct: 71.4 },
      { key: "Lead", label: "Lead", value: 2, pct: 28.6 },
    ])
  })
})

describe("roleNicheBars", () => {
  it("пусто → []", () => {
    expect(roleNicheBars(undefined)).toEqual([])
    expect(roleNicheBars([])).toEqual([])
  })

  it("усекает до 5 для мини-колонки, порядок сохранён", () => {
    const niches: MarketBucket[] = Array.from({ length: 8 }, (_, i) => ({
      label: `Ниша ${i}`,
      count: 8 - i,
      pct: 0,
    }))
    const bars = roleNicheBars(niches)
    expect(bars).toHaveLength(5)
    expect(bars.map((b) => b.label)).toEqual(["Ниша 0", "Ниша 1", "Ниша 2", "Ниша 3", "Ниша 4"])
  })
})
