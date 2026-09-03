/**
 * Геометрия вертикальной гистограммы по категориям (редизайн «Рынка» 2026-08-09):
 * заменяет все бывшие «полосы из кусков» (SegmentedBar) — воронка / что режет поток /
 * форматы / суб-баллы факторов шанса офферов. Категории по X, значения по Y, оси с тиками,
 * тултип при наведении на столбец. Без сегментных подписей, которые наезжали друг на друга.
 *
 * Одна форма (rows: [{key,label,value}]) — каждая категория отдельный столбец, общая шкала Y
 * (см. `yMax` в `CategoryBarsInput`, если нужен фиксированный потолок вместо максимума по данным).
 *
 * Чистая раскладка — без React, тестируется отдельно от `CategoryBars.tsx`.
 */

export type CategoryBar = {
  key: string
  label: string
  value: number
  /** Готовая доля 0..100 (например, бэковый `MarketBucket.pct`). Без неё и при включённом
   * `showPercent` доля считается от суммы `value` по всем строкам. */
  pct?: number
  /** Столбец-плейсхолдер (данных/формулы пока нет на бэке): рисуется минимальной высотой
   * независимо от `value` — иначе честный 0 был бы совсем невидим и ненаводим (тултип
   * «скоро» некуда было бы навести). Подпись значения над столбцом всё равно не рисуется
   * (условие — `value > 0`), так что плейсхолдер не выглядит как настоящий 0-балльный вклад. */
  placeholder?: boolean
  /** Подпись внутри столбца у его верхнего края (напр. «21 балл» — вклад фактора в итог).
   * Заменяет обычную подпись значения над столбцом. Без неё поведение не меняется. */
  inBarLabel?: string
  /** Подпись внутри столбца у его нижнего края (напр. вес фактора «25%»).
   * Рисуется только если столбец достаточно высок, чтобы вместить обе подписи без наезда.
   * Правка 2026-08-14: вес фактора перенесён из верха (где был `inBarLabel`) в низ, а в верх
   * добавлен вклад в итоговый балл (`inBarLabel`). */
  bottomInBarLabel?: string
}

export type CategoryBarsInput = {
  rows: readonly CategoryBar[]
  /** Подпись единиц Y для тултипа/оси — напр. «вак.» / «%» / «из 100». */
  unit?: string
  /** Фиксированный потолок оси Y; иначе — максимум по данным с запасом. */
  yMax?: number
  /** Подпись пустой оси, когда все значения нулевые. */
  emptyLabel?: string
  /** Ось Y и подпись над столбцом — доля от суммы строк (%), а не абсолютное число; период уже
   * задан шкалой сверху, само число видно в тултипе при наведении (`tooltipValueLabel`). */
  showPercent?: boolean
}

export type CategoryBarLayout = {
  key: string
  label: string
  value: number
  /** Координаты столбца в SVG-системе chart area. */
  x: number
  y: number
  width: number
  height: number
  /** Короткая подпись значения над столбцом («12», «62%»). */
  valueLabel: string
  /** Подпись для тултипа по умолчанию — всегда абсолютное число (даже при `showPercent: true`,
   * где `valueLabel` уже занят процентом над столбцом). */
  tooltipValueLabel: string
  /** Подпись категории под осью X — может быть повёрнута/усечена при тесноте. */
  xLabel: string
  /** Якорь подписи X. */
  xLabelAnchor: "start" | "middle" | "end"
  /** См. `CategoryBar.inBarLabel`. */
  inBarLabel?: string
  /** См. `CategoryBar.bottomInBarLabel`. */
  bottomInBarLabel?: string
  /** Полная высота столбца (для позиционирования нижней подписи в компоненте). */
  barHeight: number
}

export type CategoryYTick = {
  y: number
  label: string
}

export type CategoryBarsLayout = {
  rows: CategoryBarLayout[]
  yTicks: CategoryYTick[]
  gridLines: { y: number }[]
  /** Домен Y [0..max]. */
  yMin: number
  yMax: number
  /** Высота chart area (без осей). */
  chartH: number
  /** Ширина chart area (без отступа под ось Y). */
  chartW: number
  /** Сдвиг подписей X по высоте: 0 — горизонтальные, 1 — повёрнутые на 45°. */
  xLabelMode: "horizontal" | "rotated"
}

const Y_AXIS_WIDTH = 28
const X_AXIS_H = 16
const VALUE_LABEL_H = 14 // подпись значения над столбцом
const BAR_GAP = 0.18 // доля промежутка между столбцами от их ширины
const PLACEHOLDER_MIN_HEIGHT_FRAC = 0.12 // минимальная высота столбца-плейсхолдера от chartH

function formatYTick(v: number): string {
  if (v >= 1000) return `${(v / 1000).toLocaleString("ru-RU", { maximumFractionDigits: 1 })}к`
  if (Number.isInteger(v)) return String(v)
  return v.toLocaleString("ru-RU", { maximumFractionDigits: 1 })
}

/** «42%» — округляем до целых, дробные проценты не нужны на маленькой шкале. */
function formatPercentLabel(v: number): string {
  return `${Math.round(v)}%`
}

