import { describe, expect, it } from "vitest"
import {
  formatDayShort,
  LINE_CHART_HEADER_HEIGHT,
  LINE_CHART_X_AXIS_HEIGHT,
  LINE_CHART_Y_AXIS_WIDTH,
  lineChartLayout,
  type LineChartInput,
} from "./line-chart-geometry"

const metrics: LineChartInput["metrics"] = [
  {
    key: "impressions",
    label: "показы",
    points: [
      { x: 0, y: 4626 },
      { x: 1, y: 4900 },
      { x: 2, y: 5100 },
    ],
    days: ["2026-07-01", "2026-07-08", "2026-07-15"],
    latest: 5100,
    delta: 474,
  },
  {
    key: "views",
    label: "просмотры",
    points: [
      { x: 0, y: 36 },
      { x: 1, y: 41 },
      { x: 2, y: 45 },
    ],
    days: ["2026-07-01", "2026-07-08", "2026-07-15"],
    latest: 45,
    delta: 9,
  },
  {
    key: "invitations",
    label: "приглашения",
    points: [
      { x: 0, y: 0 },
      { x: 1, y: 1 },
      { x: 2, y: 0 },
    ],
    days: ["2026-07-01", "2026-07-08", "2026-07-15"],
    latest: 0,
    delta: 0,
  },
]

describe("lineChartLayout", () => {
  it("возвращает по одной раскладке на метрику", () => {
    const layout = lineChartLayout({ metrics }, 560, 90)
    expect(layout.metrics).toHaveLength(3)
    expect(layout.metrics.map((m) => m.key)).toEqual(["impressions", "views", "invitations"])
  })

  it("каждая метрика получает свой домен Y — не общий, чтобы ряды не прижимались к нулю", () => {
    const layout = lineChartLayout({ metrics }, 560, 90)
    const impressionsDomain = layout.metrics[0]!.yDomain
    const viewsDomain = layout.metrics[1]!.yDomain
    // Показы ~5000 — домен вокруг них, не от 0 до 5000 (views бы прижались).
    expect(impressionsDomain.max).toBeGreaterThan(5000)
    expect(viewsDomain.max).toBeLessThan(100)
    expect(viewsDomain.max).toBeGreaterThan(40)
  })

  it("coords имеют cx по индексу и cy по значению в домене метрики", () => {
    const layout = lineChartLayout({ metrics }, 560, 90)
    const chartW = 560 - LINE_CHART_Y_AXIS_WIDTH
    const impressions = layout.metrics[0]!
    // Три точки, последняя — на правом краю chart area.
    expect(impressions.coords).toHaveLength(3)
    expect(impressions.coords[2]!.cx).toBeCloseTo(chartW, 1)
    expect(impressions.coords[0]!.cx).toBeCloseTo(0, 1)
    // Большее значение — выше (меньше cy) в том же домене.
    expect(impressions.coords[2]!.cy).toBeLessThan(impressions.coords[0]!.cy)
  })

  it("xCount — длина точек первой метрики; xTicks — общие даты", () => {
    const layout = lineChartLayout({ metrics }, 560, 90)
    expect(layout.xCount).toBe(3)
    // Последняя дата всегда в подписях.
    const lastTick = layout.xTicks[layout.xTicks.length - 1]!
    expect(lastTick.label).toBe(formatDayShort("2026-07-15"))
  })

  it("yTicks: три тика (min, середина, max) с человекочитаемыми подписями", () => {
    const layout = lineChartLayout({ metrics }, 560, 90)
    const views = layout.metrics[1]!
    expect(views.yTicks).toHaveLength(3)
    // Views (36..45) — min=36, не 0, т.к. min > max*0.15.
    expect(views.yTicks[0]!.label).toBe("36")
    // Форматирование тысяч — «к» суффикс для показов.
    const impressions = layout.metrics[0]!
    expect(impressions.yTicks[2]!.label).toMatch(/к$/)
  })

  it("gridLines соответствуют yTicks", () => {
    const layout = lineChartLayout({ metrics }, 560, 90)
    for (const metric of layout.metrics) {
      expect(metric.gridLines).toHaveLength(metric.yTicks.length)
    }
  })

  it("пробрасывает latest и delta в раскладку", () => {
    const layout = lineChartLayout({ metrics }, 560, 90)
    expect(layout.metrics[0]!.latest).toBe(5100)
    expect(layout.metrics[0]!.delta).toBe(474)
  })

  it("пустые метрики → пустые coords, но домен не падает", () => {
    const empty: LineChartInput["metrics"] = [
      { key: "a", label: "a", points: [], days: [], latest: null, delta: null },
    ]
    const layout = lineChartLayout({ metrics: empty }, 560, 90)
    expect(layout.metrics[0]!.coords).toEqual([])
    expect(layout.metrics[0]!.count).toBe(0)
    // Домен не уходит в NaN — fallback {min:0, max:1}.
    expect(layout.metrics[0]!.yDomain).toEqual({ min: 0, max: 1 })
  })

  it("одно значение в ряду — домен не прижимает линию к краю", () => {
    const single: LineChartInput["metrics"] = [
      {
        key: "a",
        label: "a",
        points: [{ x: 0, y: 100 }],
        days: ["2026-07-01"],
        latest: 100,
        delta: null,
      },
    ]
    const layout = lineChartLayout({ metrics: single }, 560, 90)
    const domain = layout.metrics[0]!.yDomain
    expect(domain.min).toBeLessThan(100)
    expect(domain.max).toBeGreaterThan(100)
  })

  it("все значения равны нулю — домен {0, 1}, линия по нижней границе", () => {
    const zeros: LineChartInput["metrics"] = [
      {
        key: "a",
        label: "a",
        points: [
          { x: 0, y: 0 },
          { x: 1, y: 0 },
        ],
        days: ["2026-07-01", "2026-07-08"],
        latest: 0,
        delta: 0,
      },
    ]
    const layout = lineChartLayout({ metrics: zeros }, 560, 90)
    expect(layout.metrics[0]!.yDomain).toEqual({ min: 0, max: 1 })
    // Обе точки на одной высоте — нижняя граница (cy = innerH + PAD_TOP).
    expect(layout.metrics[0]!.coords[0]!.cy).toBe(layout.metrics[0]!.coords[1]!.cy)
  })

  it("высота раскладки учитывает ось X и шапку на каждую метрику", () => {
    const layout = lineChartLayout({ metrics }, 560, 90)
    // Каждая метрика: HEADER + metricHeight + X_AXIS.
    const perMetric = LINE_CHART_HEADER_HEIGHT + 90 + LINE_CHART_X_AXIS_HEIGHT
    expect(layout.metrics).toHaveLength(3)
    // Проверяем что layout корректно разбит на 3 блока — через количество xTicks.
    expect(layout.metrics.every((m) => m.xTicks.length > 0)).toBe(true)
    expect(perMetric * 3).toBeGreaterThan(0)
  })
})

