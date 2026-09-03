/**
 * Линейный график «Площадок» (шаг 5 плана редизайна «Деньги», правка 2026-08-11 — «Приглашения»
 * убраны, план п.6). Последнее значение/дельта каждой метрики — в шапке блока (`MarketSection`
 * meta, `MarketPage.tsx`), не врезаны в тело графика.
 *
 * Метрики (показы / просмотры), каждая на своей шкале с настоящими осями X (даты снимков) и Y
 * (значения), сеткой и тултипом по визиру. Старая форма рядов на общей оси прижимала бы ряды
 * к нулю — теперь у каждого свой честный масштаб. Без спарклайнов 90×24 — полноценные графики.
 *
 * Визир не снэпится к ближайшему снимку — скользит непрерывно по отрезку между соседними
 * точками (`chart-hover.ts::useInterpolatedHover`), а показанные значения/дата под курсором —
 * линейная аппроксимация между снимками (снимаются нерегулярно, «произвольный момент» иначе
 * был бы недоступен).
 *
 * Геометрия — в `line-chart-geometry.ts`, чистая и тестируемая отдельно.
 */
import { cn } from "@/lib/utils"
import { useContainerWidth } from "@/lib/use-container-width"
import { ChartTooltip } from "./ChartTooltip"
import {
  formatDayShort,
  LINE_CHART_HEADER_HEIGHT,
  LINE_CHART_PAD_BOTTOM,
  LINE_CHART_X_AXIS_HEIGHT,
  LINE_CHART_Y_AXIS_WIDTH,
  lineChartLayout,
  type LineChartInput,
  type LineCoord,
} from "./line-chart-geometry"
import { seriesClass } from "./series-tokens"
import { lerp, useInterpolatedHover, type InterpolatedPosition } from "./chart-hover"

export type LineChartProps = {
  input: LineChartInput
  /** Ширина в px; по умолчанию — ширина контейнера (заполняет ячейку, без пустоты справа). */
  width?: number
  /** Высота одной секции метрики (без оси X и шапки). */
  metricHeight?: number
  className?: string
}

/** Все ключи метрик в порядке — для стабильной раскраски через `seriesClass`. */
function allMetricKeys(input: LineChartInput): string[] {
  return input.metrics.map((m) => m.key)
}

function pathD(coords: readonly LineCoord[]): string {
  if (coords.length === 0) return ""
  return coords
    .map((c, i) => `${i === 0 ? "M" : "L"}${c.cx.toFixed(2)} ${c.cy.toFixed(2)}`)
    .join(" ")
}

/** Координата визира на отрезке между соседними точками метрики — линейная интерполяция
 * (план 2026-08-11 п.6), не снэп к ближайшей реальной точке. */
function interpolatedCoord(
  coords: readonly LineCoord[],
  position: InterpolatedPosition,
): LineCoord | null {
  const a = coords[position.index]
  const b = coords[position.nextIndex]
  if (!a || !b) return null
  return { cx: lerp(a.cx, b.cx, position.t), cy: lerp(a.cy, b.cy, position.t) }
}

/** Значение метрики на позиции визира — линейная интерполяция между соседними снимками, не
 * значение ближайшего снимка (то же обоснование, что и `interpolatedCoord`). */
function interpolatedValue(
  points: readonly { y: number }[],
  position: InterpolatedPosition,
): number | null {
  const a = points[position.index]
  const b = points[position.nextIndex]
  if (a == null && b == null) return null
  if (a == null) return b!.y
  if (b == null) return a.y
  return lerp(a.y, b.y, position.t)
}

/** Дата под визиром — интерполяция timestamp между соседними снимками (режим `time`); без
 * timestamps (режим `index`) — календарный день ближайшего конца сегмента. */
function interpolatedHeading(
  timestamps: readonly number[] | undefined,
  days: readonly string[],
  position: InterpolatedPosition,
): string | null {
  const ta = timestamps?.[position.index]
  const tb = timestamps?.[position.nextIndex]
  if (ta != null && tb != null) {
    return formatDayShort(new Date(lerp(ta, tb, position.t)).toISOString())
  }
  const day = position.t < 0.5 ? days[position.index] : days[position.nextIndex]
  return day ?? null
}

