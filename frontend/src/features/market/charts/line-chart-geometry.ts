/**
 * Геометрия линейного графика для «Отклика рынка»: три метрики (показы / просмотры /
 * приглашения), каждая на своей шкале, с настоящими осями X (даты снимков) и Y
 * (значения), сеткой и тултипом по визиру. Чистая раскладка — без React, тестируется
 * отдельно от `LineChart.tsx`.
 *
 * Каждая метрика рисуется отдельным графиком со своим доменом Y — старая форма трёх
 * рядов на общей оси прижимала два ряда к нулю (план §0). Общий домен X — даты снимков —
 * выровнен между графиками, чтобы сравнивать провалы/всплески в одних и тех же точках.
 */
export type LinePoint = { x: number; y: number }

export type LineMetricInput = {
  key: string
  label: string
  points: LinePoint[]
  /** Дни снимков `YYYY-MM-DD`, тот же порядок и длина, что и `points`. */
  days: string[]
  /**
   * Опционально: ms-таймстампы точек (тот же порядок и длина, что и `points`/`days`).
   * Если заданы у всех метрик — X-ось строится по реальному времени, а не по индексу
   * точки. Это убирает «равноотстоящие точки» и корректно показывает пропуски: когда
   * hh не открывали неделю — дырка в показах, а не сжатие к соседям. Режим 'index'
   * (без `timestamps`) оставлен для обратной совместимости со старыми тестами.
   */
  timestamps?: number[]
  /** Последнее значение и дельта за окно — для подписи в шапке графика. */
  latest: number | null
  delta: number | null
}

export type LineChartInput = {
  metrics: LineMetricInput[]
}

export type LineCoord = { cx: number; cy: number }

export type LineYDomain = { min: number; max: number }

export type LineXTick = {
  x: number
  /** Подпись даты снимка. */
  label: string
}

export type LineYTick = {
  y: number
  label: string
}

export type LineMetricLayout = {
  key: string
  label: string
  coords: LineCoord[]
  yDomain: LineYDomain
  yTicks: LineYTick[]
  xTicks: LineXTick[]
  gridLines: { y: number }[]
  latest: number | null
  delta: number | null
  /** Длина точек — дублирует `coords.length`, чтобы не таскать массив ради длины. */
  count: number
}

export type LineChartLayout = {
  metrics: LineMetricLayout[]
  /** Общий домен X (индексы точек 0..n-1) — одинаковый для всех метрик. */
  xCount: number
  /** Общие подписи дат — одинаковые для всех метрик. */
  xTicks: LineXTick[]
  /** Вертикальные гайды по границам недель — общие для всех панелей, рисуются в каждой. */
  weekGuides: { x: number }[]
  /** Режим X-оси: 'time' если у всех метрик есть валидные timestamps, иначе 'index'. */
  xMode: "time" | "index"
}

// Правка 2026-08-11 (план п.6, «мелкие цифры на оси»): ось Y была рассчитана под 10px-подписи —
// расширена под увеличенный шрифт тиков (`LineChart.tsx`: text-[10px] → text-xs).
const Y_AXIS_WIDTH = 50
const X_AXIS_HEIGHT = 18
// Последнее значение/дельта переехали в шапку блока (`MarketSection` meta) — здесь остаётся
// только небольшой зазор над графиком метрики (и между метриками при нескольких рядах).
const HEADER_HEIGHT = 10
const PAD_TOP = 8
const PAD_BOTTOM = 4
/** Шаг между подписями дат на оси X — чтобы не сливались при ~30 точках. */
const X_TICK_MIN_STEP = 4
/** Минимальный зазор в px между соседними подписями дат в режиме `time` — несколько снимков
 * в один день не должны печатать одну и ту же дату впритык друг к другу. */
const MIN_TIME_TICK_GAP_PX = 44