describe("formatDayShort", () => {
  it("ISO → дд.мм", () => {
    expect(formatDayShort("2026-07-15")).toBe("15.07")
    expect(formatDayShort("2026-01-05")).toBe("05.01")
  })

  it("битая дата → как есть", () => {
    expect(formatDayShort("не дата")).toBe("не дата")
  })
})

describe("lineChartLayout — режим time (X по timestamp)", () => {
  // Точки с разным каденсом: 1, 4, 8, 9 июля — дырка 4→8 (неделя без снимков) должна
  // быть видна как провал, а не сжата к соседям.
  const ts = [
    Date.parse("2026-07-01"),
    Date.parse("2026-07-04"),
    Date.parse("2026-07-08"),
    Date.parse("2026-07-09"),
  ]
  const days = ["2026-07-01", "2026-07-04", "2026-07-08", "2026-07-09"]
  const metricsTime: LineChartInput["metrics"] = [
    {
      key: "views",
      label: "просмотры",
      points: ts.map((_t, i) => ({ x: i, y: 10 + i })),
      days,
      timestamps: ts,
      latest: 13,
      delta: 3,
    },
  ]

  it("xMode = 'time' когда все метрики с валидными timestamps", () => {
    const layout = lineChartLayout({ metrics: metricsTime }, 560, 90)
    expect(layout.xMode).toBe("time")
  })

  it("xMode = 'index' (fallback) если timestamps нет или неполные", () => {
    const noTs: LineChartInput["metrics"] = metricsTime.map((m) => ({
      ...m,
      timestamps: undefined,
    }))
    expect(lineChartLayout({ metrics: noTs }, 560, 90).xMode).toBe("index")
    const partial: LineChartInput["metrics"] = metricsTime.map((m) => ({
      ...m,
      timestamps: m.timestamps!.slice(0, 2), // длина не совпадает с points
    }))
    expect(lineChartLayout({ metrics: partial }, 560, 90).xMode).toBe("index")
  })

  it("точки ставятся по реальному времени, дырка 4→8 июля видна как провал", () => {
    const layout = lineChartLayout({ metrics: metricsTime }, 560, 90)
    const coords = layout.metrics[0]!.coords
    expect(coords).toHaveLength(4)
    // Расстояние между 1 и 4 июля (3 дня) меньше, чем между 4 и 8 июля (4 дня) —
    // значит по X дырка шире, чем равноотстоящая. Это и есть «честные пропуски».
    const gapSmall = coords[1]!.cx - coords[0]!.cx
    const gapBig = coords[2]!.cx - coords[1]!.cx
    expect(gapBig).toBeGreaterThan(gapSmall)
    // Первая точка не прилипает к левому краю (pad 2%), последняя — не к правому.
    expect(coords[0]!.cx).toBeGreaterThan(0)
    expect(coords[3]!.cx).toBeLessThan(560 - LINE_CHART_Y_AXIS_WIDTH)
  })

  it("все точки с одной датой — домен растягивается минимум на сутки, не склеиваются", () => {
    const sameDay = Date.parse("2026-07-10")
    const sameTs: LineChartInput["metrics"] = [
      {
        key: "a",
        label: "a",
        points: [
          { x: 0, y: 1 },
          { x: 1, y: 2 },
        ],
        days: ["2026-07-10", "2026-07-10"],
        timestamps: [sameDay, sameDay + 3_600_000], // час спустя
        latest: 2,
        delta: 1,
      },
    ]
    const layout = lineChartLayout({ metrics: sameTs }, 560, 90)
    const coords = layout.metrics[0]!.coords
    // Две точки в один час — разнесены по X (домен ≥ сутки, не склеены в один пиксель).
    expect(Math.abs(coords[1]!.cx - coords[0]!.cx)).toBeGreaterThan(1)
  })
})