function niceMax(value: number): number {
  if (value <= 0) return 1
  if (value <= 5) return Math.ceil(value)
  // Округляем вверх к «красивой» границе.
  const mag = Math.pow(10, Math.floor(Math.log10(value)))
  const norm = value / mag
  const step = norm <= 1 ? 0.2 : norm <= 2 ? 0.5 : norm <= 5 ? 1 : 2
  return Math.ceil(norm / step) * step * mag
}

/**
 * Полная раскладка гистограммы по категориям. `width` — полная ширина контейнера,
 * `height` — полная высота (включая оси и подписи). Возвращает null, если нет данных
 * или габаритов слишком мало для отрисовки.
 */
export function categoryBarsLayout(
  input: CategoryBarsInput,
  width: number,
  height: number,
): CategoryBarsLayout | null {
  const rows = input.rows.filter((r) => Number.isFinite(r.value) && r.value >= 0)
  if (rows.length === 0 || width <= Y_AXIS_WIDTH + 4 || height <= X_AXIS_H + VALUE_LABEL_H + 4) {
    return null
  }

  const chartW = width - Y_AXIS_WIDTH
  const chartH = height - X_AXIS_H - VALUE_LABEL_H

  // В процентном режиме высота столбца считается от доли (бэковый `.pct`, иначе доля от суммы
  // строк), а не от абсолютного значения — но `value`/`tooltipValueLabel` остаются числом для
  // тултипа при наведении.
  const total = rows.reduce((sum, r) => sum + r.value, 0)
  const pctOf = (r: CategoryBar) => r.pct ?? (total > 0 ? (r.value / total) * 100 : 0)
  const yDatum = (r: CategoryBar) => (input.showPercent ? pctOf(r) : r.value)
  const formatY = input.showPercent ? formatPercentLabel : formatYTick

  const dataMax = Math.max(1, ...rows.map(yDatum))
  const yMax = input.yMax != null && input.yMax > 0 ? input.yMax : niceMax(dataMax)
  const yMin = 0

  const yTicks: CategoryYTick[] = [
    { y: chartH, label: formatY(yMin) },
    { y: chartH / 2, label: formatY((yMin + yMax) / 2) },
    { y: 0, label: formatY(yMax) },
  ]
  const gridLines = yTicks.map((t) => ({ y: t.y }))

  // Раскладываем столбцы: ширина поровну, с зазором.
  const slot = chartW / rows.length
  const barW = Math.max(2, slot * (1 - BAR_GAP))
  const barOffset = (slot - barW) / 2

  // Подписи X: поворачиваем, если подписи длинные и их много.
  const avgLabelLen = rows.reduce((sum, r) => sum + r.label.length, 0) / Math.max(1, rows.length)
  const xLabelMode: "horizontal" | "rotated" =
    rows.length > 4 && avgLabelLen > 5 ? "rotated" : "horizontal"

  const bars: CategoryBarLayout[] = rows.map((r, i) => {
    const cx = i * slot + slot / 2
    const x = i * slot + barOffset
    const rawH = yMax > 0 ? (yDatum(r) / yMax) * chartH : 0
    const h = r.placeholder ? Math.max(rawH, chartH * PLACEHOLDER_MIN_HEIGHT_FRAC) : rawH
    const y = chartH - h
    return {
      key: r.key,
      label: r.label,
      value: r.value,
      x,
      y,
      width: barW,
      height: Math.max(0, h),
      barHeight: Math.max(0, h),
      valueLabel: input.showPercent
        ? formatPercentLabel(pctOf(r))
        : formatValueLabel(r.value, input.unit),
      tooltipValueLabel: formatValueLabel(r.value, input.unit),
      xLabel: r.label,
      xLabelAnchor: anchorForX(cx, chartW, xLabelMode),
      inBarLabel: r.inBarLabel,
      bottomInBarLabel: r.bottomInBarLabel,
    }
  })

  return {
    rows: bars,
    yTicks,
    gridLines,
    yMin,
    yMax,
    chartH,
    chartW,
    xLabelMode,
  }
}

/** «12 вак.» / «62%» — подпись значения над столбцом. */
function formatValueLabel(value: number, unit?: string): string {
  const num = Number.isInteger(value)
    ? String(value)
    : value.toLocaleString("ru-RU", { maximumFractionDigits: 1 })
  return unit ? `${num} ${unit}` : num
}

function anchorForX(
  cx: number,
  chartW: number,
  mode: "horizontal" | "rotated",
): "start" | "middle" | "end" {
  if (mode === "rotated") return "end" // поворот на 45° — конец у точки
  if (cx <= 2) return "start"
  if (cx >= chartW - 2) return "end"
  return "middle"
}

export const CATEGORY_BARS_Y_AXIS_WIDTH = Y_AXIS_WIDTH
export const CATEGORY_BARS_X_AXIS_HEIGHT = X_AXIS_H
export const CATEGORY_BARS_VALUE_LABEL_HEIGHT = VALUE_LABEL_H
