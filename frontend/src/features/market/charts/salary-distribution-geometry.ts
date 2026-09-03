/**
 * Геометрия гистограммы «Зарплаты» (редизайн 2026-08-11, шаг 2 плана «Деньги»).
 *
 * Настоящий bar chart: ось X (зарплатные корзины), ось Y (количество вакансий), сетка,
 * скобка целевой вилки под осью, тонкая линия медианы, точки офферов. Чистая раскладка —
 * без React, тестируется отдельно от `SalaryDistribution.tsx`.
 *
 * Домен режется по перцентилям P5–P95 (не по разрыву-эвристике `robustDomain`, как раньше):
 * нижние/верхние 5% точек сворачиваются в крайние корзины, а не растягивают шкалу на себя.
 * Медиана/P25/P75 в подписи считаются от ПОЛНОГО ряда (не усечённого) — эти числа должны
 * быть точными независимо от того, как урезан домен гистограммы.
 *
 * Редизайн убрал: сплошную заливку зоны цели на всю высоту графика (читалась как случайный
 * артефакт) — заменена тонкой скобкой под осью; три подписи маркеров (медиана/P25/P75),
 * разведённые по строкам — свёрнуты в одну текстовую строку над графиком (компонент), в SVG
 * остаётся только тонкая линия медианы и две короткие незаподписанные насечки P25/P75.
 */
import { clampPct } from "./pct"

export type SalaryBucket = {
  from: number
  to: number
  count: number
}

export type SalaryDomain = { min: number; max: number }

export type SalaryBar = {
  key: string
  /** X-координата левого края столбика, px. */
  x: number
  /** Ширина столбика, px (с зазором между соседями). */
  width: number
  /** Высота столбика, px. */
  height: number
  /** Y-координата верха столбика, px. */
  y: number
  count: number
  /** Середина корзины в деньгах — для тултипа. */
  mid: number
}

export type SalaryAxisTick = {
  /** Позиция в px от левого края chart area. */
  x: number
  /** Подпись («300к»). */
  label: string
  /** Якорь подписи — у краёв текст растёт внутрь, чтобы не обрезаться контейнером
   * (крайняя подпись, центрированная ровно на границе, иначе половиной уходит за карточку). */
  anchor: SalaryMarkerAnchor
}

export type SalaryYTick = {
  y: number
  label: string
}

export type SalaryMarkerAnchor = "start" | "middle" | "end"

/** Скобка целевой вилки — тонкая линия с засечками под осью X, без заливки на всю высоту. */
export type SalaryTargetBracket = {
  x: number
  width: number
  label: string
  labelAnchor: SalaryMarkerAnchor
}

/** Тонкая вертикальная линия медианы через область столбиков — без подписи в SVG (подпись
 * с числом — в текстовой строке над графиком, `SalaryDistribution.tsx`). */
export type SalaryMedianMarker = {
  x: number
}

/** Короткая незаподписанная насечка P25/P75 на оси X. */
export type SalaryQuartileTick = {
  key: "p25" | "p75"
  x: number
}

export type SalaryOfferMarker = {
  key: string
  x: number
  label: string
  /** Номер полосы (0=верх) для подписей, не наезжающих друг на друга. */
  lane: number
}

export type SalaryDistributionLayout = {
  bars: SalaryBar[]
  xTicks: SalaryAxisTick[]
  yTicks: SalaryYTick[]
  gridLines: { y: number }[]
  targetBracket: SalaryTargetBracket | null
  medianMarker: SalaryMedianMarker | null
  quartileTicks: SalaryQuartileTick[]
  offerMarkers: SalaryOfferMarker[]
  /** Высота одной строки подписей офферов под осью X, px. */
  offerLaneHeight: number
}

export const SALARY_BUCKET_COUNT = 10
export const MIN_HISTOGRAM_POINTS = 5
const BAR_GAP_PX = 3
const OFFER_LANE_HEIGHT_PX = 16
const OFFER_LABEL_GAP_PX = 4
/** Урезаем домен гистограммы по нижним/верхним 5% — выбросы сворачиваются в крайние корзины,
 * не растягивают шкалу. */
const OUTLIER_TRIM_PCT = 0.05
/** Отступ от края (в %), внутри которого подпись цепляется этим концом за край, а не серединой. */
const EDGE_GUARD_PCT = 10

/** `300к` — компактная подпись оси. */
export function formatSalaryShort(value: number): string {
  return `${Math.round(value / 1000)}к`
}

