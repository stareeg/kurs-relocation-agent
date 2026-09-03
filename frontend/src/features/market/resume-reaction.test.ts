import { describe, expect, it } from "vitest"
import {
  buildResumeReactionMetrics,
  filterResumeReactionBySource,
  formatSnapshotDate,
  GETMATCH_PROFILE_RESUME_ID,
  lineChartInputFromPoints,
  pickResumeReactionSource,
  RESUME_REACTION_METRIC_KEYS,
} from "./resume-reaction"

const hhPoints = [
  {
    captured_at: "2026-07-01T10:00:00Z",
    resume_id: "hh:123",
    impressions: 4626,
    views: 36,
    invitations: 0,
  },
  {
    captured_at: "2026-07-15T10:00:00Z",
    resume_id: "hh:123",
    impressions: 4900,
    views: 41,
    invitations: 1,
  },
]

const gmPoints = [
  {
    captured_at: "2026-07-10T10:00:00Z",
    resume_id: GETMATCH_PROFILE_RESUME_ID,
    impressions: 12,
    views: 5,
    invitations: 0,
  },
]

describe("filterResumeReactionBySource", () => {
  it("разделяет hh и getmatch по resume_id, не смешивает", () => {
    const all = [...hhPoints, ...gmPoints]
    expect(filterResumeReactionBySource(all, "hh")).toHaveLength(2)
    expect(filterResumeReactionBySource(all, "getmatch")).toHaveLength(1)
  })

  it("пусто/undefined → []", () => {
    expect(filterResumeReactionBySource(null, "hh")).toEqual([])
    expect(filterResumeReactionBySource(undefined, "hh")).toEqual([])
  })
})

describe("pickResumeReactionSource", () => {
  it("hh есть данные → hh, даже если есть и getmatch", () => {
    expect(pickResumeReactionSource([...hhPoints, ...gmPoints])).toBe("hh")
  })

  it("только getmatch → getmatch", () => {
    expect(pickResumeReactionSource(gmPoints)).toBe("getmatch")
  })

  it("нет снимков → hh по умолчанию", () => {
    expect(pickResumeReactionSource([])).toBe("hh")
    expect(pickResumeReactionSource(null)).toBe("hh")
  })
})

describe("buildResumeReactionMetrics", () => {
  it("две метрики в фиксированном порядке — показы, просмотры (без приглашений, план п.6)", () => {
    const metrics = buildResumeReactionMetrics(hhPoints)
    expect(metrics.map((m) => m.key)).toEqual(RESUME_REACTION_METRIC_KEYS)
    expect(metrics.map((m) => m.label)).toEqual(["показы", "просмотры"])
  })

  it("каждая метрика — свой ряд точек, независимый от других (план §0: не одна ось)", () => {
    const metrics = buildResumeReactionMetrics(hhPoints)
    const impressions = metrics.find((m) => m.key === "impressions")!
    const views = metrics.find((m) => m.key === "views")!
    expect(impressions.points).toEqual([
      { x: 0, y: 4626 },
      { x: 1, y: 4900 },
    ])
    expect(views.points).toEqual([
      { x: 0, y: 36 },
      { x: 1, y: 41 },
    ])
  })

  it("несёт дни снимков в том же порядке, что и точки", () => {
    const metrics = buildResumeReactionMetrics(hhPoints)
    expect(metrics[0]!.days).toEqual(["2026-07-01", "2026-07-15"])
  })

  it("сортирует по дате перед построением ряда", () => {
    const shuffled = [hhPoints[1]!, hhPoints[0]!]
    const metrics = buildResumeReactionMetrics(shuffled)
    const impressions = metrics.find((m) => m.key === "impressions")!
    expect(impressions.points.map((p) => p.y)).toEqual([4626, 4900])
  })

  it("latest — последняя точка, delta — последняя минус первая", () => {
    const metrics = buildResumeReactionMetrics(hhPoints)
    const views = metrics.find((m) => m.key === "views")!
    expect(views.latest).toBe(41)
    expect(views.delta).toBe(5)
  })

  it("меньше двух точек → delta не считается (не соврать про тренд)", () => {
    const metrics = buildResumeReactionMetrics([hhPoints[0]!])
    expect(metrics[0]!.latest).toBe(4626)
    expect(metrics[0]!.delta).toBeNull()
  })

  it("нет точек → пустые ряды, latest/delta null", () => {
    const metrics = buildResumeReactionMetrics([])
    for (const m of metrics) {
      expect(m.points).toEqual([])
      expect(m.latest).toBeNull()
      expect(m.delta).toBeNull()
    }
  })

  it("отрицательные/битые значения не уходят в минус", () => {
    const metrics = buildResumeReactionMetrics([
      { captured_at: "2026-07-01T10:00:00Z", impressions: -5, views: Number.NaN, invitations: 2 },
    ])
    expect(metrics.find((m) => m.key === "impressions")!.points[0]!.y).toBe(0)
    expect(metrics.find((m) => m.key === "views")!.points[0]!.y).toBe(0)
  })
})

describe("formatSnapshotDate", () => {
  it("пусто → null", () => {
    expect(formatSnapshotDate(null)).toBeNull()
    expect(formatSnapshotDate(undefined)).toBeNull()
    expect(formatSnapshotDate("не дата")).toBeNull()
  })

  it("форматирует день/месяц/время", () => {
    const label = formatSnapshotDate("2026-07-15T10:30:00Z")
    expect(label).toMatch(/июл/i)
  })
})

describe("lineChartInputFromPoints", () => {
  it("две метрики в порядке показы → просмотры", () => {
    const { metrics } = lineChartInputFromPoints(hhPoints)
    expect(metrics.map((m) => m.key)).toEqual(["impressions", "views"])
    expect(metrics.map((m) => m.label)).toEqual(["показы", "просмотры"])
  })

  it("каждая метрика несёт точки с обязательным x, дни, latest и delta", () => {
    const { metrics } = lineChartInputFromPoints(hhPoints)
    const impressions = metrics[0]!
    expect(impressions.points).toEqual([
      { x: 0, y: 4626 },
      { x: 1, y: 4900 },
    ])
    expect(impressions.days).toEqual(["2026-07-01", "2026-07-15"])
    expect(impressions.latest).toBe(4900)
    expect(impressions.delta).toBe(274)
  })

  it("source: hh приоритетнее getmatch", () => {
    expect(lineChartInputFromPoints([...hhPoints, ...gmPoints]).source).toBe("hh")
    expect(lineChartInputFromPoints(gmPoints).source).toBe("getmatch")
    expect(lineChartInputFromPoints([]).source).toBe("hh")
  })

  it("latestAt — последняя дата снимка по отфильтрованному источнику", () => {
    expect(lineChartInputFromPoints(hhPoints).latestAt).toBe("2026-07-15T10:00:00Z")
    expect(lineChartInputFromPoints([]).latestAt).toBeNull()
  })

  it("пусто → две метрики с пустыми рядами", () => {
    const { metrics } = lineChartInputFromPoints([])
    expect(metrics).toHaveLength(2)
    for (const m of metrics) {
      expect(m.points).toEqual([])
      expect(m.latest).toBeNull()
      expect(m.delta).toBeNull()
    }
  })

  it("getmatch-снимки фильтруются отдельно от hh", () => {
    const { metrics, source } = lineChartInputFromPoints(gmPoints)
    expect(source).toBe("getmatch")
    expect(metrics[0]!.points).toEqual([{ x: 0, y: 12 }])
  })
})