function niceNumberDomain(values: readonly number[]): LineYDomain {
  if (values.length === 0) return { min: 0, max: 1 }
  const min = Math.min(...values)
  const max = Math.max(...values)
  if (min === max) {
    // Одна точка на оси — даём ей воздух сверху и снизу, не прижимаем к краю.
    if (min === 0) return { min: 0, max: 1 }
    return { min: Math.min(0, min * 0.8), max: min * 1.2 }
  }
  // Всегда от 0, если минимум близок к нулю — иначе режем от фактического min
  // (показы ~5000, просмотры ~40 — у каждой шкалы свой честный масштаб).
  const lo = min > 0 && min < max * 0.15 ? 0 : min
  const span = max - lo
  // Паддинг 8% сверху, чтобы линия не прилипала к верхней рамке.
  return { min: lo, max: max + span * 0.08 }
}

function formatYTick(value: number): string {
  if (value >= 1000) {
    return `${(value / 1000).toLocaleString("ru-RU", { maximumFractionDigits: 1 })}к`
  }
  return String(Math.round(value))
}

/** Человекочитаемая подпись даты из ISO-строки `YYYY-MM-DD` → `дд.мм`. */
export function formatDayShort(iso: string): string {
  const ms = Date.parse(iso)
  if (!Number.isFinite(ms)) return iso
  const d = new Date(ms)
  const dd = String(d.getDate()).padStart(2, "0")
  const mm = String(d.getMonth() + 1).padStart(2, "0")
  return `${dd}.${mm}`
}

function buildYTicks(domain: LineYDomain, height: number): LineYTick[] {
  const { min, max } = domain
  // Три тика: min, середина, max — достаточно для маленького графика.
  return [
    { y: height, label: formatYTick(min) },
    { y: height / 2, label: formatYTick((min + max) / 2) },
    { y: 0, label: formatYTick(max) },
  ]
}

function buildXTicks(days: readonly string[], width: number): LineXTick[] {
  const n = days.length
  if (n === 0) return []
  const step = Math.max(1, Math.ceil(n / Math.max(1, Math.floor(width / (X_TICK_MIN_STEP * 6)))))
  const ticks: LineXTick[] = []
  for (let i = 0; i < n; i += step) {
    ticks.push({ x: i, label: formatDayShort(days[i]!) })
  }
  // Всегда подписываем последнюю точку, даже если шаг её пропустил.
  const lastIdx = n - 1
  if (ticks.length === 0 || ticks[ticks.length - 1]!.x !== lastIdx) {
    ticks.push({ x: lastIdx, label: formatDayShort(days[lastIdx]!) })
  }
  return ticks
}

/**
 * Тики X по реальному времени: точки ставятся по их timestamp, подписи — по возможности
 * каждая (или с прореживанием, если точки плотнее ~60px). Подпись — `дд.мм` снимка.
 * Граница домена берётся с запасом ~2% от span, чтобы крайние точки не прилипали к бортам.
 */
function buildXTicksByTime(
  timestamps: readonly number[],
  days: readonly string[],
  width: number,
): { xTicks: LineXTick[]; domain: { min: number; max: number } } {
  const n = timestamps.length
  if (n === 0) return { xTicks: [], domain: { min: 0, max: 1 } }
  let tMin = Infinity
  let tMax = -Infinity
  for (const t of timestamps) {
    if (Number.isFinite(t)) {
      if (t < tMin) tMin = t
      if (t > tMax) tMax = t
    }
  }
  if (!Number.isFinite(tMin) || !Number.isFinite(tMax)) {
    return { xTicks: [], domain: { min: 0, max: 1 } }
  }
  // Несколько точек в одну дату — растягиваем домен минимум на сутки, иначе они склеятся.
  if (tMax - tMin < 86_400_000) {
    const mid = (tMin + tMax) / 2
    tMin = mid - 43_200_000
    tMax = mid + 43_200_000
  }
  const span = tMax - tMin
  const pad = span * 0.02
  const domain = { min: tMin - pad, max: tMax + pad }

  // Прореживаем по фактической пиксельной позиции, не по индексу точки (правка 2026-08-11,
  // план п.6): несколько снимков в один календарный день ложатся почти в одну X-координату —
  // прежнее «каждая N-я точка» не спасало от подписей одной и той же даты впритык друг к другу.
  // Один день = одна подпись, соседние подписи не ближе `MIN_TIME_TICK_GAP_PX`; последняя точка
  // всегда подписана (даже если она попадает под оба правила прореживания).
  const xTicks: LineXTick[] = []
  let lastLabel: string | null = null
  let lastX = -Infinity
  for (let i = 0; i < n; i++) {
    if (!days[i]) continue
    const isLast = i === n - 1
    const label = formatDayShort(days[i]!)
    const x = timeToX(timestamps[i]!, domain, width)
    if (!isLast && (label === lastLabel || x - lastX < MIN_TIME_TICK_GAP_PX)) continue
    xTicks.push({ x: timestamps[i]!, label })
    lastLabel = label
    lastX = x
  }
  return { xTicks, domain }
}