export function LineChart({ input, width, metricHeight = 90, className }: LineChartProps) {
  const { ref, width: containerWidth } = useContainerWidth<HTMLDivElement>(560)
  const effectiveWidth = width ?? containerWidth
  const layout = lineChartLayout(input, effectiveWidth, metricHeight)
  const keys = allMetricKeys(input)
  const totalH =
    layout.metrics.length * (LINE_CHART_HEADER_HEIGHT + metricHeight + LINE_CHART_X_AXIS_HEIGHT)

  // Общий визир скользит по позиции курсора непрерывно (план 2026-08-11 п.6) — все графики
  // подсвечивают одну и ту же интерполированную точку на общей оси времени. Координаты берём из
  // первой метрики (домен X общий), но визир и интерполированное значение считаем в каждом блоке.
  const firstCoords = layout.metrics[0]?.coords ?? []
  const hover = useInterpolatedHover<SVGSVGElement>(
    firstCoords,
    effectiveWidth - LINE_CHART_Y_AXIS_WIDTH,
  )
  const { position, containerRef, handlers } = hover

  if (layout.metrics.length === 0) return null

  return (
    <div ref={ref} className={cn("relative min-w-0", className)} data-testid="line-chart">
      <svg
        ref={containerRef}
        width={effectiveWidth}
        height={totalH}
        viewBox={`0 0 ${effectiveWidth} ${totalH}`}
        className="block overflow-visible"
        role="img"
        aria-label="Площадки: показы, просмотры"
        tabIndex={0}
        onPointerMove={handlers.onPointerMove}
        onPointerLeave={handlers.onPointerLeave}
        onClick={handlers.onClick}
        onFocus={handlers.onFocus}
        onBlur={handlers.onBlur}
        onKeyDown={handlers.onKeyDown}
      >
        {layout.metrics.map((metric, mIdx) => {
          const offsetY =
            mIdx * (LINE_CHART_HEADER_HEIGHT + metricHeight + LINE_CHART_X_AXIS_HEIGHT)
          const chartW = width - LINE_CHART_Y_AXIS_WIDTH
          const strokeClass = seriesClass("stroke", metric.key, keys)
          const d = pathD(metric.coords)
          const activeCoord = position ? interpolatedCoord(metric.coords, position) : null

          return (
            <g key={metric.key} transform={`translate(0 ${offsetY})`}>
              {/* Chart area со сдвигом под ось Y и небольшой верхний зазор. */}
              <g transform={`translate(${LINE_CHART_Y_AXIS_WIDTH} ${LINE_CHART_HEADER_HEIGHT})`}>
                {/* Вертикальные гайды по границам недель — общая временная сетка во всех панелях. */}
                {layout.weekGuides.map((g, i) => (
                  <line
                    key={`week-${metric.key}-${i}`}
                    x1={g.x}
                    x2={g.x}
                    y1={0}
                    y2={metricHeight}
                    className="text-slate-100"
                    stroke="currentColor"
                    strokeWidth={1}
                    strokeDasharray="2 3"
                  />
                ))}
                {/* Сетка + тики оси Y. */}
                {metric.gridLines.map((line, i) => (
                  <line
                    key={`grid-${metric.key}-${i}`}
                    x1={0}
                    x2={chartW}
                    y1={line.y}
                    y2={line.y}
                    className="text-slate-100"
                    stroke="currentColor"
                    strokeWidth={1}
                  />
                ))}
                {metric.yTicks.map((tick, i) => (
                  <text
                    key={`ytick-${metric.key}-${i}`}
                    x={-10}
                    y={tick.y + 3}
                    textAnchor="end"
                    className="fill-slate-500 text-xs font-medium tabular-nums"
                  >
                    {tick.label}
                  </text>
                ))}

                {/* Линия. */}
                {d ? (
                  <path
                    d={d}
                    fill="none"
                    className={cn("stroke-1.5", strokeClass)}
                    stroke="currentColor"
                    strokeWidth={1.5}
                    strokeLinejoin="round"
                    strokeLinecap="round"
                  />
                ) : null}

                {/* Визир — вертикальная линия + точка. */}
                {activeCoord ? (
                  <>
                    <line
                      x1={activeCoord.cx}
                      x2={activeCoord.cx}
                      y1={0}
                      y2={metricHeight}
                      className="text-slate-300"
                      stroke="currentColor"
                      strokeWidth={1}
                    />
                    <circle
                      cx={activeCoord.cx}
                      cy={activeCoord.cy}
                      r={2.5}
                      className={cn(strokeClass, "fill-white")}
                      stroke="currentColor"
                      strokeWidth={1.5}
                    />
                  </>
                ) : null}

                {/* Ось X. */}
                <line
                  x1={0}
                  x2={chartW}
                  y1={metricHeight}
                  y2={metricHeight}
                  className="text-slate-200"
                  stroke="currentColor"
                  strokeWidth={1}
                />
                {metric.xTicks.map((tick, i) => (
                  <text
                    key={`xtick-${metric.key}-${i}`}
                    x={tick.x}
                    y={metricHeight + 12}
                    textAnchor="middle"
                    className="fill-slate-400 text-[10px] tabular-nums"
                  >
                    {tick.label}
                  </text>
                ))}
              </g>
            </g>
          )
        })}
      </svg>

      {/* Общий тултип — три метрики в одном блоке под одной интерполированной датой (план
          2026-08-11 п.6): значения — линейная аппроксимация между соседними снимками, не
          значения ближайшего снимка, курсор можно спокойно двигать вдоль линии. */}
      {position && input.metrics[0]
        ? (() => {
            const heading = interpolatedHeading(
              input.metrics[0]!.timestamps,
              input.metrics[0]!.days,
              position,
            )
            const coord = interpolatedCoord(firstCoords, position)
            if (!heading || !coord) return null
            return (
              <ChartTooltip
                x={LINE_CHART_Y_AXIS_WIDTH + coord.cx}
                y={LINE_CHART_HEADER_HEIGHT + LINE_CHART_PAD_BOTTOM}
                heading={heading}
                rows={input.metrics.map((metric) => {
                  const value = interpolatedValue(metric.points, position)
                  return {
                    key: metric.key,
                    label: metric.label,
                    value: value != null ? Math.round(value).toLocaleString("ru-RU") : "—",
                    swatchClassName: seriesClass("bg", metric.key, keys),
                  }
                })}
              />
            )
          })()
        : null}
    </div>
  )
}
