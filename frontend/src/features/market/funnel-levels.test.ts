import { describe, expect, it } from "vitest"
import type { MarketBucket } from "@/api/market"
import { funnelBars, funnelHeaderSummary } from "./funnel-levels"

describe("funnelBars (активность за период)", () => {
  it("маппит корзины бэка 1-в-1 по порядку (Диалоги — первый столбец, база)", () => {
    // Правка 2026-08-14: бэк отдаёт Диалоги первым столбцом (база 100%), от него считаются
    // pct остальных. Финалы добавлены (раньше было 3 стадии).
    const buckets: MarketBucket[] = [
      { label: "Диалоги", count: 12, pct: 100.0 },
      { label: "Скрининги", count: 6, pct: 50.0 },
      { label: "Технички", count: 3, pct: 25.0 },
      { label: "Финалы", count: 1, pct: 8.3 },
      { label: "Офферы", count: 1, pct: 8.3 },
    ]
    const bars = funnelBars(buckets)
    expect(bars).toEqual([
      { key: "Диалоги", label: "Диалоги", value: 12, pct: 100.0 },
      { key: "Скрининги", label: "Скрининги", value: 6, pct: 50.0 },
      { key: "Технички", label: "Технички", value: 3, pct: 25.0 },
      { key: "Финалы", label: "Финалы", value: 1, pct: 8.3 },
      { key: "Офферы", label: "Офферы", value: 1, pct: 8.3 },
    ])
  })

  it("нет данных → []", () => {
    expect(funnelBars(undefined)).toEqual([])
    expect(funnelBars([])).toEqual([])
  })
})

describe("funnelHeaderSummary (строка шапки воронки)", () => {
  it("строит цепочку конверсии от Диалогов к Финалам", () => {
    const buckets: MarketBucket[] = [
      { label: "Диалоги", count: 12, pct: 100.0 },
      { label: "Скрининги", count: 6, pct: 50.0 },
      { label: "Технички", count: 3, pct: 25.0 },
      { label: "Финалы", count: 1, pct: 8.3 },
      { label: "Офферы", count: 1, pct: 8.3 },
    ]
    expect(funnelHeaderSummary(buckets)).toBe("100% Диалоги → 50% Скрининги → 25% Технички → 8% Финалы")
  })

  it("пропускает отсутствующие корзины (нет Финалов — цепочка короче)", () => {
    const buckets: MarketBucket[] = [
      { label: "Диалоги", count: 10, pct: 100.0 },
      { label: "Скрининги", count: 4, pct: 40.0 },
      { label: "Технички", count: 2, pct: 20.0 },
    ]
    expect(funnelHeaderSummary(buckets)).toBe("100% Диалоги → 40% Скрининги → 20% Технички")
  })

  it("пусто при отсутствии данных", () => {
    expect(funnelHeaderSummary(undefined)).toBe("")
    expect(funnelHeaderSummary([])).toBe("")
  })
})