/**
 * Вертикальные гайды по границам недель (полуночи понедельников по локальному времени).
 * Берём целочисленный домен [tMin, tMax] исходных точек (без pad-а), и для каждого
 * понедельника в этом диапазоне кладём гайд. Это даёт глазу временную сетку, одинаковые
 * «недели» во всех панелях, и не зависит от каденса снимков (daily / event-driven).
 */
function buildWeekGuides(
  timestamps: readonly number[],
  width: number,
  domain: { min: number; max: number },
): { x: number }[] {
  if (timestamps.length === 0) return []
  let tMin = Infinity
  let tMax = -Infinity
  for (const t of timestamps) {
    if (Number.isFinite(t)) {
      if (t < tMin) tMin = t
      if (t > tMax) tMax = t
    }
  }
  if (!Number.isFinite(tMin) || !Number.isFinite(tMax)) return []
  // Полночь понедельника, предшествующая или равная первой точке.
  const start = new Date(tMin)
  start.setHours(0, 0, 0, 0)
  // JS: 0=вс, 1=пн. Сдвигаем к началу недели (понедельнику).
  const dow = start.getDay()
  const daysSinceMon = (dow + 6) % 7
  start.setDate(start.getDate() - daysSinceMon)

  const guides: { x: number }[] = []
  const span = domain.max - domain.min
  if (span <= 0) return guides
  const cursor = new Date(start)
  // +1 день, чтобы первый гайд не прилип к левой границе, если точка уже в понедельник.
  cursor.setDate(cursor.getDate() + 7)
  while (cursor.getTime() <= tMax) {
    const t = cursor.getTime()
    if (t >= domain.min && t <= domain.max) {
      guides.push({ x: ((t - domain.min) / span) * width })
    }
    cursor.setDate(cursor.getDate() + 7)
  }
  return guides
}

function moneyToY(value: number, domain: LineYDomain, height: number): number {
  const span = domain.max - domain.min
  if (span <= 0) return height / 2
  return height - ((value - domain.min) / span) * height
}

function indexToX(index: number, count: number, width: number): number {
  if (count <= 1) return width / 2
  return (index / (count - 1)) * width
}

function timeToX(t: number, domain: { min: number; max: number }, width: number): number {
  const span = domain.max - domain.min
  if (span <= 0) return width / 2
  return ((t - domain.min) / span) * width
}

/** Все ли метрики снабжены валидными timestamps той же длины, что и points? */
function allHaveTimestamps(metrics: readonly LineMetricInput[]): boolean {
  if (metrics.length === 0) return false
  for (const m of metrics) {
    if (!m.timestamps || m.timestamps.length !== m.points.length) return false
    if (!m.timestamps.every((t) => Number.isFinite(t))) return false
  }
  return true
}

/**
 * Полная раскладка линейного графика: по одной `LineMetricLayout` на метрику.
 * `width` — ширина chart area (без отступа под ось Y слева), `metricHeight` — высота
 * одной секции метрики (без оси X и шапки).
 *
 * Если у всех метрик есть валидные `timestamps` — X-ось строится по реальному времени
 * (режим `time`), иначе — по индексу точки (режим `index`, обратная совместимость).
 * В режиме `time` точки ставятся по их timestamp, корректно показывая пропуски; общий
 * домен X — union всех timestamps, гайды недель — по границам недель.
 */