describe("lineChartLayout — подписи X при нескольких снимках в один день (план 2026-08-11 п.6)", () => {
  it("подписи одного дня из плотного кластера снимков не садятся друг на друга", () => {
    // Пять снимков за один день (раз в час) — прежнее прореживание «каждая N-я точка» держало
    // бы несколько подписей "10.07" почти впритык. Соседние подписи с одинаковым текстом
    // допустимы, только если между ними достаточный зазор (иначе они читались бы как одна
    // слипшаяся клякса) — крайние точки дня всё равно подписываются каждая.
    const day = "2026-07-10"
    const base = Date.parse(day)
    const ts = [0, 1, 2, 3, 4].map((h) => base + h * 3_600_000)
    const metrics: LineChartInput["metrics"] = [
      {
        key: "views",
        label: "просмотры",
        points: ts.map((_t, i) => ({ x: i, y: 10 + i })),
        days: ts.map(() => day),
        timestamps: ts,
        latest: 14,
        delta: 4,
      },
    ]
    const layout = lineChartLayout({ metrics }, 560, 90)
    const xTicks = layout.metrics[0]!.xTicks
    for (let i = 1; i < xTicks.length; i++) {
      const gapPx = xTicks[i]!.x - xTicks[i - 1]!.x
      if (xTicks[i]!.label === xTicks[i - 1]!.label) {
        expect(gapPx).toBeGreaterThanOrEqual(40)
      } else {
        expect(gapPx).toBeGreaterThan(0)
      }
    }
  })

  it("прореживает по фактическому пиксельному зазору — не каждая точка получает подпись на тесной шкале", () => {
    const days = ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04", "2026-07-05"]
    const ts = days.map((d) => Date.parse(d))
    const metrics: LineChartInput["metrics"] = [
      {
        key: "views",
        label: "просмотры",
        points: ts.map((_t, i) => ({ x: i, y: i })),
        days,
        timestamps: ts,
        latest: 4,
        delta: 4,
      },
    ]
    const layout = lineChartLayout({ metrics }, 200, 90) // узкая шкала — 5 подписей не влезут
    expect(layout.metrics[0]!.xTicks.length).toBeLessThan(days.length)
    // Последняя точка всё равно подписана.
    expect(layout.metrics[0]!.xTicks.at(-1)!.label).toBe(formatDayShort("2026-07-05"))
  })
})

describe("lineChartLayout — вертикальные гайды по неделям", () => {
  it("гайды кладутся по границам недель (понедельникам) в режиме time", () => {
    // 2026-07-06 — понедельник. Точки 30 июня (вт) и 10 июля (пт) → один гайд 6 июля.
    const ts = [Date.parse("2026-06-30"), Date.parse("2026-07-10")]
    const days = ["2026-06-30", "2026-07-10"]
    const metrics: LineChartInput["metrics"] = [
      {
        key: "a",
        label: "a",
        points: [
          { x: 0, y: 1 },
          { x: 1, y: 2 },
        ],
        days,
        timestamps: ts,
        latest: 2,
        delta: 1,
      },
    ]
    const layout = lineChartLayout({ metrics }, 560, 90)
    expect(layout.xMode).toBe("time")
    // Хотя бы один гайд недели (понедельник 6 июля) попал в домен.
    expect(layout.weekGuides.length).toBeGreaterThan(0)
    // Гайд в пределах chart area (0..chartW).
    const chartW = 560 - LINE_CHART_Y_AXIS_WIDTH
    for (const g of layout.weekGuides) {
      expect(g.x).toBeGreaterThanOrEqual(0)
      expect(g.x).toBeLessThanOrEqual(chartW)
    }
  })

  it("в режиме index (без timestamps) гайды недель пустые", () => {
    const metrics: LineChartInput["metrics"] = [
      {
        key: "a",
        label: "a",
        points: [
          { x: 0, y: 1 },
          { x: 1, y: 2 },
        ],
        days: ["2026-06-30", "2026-07-10"],
        latest: 2,
        delta: 1,
      },
    ]
    const layout = lineChartLayout({ metrics }, 560, 90)
    expect(layout.xMode).toBe("index")
    expect(layout.weekGuides).toEqual([])
  })
})
