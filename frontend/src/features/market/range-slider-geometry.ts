/**
 * Чистая геометрия фоновой линии шкалы периода (`PeriodRangeSlider`): «шанс офферов» по дням,
 * отрисованный на том же домене 0..100%, что и границы диапазона (`daysToPct`), чтобы линия и
 * бегунки не расходились друг с другом. Разрывы в `market_snapshots` не интерполируются — точка
 * ставится по календарной дате снимка, а не по порядковому номеру (иначе редкие снимки съезжали
 * бы влево/вправо от своих настоящих дат).
 */
import { daysToPct, RANGE_MAX_DAYS } from "./period-range"

export type RangeBackgroundInput = { day: string; value: number }
export type RangeBackgroundPoint = { xPct: number; yPct: number }

/** Календарных дней между `iso` (`YYYY-MM-DD`) и `now`, округлено; будущее — отрицательно. */
export function daysAgoFromIso(iso: string, now: Date = new Date()): number {
  const point = new Date(`${iso}T00:00:00Z`)
  const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate())
  return Math.round((today - point.getTime()) / 86_400_000)
}

/**
 * Точки фоновой линии на шкале 0..100%: `xPct` — календарная позиция (план: та же ось, что у
 * бегунков), `yPct` — нормализованное значение (0 = минимум окна, 100 = максимум). Меньше двух
 * точек или нулевой разброс значений → плоская/пустая линия не рисуется отдельно — вызывающий
 * решает по длине результата.
 */
export function rangeBackgroundPoints(
  points: readonly RangeBackgroundInput[],
  now: Date = new Date(),
  maxDays: number = RANGE_MAX_DAYS,
): RangeBackgroundPoint[] {
  if (points.length < 2) return []
  const values = points.map((p) => p.value)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min
  return points
    .map((p) => ({
      xPct: daysToPct(daysAgoFromIso(p.day, now), maxDays),
      yPct: span > 0 ? ((p.value - min) / span) * 100 : 50,
    }))
    .sort((a, b) => a.xPct - b.xPct)
}

/** SVG `points` для `<polyline>`, инвертируя Y (0% значения — низ, но SVG Y растёт вниз). */
export function rangeBackgroundPolyline(
  points: readonly RangeBackgroundPoint[],
  height: number,
): string {
  return points.map((p) => `${p.xPct},${height - (p.yPct / 100) * height}`).join(" ")
}

/**
 * Позиции засечек «начало дня» на шкале, % слева направо (план 2026-08-11, п.2): показывают,
 * куда можно сдвинуть границы — по дням, не произвольно. Прорежены шагом дней, если домен
 * широкий (много месяцев истории) и засечки иначе слились бы в сплошную полосу плотнее
 * `minSpacingPx` друг к другу.
 */
export function dayTickPositions(
  maxDays: number,
  trackWidthPx: number,
  minSpacingPx = 4,
): number[] {
  if (maxDays <= 0 || trackWidthPx <= 0) return []
  const maxTicks = Math.max(1, Math.floor(trackWidthPx / minSpacingPx))
  const step = Math.max(1, Math.ceil(maxDays / maxTicks))
  const ticks: number[] = []
  for (let day = 0; day <= maxDays; day += step) {
    ticks.push(daysToPct(day, maxDays))
  }
  return ticks
}

export { RANGE_MAX_DAYS }