/** Якорь подписи по позиции на оси: у краёв текст растёт внутрь, чтобы не обрезаться контейнером. */
export function markerAnchorFor(xPx: number, chartW: number): SalaryMarkerAnchor {
  const pct = chartW > 0 ? (xPx / chartW) * 100 : 50
  if (pct <= EDGE_GUARD_PCT) return "start"
  if (pct >= 100 - EDGE_GUARD_PCT) return "end"
  return "middle"
}

/** «18%» — округляем до целых, доля бакета от всех точек гистограммы. */
function formatSharePct(value: number): string {
  return `${Math.round(value)}%`
}

/** `374 000 ₽` — полная форма для тултипа. */
export function formatMoneyFull(value: number): string {
  return `${Math.round(value)
    .toLocaleString("ru-RU")
    .replace(/\u00A0/g, " ")} ₽`
}

/** Перцентиль отсортированного (по возрастанию) ряда, линейная интерполяция между соседями. */
function percentileOf(sortedAsc: readonly number[], p: number): number {
  const n = sortedAsc.length
  if (n === 0) return 0
  if (n === 1) return sortedAsc[0]!
  const idx = p * (n - 1)
  const lo = Math.floor(idx)
  const hi = Math.ceil(idx)
  if (lo === hi) return sortedAsc[lo]!
  const frac = idx - lo
  return sortedAsc[lo]! + (sortedAsc[hi]! - sortedAsc[lo]!) * frac
}

/** Домен по P5–P95: нижние/верхние 5% точек сворачиваются в крайние корзины при бакетировании
 * (`salaryBuckets` кламппит точку в границы домена), а не растягивают шкалу на выброс. */
function trimmedDomain(sorted: readonly number[]): SalaryDomain | null {
  const n = sorted.length
  if (n === 0) return null
  if (n < 2) return { min: sorted[0]!, max: sorted[0]! }
  const min = percentileOf(sorted, OUTLIER_TRIM_PCT)
  const max = percentileOf(sorted, 1 - OUTLIER_TRIM_PCT)
  if (max > min) return { min, max }
  return { min: sorted[0]!, max: sorted[n - 1]! }
}

/**
 * Равномерные корзины по ряду net-середин. Меньше `MIN_HISTOGRAM_POINTS` или
 * все значения совпадают → `[]` (честно не рисуем вместо одной обманчивой корзины).
 */
export function salaryBuckets(
  points: readonly number[],
  bucketCount = SALARY_BUCKET_COUNT,
): SalaryBucket[] {
  if (points.length < MIN_HISTOGRAM_POINTS) return []
  const sorted = [...points].sort((a, b) => a - b)
  const domain = trimmedDomain(sorted)
  if (!domain || !(domain.max > domain.min)) return []
  const span = domain.max - domain.min
  const buckets: SalaryBucket[] = Array.from({ length: bucketCount }, (_, i) => ({
    from: domain.min + (span * i) / bucketCount,
    to: domain.min + (span * (i + 1)) / bucketCount,
    count: 0,
  }))
  for (const p of sorted) {
    const clamped = Math.min(domain.max, Math.max(domain.min, p))
    const idx = Math.min(
      bucketCount - 1,
      Math.max(0, Math.floor(((clamped - domain.min) / span) * bucketCount)),
    )
    buckets[idx]!.count += 1
  }
  return buckets
}

function domainOf(buckets: readonly SalaryBucket[]): SalaryDomain | null {
  if (buckets.length === 0) return null
  return { min: buckets[0]!.from, max: buckets[buckets.length - 1]!.to }
}

function moneyToX(value: number, domain: SalaryDomain, chartW: number): number {
  const span = domain.max - domain.min
  if (span <= 0) return chartW / 2
  const clamped = Math.min(domain.max, Math.max(domain.min, value))
  return ((clamped - domain.min) / span) * chartW
}

/** Приближённая ширина подписи в px (~6.2px/символ на 12px кириллице). */
function estimateLabelWidthPx(label: string): number {
  return 14 + label.length * 6.2
}

/**
 * Разводит подписи офферов по полосам, чтобы соседние не наезжали друг на друга.
 * Жадная раскраска: ближайшую свободную полосу, где хвост предыдущей + зазор ≤ x.
 */
function assignOfferLanes(
  markers: readonly { key: string; x: number; label: string }[],
): SalaryOfferMarker[] {
  const sorted = [...markers].sort((a, b) => a.x - b.x)
  const laneEnds: number[] = []
  const placed: SalaryOfferMarker[] = []
  for (const m of sorted) {
    const half = estimateLabelWidthPx(m.label) / 2
    const start = m.x - half
    const end = m.x + half
    let lane = 0
    while (lane < laneEnds.length && start < laneEnds[lane]! + OFFER_LABEL_GAP_PX) lane++
    laneEnds[lane] = end
    placed.push({ key: m.key, x: m.x, label: m.label, lane })
  }
  return placed
}

