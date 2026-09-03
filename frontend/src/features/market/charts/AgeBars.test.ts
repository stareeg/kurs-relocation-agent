import { describe, expect, it } from "vitest"
import {
  AGE_BUCKET_KEYS,
  ageBarsRows,
  type AgeBarsBucket,
  type AgeBarsRow,
} from "./age-bars-geometry"

const SCREENING: AgeBarsBucket[] = [
  { key: "fresh", count: 3 },
  { key: "week2", count: 4 },
  { key: "week3", count: 2 },
  { key: "stale", count: 2 },
]

describe("ageBarsRows (V-05)", () => {
  it("пустой набор строк → []", () => {
    expect(ageBarsRows([])).toEqual([])
  })

  it("строка без вакансий (сумма корзин 0) выпадает", () => {
    const rows: AgeBarsRow[] = [{ key: "screening", label: "Скрининг", buckets: [] }]
    expect(ageBarsRows(rows)).toEqual([])
  })

  it("сумма положительных корзин — база строки", () => {
    const rows: AgeBarsRow[] = [{ key: "screening", label: "Скрининг", buckets: SCREENING }]
    const [layout] = ageBarsRows(rows)
    expect(layout!.total).toBe(11)
  })

  it("порядок сегментов — фиксированная шкала корзин, а не порядок входа", () => {
    const shuffled: AgeBarsBucket[] = [
      { key: "stale", count: 2 },
      { key: "fresh", count: 3 },
      { key: "week3", count: 2 },
      { key: "week2", count: 4 },
    ]
    const [layout] = ageBarsRows([{ key: "s", label: "S", buckets: shuffled }])
    expect(layout!.segments.map((s) => s.key)).toEqual(["fresh", "week2", "week3", "stale"])
  })

  it("ширина сегмента ∝ count/total; сегменты идут подряд без разрывов", () => {
    const [layout] = ageBarsRows([{ key: "s", label: "S", buckets: SCREENING }])
    const segs = layout!.segments
    expect(segs[0]!.xPct).toBeCloseTo(0)
    expect(segs[0]!.widthPct).toBeCloseTo((3 / 11) * 100)
    expect(segs[1]!.xPct).toBeCloseTo(segs[0]!.widthPct)
    expect(segs[1]!.widthPct).toBeCloseTo((4 / 11) * 100)
  })

  it("rampIndex — индекс корзины в фиксированной шкале (0 = свежее, 3 = залежалее)", () => {
    const [layout] = ageBarsRows([{ key: "s", label: "S", buckets: SCREENING }])
    expect(layout!.segments.map((s) => s.rampIndex)).toEqual([0, 1, 2, 3])
  })

  it("корзины с count <= 0 не занимают места и выпадают", () => {
    const buckets: AgeBarsBucket[] = [
      { key: "fresh", count: 5 },
      { key: "week2", count: 0 },
      { key: "week3", count: -3 },
      { key: "stale", count: 5 },
    ]
    const [layout] = ageBarsRows([{ key: "s", label: "S", buckets }])
    expect(layout!.segments.map((s) => s.key)).toEqual(["fresh", "stale"])
    expect(layout!.total).toBe(10)
  })

  it("пропущенный в данных ключ корзины считается нулём", () => {
    const buckets: AgeBarsBucket[] = [
      { key: "fresh", count: 5 },
      { key: "stale", count: 5 },
    ]
    const [layout] = ageBarsRows([{ key: "s", label: "S", buckets }])
    expect(layout!.segments.map((s) => s.key)).toEqual(["fresh", "stale"])
  })

  it("несколько строк — каждая нормирована на свою базу, пустые выпадают", () => {
    const rows: AgeBarsRow[] = [
      { key: "screening", label: "Скрининг", buckets: SCREENING },
      { key: "tech", label: "Техничка", buckets: [] },
      {
        key: "final",
        label: "Финал",
        buckets: [
          { key: "fresh", count: 1 },
          { key: "stale", count: 1 },
        ],
      },
    ]
    const layout = ageBarsRows(rows)
    expect(layout.map((r) => r.key)).toEqual(["screening", "final"])
    expect(layout[1]!.total).toBe(2)
    expect(layout[1]!.segments.map((s) => s.widthPct)).toEqual([50, 50])
  })

  it("покрывает все ключи фиксированной шкалы", () => {
    expect(AGE_BUCKET_KEYS).toEqual(["fresh", "week2", "week3", "stale"])
  })
})