export function lineChartLayout(
  input: LineChartInput,
  width: number,
  metricHeight: number,
): LineChartLayout {
  const chartW = width - Y_AXIS_WIDTH
  const innerH = metricHeight - PAD_TOP - PAD_BOTTOM
  const metrics = input.metrics
  const useTime = allHaveTimestamps(metrics)
  const xMode: "time" | "index" = useTime ? "time" : "index"

  // Общий временной домен (union всех timestamps) — один для всех метрик.
  let timeDomain: { min: number; max: number } | null = null
  if (useTime) {
    let tMin = Infinity
    let tMax = -Infinity
    for (const m of metrics) {
      for (const t of m.timestamps ?? []) {
        if (t < tMin) tMin = t
        if (t > tMax) tMax = t
      }
    }
    if (Number.isFinite(tMin) && Number.isFinite(tMax)) {
      if (tMax - tMin < 86_400_000) {
        const mid = (tMin + tMax) / 2
        tMin = mid - 43_200_000
        tMax = mid + 43_200_000
      }
      const span = tMax - tMin
      const pad = span * 0.02
      timeDomain = { min: tMin - pad, max: tMax + pad }
    }
  }

  // Общий набор timestamps (из первой метрики) — для гайдов недель и общего xTicks.
  const firstTs = metrics[0]?.timestamps ?? []
  const commonWeekGuides = useTime && timeDomain ? buildWeekGuides(firstTs, chartW, timeDomain) : []
  const commonXTicks =
    useTime && timeDomain
      ? metrics[0]?.days
        ? buildXTicksByTime(firstTs, metrics[0].days, chartW).xTicks
        : []
      : metrics[0]?.days
        ? buildXTicks(metrics[0].days, chartW)
        : []
  const xCount = metrics[0]?.points.length ?? 0

  const layouts: LineMetricLayout[] = metrics.map((metric) => {
    const ys = metric.points.map((p) => p.y)
    const domain = niceNumberDomain(ys)
    const coords =
      useTime && timeDomain
        ? metric.points.map((p, i) => ({
            cx: timeToX(metric.timestamps![i]!, timeDomain, chartW),
            cy: moneyToY(p.y, domain, innerH) + PAD_TOP,
          }))
        : metric.points.map((p) => ({
            cx: indexToX(p.x, metric.points.length, chartW),
            cy: moneyToY(p.y, domain, innerH) + PAD_TOP,
          }))
    const yTicks = buildYTicks(domain, innerH).map((t) => ({
      y: t.y + PAD_TOP,
      label: t.label,
    }))
    const xTicks =
      useTime && timeDomain
        ? metric.days
          ? buildXTicksByTime(metric.timestamps ?? [], metric.days, chartW).xTicks.map((t) => ({
              x: timeToX(t.x, timeDomain, chartW),
              label: t.label,
            }))
          : []
        : metric.days
          ? buildXTicks(metric.days, chartW).map((t) => ({
              x: indexToX(t.x, metric.days.length, chartW),
              label: t.label,
            }))
          : []
    const gridLines = yTicks.map((t) => ({ y: t.y }))
    return {
      key: metric.key,
      label: metric.label,
      coords,
      yDomain: domain,
      yTicks,
      xTicks,
      gridLines,
      latest: metric.latest,
      delta: metric.delta,
      count: metric.points.length,
    }
  })

  return {
    metrics: layouts,
    xCount,
    xTicks: commonXTicks,
    weekGuides: commonWeekGuides,
    xMode,
  }
}

export const LINE_CHART_Y_AXIS_WIDTH = Y_AXIS_WIDTH
export const LINE_CHART_X_AXIS_HEIGHT = X_AXIS_HEIGHT
export const LINE_CHART_HEADER_HEIGHT = HEADER_HEIGHT
export const LINE_CHART_PAD_TOP = PAD_TOP
export const LINE_CHART_PAD_BOTTOM = PAD_BOTTOM