export type SalaryDistributionInput = {
  points: readonly number[]
  targetMin?: number | null
  targetMax?: number | null
  median?: number | null
  p25?: number | null
  p75?: number | null
  offers: readonly { key: string; company: string; value: number }[]
}

/**
 * Сборка полной раскладки гистограммы. `width` — ширина chart area (без отступов
 * под ось Y слева и подписи справа), `height` — высота области столбиков (без
 * оси X и зоны офферов снизу).
 */
export function salaryDistributionLayout(
  input: SalaryDistributionInput,
  width: number,
  height: number,
): SalaryDistributionLayout | null {
  const buckets = salaryBuckets(input.points)
  const domain = domainOf(buckets)
  if (!domain) return null

  const maxCount = Math.max(1, ...buckets.map((b) => b.count))
  const innerW = width
  const bucketW = innerW / buckets.length

  const bars: SalaryBar[] = buckets.map((b, i) => {
    const h = (b.count / maxCount) * height
    return {
      key: `bar-${i}`,
      x: i * bucketW + BAR_GAP_PX / 2,
      width: Math.max(1, bucketW - BAR_GAP_PX),
      height: h,
      y: height - h,
      count: b.count,
      mid: (b.from + b.to) / 2,
    }
  })

  // Тики оси X: подписываем каждую 2-ю корзину (от max назад), чтобы не сливались.
  const xTicks: SalaryAxisTick[] = []
  const tickStep = buckets.length > 6 ? 2 : 1
  for (let i = buckets.length; i >= 0; i -= tickStep) {
    const value = i === buckets.length ? domain.max : (buckets[i]?.from ?? domain.min)
    const x = clampPct((i / buckets.length) * 100) * (innerW / 100)
    xTicks.push({ x, label: formatSalaryShort(value), anchor: markerAnchorFor(x, innerW) })
  }

  // Тики оси Y — доля бакета от всех точек гистограммы (%), не сырое число вакансий: период
  // уже задан шкалой сверху, а само число видно в тултипе при наведении на столбик.
  const totalCount = buckets.reduce((s, b) => s + b.count, 0)
  const maxPct = totalCount > 0 ? (maxCount / totalCount) * 100 : 0
  const yTicks: SalaryYTick[] = [
    { y: height, label: formatSharePct(0) },
    { y: height / 2, label: formatSharePct(maxPct / 2) },
    { y: 0, label: formatSharePct(maxPct) },
  ]
  const gridLines = yTicks.map((t) => ({ y: t.y }))

  // Скобка целевой вилки — тонкая линия с засечками под осью, без заливки на всю высоту графика.
  let targetBracket: SalaryTargetBracket | null = null
  if (input.targetMin != null && input.targetMax != null) {
    const lo = moneyToX(Math.min(input.targetMin, input.targetMax), domain, innerW)
    const hi = moneyToX(Math.max(input.targetMin, input.targetMax), domain, innerW)
    const labelX = (lo + hi) / 2
    targetBracket = {
      x: Math.min(lo, hi),
      width: Math.max(1, hi - lo),
      label: "Целевая вилка",
      labelAnchor: markerAnchorFor(labelX, innerW),
    }
  }

  // Медиана — тонкая линия без подписи в SVG (число — в текстовой строке над графиком).
  const medianMarker: SalaryMedianMarker | null =
    input.median != null ? { x: moneyToX(input.median, domain, innerW) } : null

  // P25/P75 — короткие незаподписанные насечки на оси, без текста (число — тоже в строке над
  // графиком), поэтому им не нужно разведение по строкам.
  const quartileTicks: SalaryQuartileTick[] = []
  if (input.p25 != null) {
    quartileTicks.push({ key: "p25", x: moneyToX(input.p25, domain, innerW) })
  }
  if (input.p75 != null) {
    quartileTicks.push({ key: "p75", x: moneyToX(input.p75, domain, innerW) })
  }

  // Точки офферов на оси X.
  const offerInputs = input.offers
    .filter((o) => Number.isFinite(o.value))
    .map((o) => ({
      key: o.key,
      x: moneyToX(o.value, domain, innerW),
      label: o.company,
    }))
  const offerMarkers = assignOfferLanes(offerInputs)

  return {
    bars,
    xTicks,
    yTicks,
    gridLines,
    targetBracket,
    medianMarker,
    quartileTicks,
    offerMarkers,
    offerLaneHeight: OFFER_LANE_HEIGHT_PX,
  }
}
